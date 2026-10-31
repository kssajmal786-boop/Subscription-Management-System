"""
accounts/decorators.py
Role-Based Access Control (RBAC) and Anti-IDOR decorators for Subscribify view endpoints.
"""
from functools import wraps
from django.shortcuts import redirect, get_object_or_404
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseForbidden, JsonResponse


def role_required(*allowed_roles):
    """Decorator ensuring authenticated user has one of the specified roles."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.path.startswith('/api/'):
                    return JsonResponse({'success': False, 'message': 'Authentication required.'}, status=401)
                return redirect('accounts:login')

            if request.user.role not in allowed_roles:
                # Log authorization violation
                from accounts.models import UserAuditLog
                ip = request.META.get('REMOTE_ADDR')
                UserAuditLog.objects.create(
                    user=request.user,
                    actor=request.user,
                    action='PERMISSION_DENIED',
                    ip_address=ip,
                    details=f'Access denied for {request.path}. Allowed roles: {allowed_roles}, User role: {request.user.role}'
                )
                if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.path.startswith('/api/'):
                    return JsonResponse({'success': False, 'message': 'Access forbidden.'}, status=403)
                messages.error(request, 'You do not have authorization to access this operational screen.')
                return redirect('dashboard:index')

            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def admin_required(view_func):
    """Ensure user is an Administrator."""
    return role_required('Admin')(view_func)


def staff_or_admin_required(view_func):
    """Ensure user is an Operations Staff member or Administrator."""
    return role_required('Admin', 'Staff')(view_func)


def customer_required(view_func):
    """Ensure user is a Customer."""
    return role_required('Customer')(view_func)


def prevent_customer_idor(param_name='pk'):
    """
    IDOR (Insecure Direct Object Reference) prevention decorator.
    If current user is a Customer, strictly prevents them from querying or modifying
    another customer's profile, subscriptions, or invoices.
    Staff and Admin users pass through transparently.
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('accounts:login')

            target_id = kwargs.get(param_name)
            if request.user.role == 'Customer':
                customer_profile = getattr(request.user, 'customer_profile', None)
                if not customer_profile or str(customer_profile.pk) != str(target_id):
                    from accounts.models import UserAuditLog
                    ip = request.META.get('REMOTE_ADDR')
                    UserAuditLog.objects.create(
                        user=request.user,
                        actor=request.user,
                        action='PERMISSION_DENIED',
                        ip_address=ip,
                        details=f'IDOR attempt on customer id {target_id} by customer {getattr(customer_profile, "pk", None)}'
                    )
                    messages.error(request, 'Access denied. You may only view your own corporate records.')
                    return redirect('dashboard:customer')

            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator
