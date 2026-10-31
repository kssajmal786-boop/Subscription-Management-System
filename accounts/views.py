"""
accounts/views.py
Web controller views for Authentication, RBAC, Customer Management,
Staff Provisioning, Password Lifecycle, and User Directory Administration.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseForbidden
from django.utils import timezone
from django.core.paginator import Paginator

from accounts.models import (
    User, Customer, Staff, PasswordResetToken,
    EmailVerificationToken, UserAuditLog
)
from accounts.forms import (
    LoginForm, CustomerRegistrationForm, ForgotPasswordForm,
    ResetPasswordForm, ChangePasswordForm, ProfileUpdateForm,
    CustomerProfileForm, StaffCreationForm, StaffUpdateForm,
    CustomerAdminForm
)
from accounts.services import (
    AuthService, CustomerService, StaffService, PasswordPolicyValidator
)
from accounts.decorators import (
    admin_required, staff_or_admin_required, customer_required,
    prevent_customer_idor
)


def get_client_ip(request):
    """Safely extracts client IP address accounting for proxies."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


# ── Authentication Views ──────────────────────────────────────────────────────

def login_view(request):
    """
    Session login view with brute-force lockout handling and role-based redirect.
    """
    if request.user.is_authenticated:
        return redirect('dashboard:index')

    form = LoginForm(request.POST or None)
    error_msg = None

    if request.method == 'POST' and form.is_valid():
        email = form.cleaned_data['email']
        password = form.cleaned_data['password']
        remember_me = form.cleaned_data.get('remember_me', False)
        ip = get_client_ip(request)

        user, err = AuthService.authenticate_user(request, email, password, ip_address=ip)
        if user:
            auth_login(request, user)
            if remember_me:
                request.session.set_expiry(60 * 60 * 24 * 30)  # 30 days
            else:
                request.session.set_expiry(0)  # On browser close

            messages.success(request, f'Welcome back, {user.name}!')
            next_url = request.GET.get('next') or request.POST.get('next')
            if next_url and next_url.startswith('/'):
                return redirect(next_url)
            return redirect('dashboard:index')
        else:
            error_msg = err

    return render(request, 'registration/login.html', {
        'form': form,
        'error': error_msg,
    })


def logout_view(request):
    """Terminates session and records audit event."""
    if request.user.is_authenticated:
        ip = get_client_ip(request)
        UserAuditLog.objects.create(
            user=request.user,
            actor=request.user,
            action='LOGOUT',
            ip_address=ip,
            details=f'User {request.user.email} signed out.'
        )
    auth_logout(request)
    messages.info(request, 'You have been securely signed out.')
    return redirect('accounts:login')


def register_view(request):
    """
    Customer self-registration with company info and email verification initiation.
    """
    if request.user.is_authenticated:
        return redirect('dashboard:index')

    form = CustomerRegistrationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        ip = get_client_ip(request)
        try:
            user, customer, token = AuthService.register_customer(
                name=form.cleaned_data['name'],
                email=form.cleaned_data['email'],
                password=form.cleaned_data['password'],
                company_name=form.cleaned_data.get('company_name', ''),
                phone=form.cleaned_data.get('phone', ''),
                gst_number=form.cleaned_data.get('gst_number', ''),
                billing_address=form.cleaned_data.get('billing_address', ''),
                city=form.cleaned_data.get('city', ''),
                state=form.cleaned_data.get('state', ''),
                pincode=form.cleaned_data.get('pincode', ''),
                ip_address=ip,
            )
            # Auto login customer
            auth_login(request, user)
            messages.success(request, 'Account created! Please check your email to verify your address.')
            return redirect('accounts:verification_sent')
        except ValueError as e:
            form.add_error(None, str(e))

    return render(request, 'registration/register.html', {'form': form})


def verification_sent_view(request):
    """Informs customer of dispatched verification instructions."""
    return render(request, 'registration/verification_sent.html')


def verify_email_view(request, token):
    """Validates email token and marks account as email_verified."""
    ip = get_client_ip(request)
    success, msg = AuthService.verify_email(token, ip_address=ip)
    return render(request, 'registration/verify_email.html', {
        'success': success,
        'message': msg,
    })


@login_required
def resend_verification_view(request):
    """Resends email verification instructions for active session."""
    user = request.user
    if user.email_verified:
        messages.info(request, 'Your email address is already verified.')
        return redirect('dashboard:index')

    token = EmailVerificationToken.generate_for_user(user)
    AuthService.send_verification_email(user, token)
    messages.success(request, 'A fresh verification link has been sent to your email.')
    return redirect('accounts:verification_sent')


def forgot_password_view(request):
    """Initiates password reset without leaking existence of email."""
    form = ForgotPasswordForm(request.POST or None)
    sent = False

    if request.method == 'POST' and form.is_valid():
        email = form.cleaned_data['email']
        ip = get_client_ip(request)
        AuthService.request_password_reset(email, ip_address=ip)
        sent = True

    return render(request, 'registration/forgot_password.html', {'form': form, 'sent': sent})


def reset_password_view(request, token):
    """Validates reset token and saves new password."""
    token_obj = PasswordResetToken.objects.filter(token=token).select_related('user').first()
    if not token_obj or not token_obj.is_valid():
        messages.error(request, 'This reset link has expired or has already been used.')
        return redirect('accounts:login')

    form = ResetPasswordForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        ip = get_client_ip(request)
        success, msg = AuthService.reset_password(
            token_str=token,
            new_password=form.cleaned_data['new_password'],
            ip_address=ip
        )
        if success:
            messages.success(request, msg)
            return redirect('accounts:login')
        else:
            form.add_error(None, msg)

    return render(request, 'registration/reset_password.html', {'form': form, 'token': token})


@login_required
def change_password_view(request):
    """Allows authenticated user to change password."""
    form = ChangePasswordForm(request.user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        new_pwd = form.cleaned_data['new_password']
        request.user.set_password(new_pwd)
        request.user.save()
        # Keep user logged in after password change
        from django.contrib.auth import update_session_auth_hash
        update_session_auth_hash(request, request.user)

        ip = get_client_ip(request)
        UserAuditLog.objects.create(
            user=request.user,
            actor=request.user,
            action='PASSWORD_RESET_DONE',
            ip_address=ip,
            details='User changed password from profile screen.'
        )
        messages.success(request, 'Your password has been changed successfully.')
        return redirect('accounts:profile')

    return render(request, 'shared/change_password.html', {'form': form})


# ── Profile Management ────────────────────────────────────────────────────────

@login_required
def profile_view(request):
    """
    User self-profile view and update.
    Customers edit company metadata; Staff/Admin edit personal information.
    """
    user = request.user
    customer_profile = getattr(user, 'customer_profile', None)

    user_form = ProfileUpdateForm(instance=user)
    customer_form = CustomerProfileForm(instance=customer_profile) if customer_profile else None
    pwd_form = ChangePasswordForm(user)

    if request.method == 'POST':
        action = request.POST.get('action', 'profile')
        if action == 'profile':
            user_form = ProfileUpdateForm(request.POST, instance=user)
            if customer_profile:
                customer_form = CustomerProfileForm(request.POST, instance=customer_profile)
                if user_form.is_valid() and customer_form.is_valid():
                    user_form.save()
                    customer_form.save()
                    messages.success(request, 'Profile details updated successfully.')
                    return redirect('accounts:profile')
            else:
                if user_form.is_valid():
                    user_form.save()
                    messages.success(request, 'Profile updated.')
                    return redirect('accounts:profile')

        elif action == 'password':
            pwd_form = ChangePasswordForm(user, request.POST)
            if pwd_form.is_valid():
                user.set_password(pwd_form.cleaned_data['new_password'])
                user.save()
                from django.contrib.auth import update_session_auth_hash
                update_session_auth_hash(request, user)
                messages.success(request, 'Password updated successfully.')
                return redirect('accounts:profile')

    return render(request, 'shared/profile.html', {
        'form': user_form,
        'customer_profile': customer_profile,
        'customer_form': customer_form,
        'pwd_form': pwd_form,
    })


# ── Customer Management (Staff / Admin) ───────────────────────────────────────

@login_required
@staff_or_admin_required
def customer_list_view(request):
    """
    Searchable, filterable customer directory.
    Filters: keyword search, status (Active, Inactive, Pending_Verification).
    """
    search = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()

    customers_qs = CustomerService.search_and_filter(query=search, status=status_filter)

    paginator = Paginator(customers_qs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'staff/customer_list.html', {
        'customers': page_obj,
        'search': search,
        'status_filter': status_filter,
        'status_choices': Customer.STATUS_CHOICES,
        'total_count': customers_qs.count(),
    })


@login_required
@staff_or_admin_required
def customer_create_view(request):
    """Staff/Admin creates customer account directly."""
    form = CustomerAdminForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        ip = get_client_ip(request)
        try:
            data = form.cleaned_data
            data['name'] = form.cleaned_data['name']
            data['email'] = form.cleaned_data['email']
            data['is_active'] = form.cleaned_data.get('is_active', True)
            data['email_verified'] = True  # Staff created customers pre-verified

            customer = CustomerService.create_customer_by_staff(
                data=data,
                creator_user=request.user,
                ip_address=ip
            )
            messages.success(request, f'Customer account for {customer.display_name} created.')
            return redirect('accounts:customer_detail', pk=customer.pk)
        except ValueError as e:
            form.add_error(None, str(e))

    return render(request, 'staff/customer_form.html', {
        'form': form,
        'title': 'Add Customer Account',
        'is_create': True,
    })


@login_required
@prevent_customer_idor('pk')
def customer_detail_view(request, pk):
    """
    Detailed profile view for a customer.
    Enforces anti-IDOR: Customer users can only open their own customer pk.
    """
    customer = get_object_or_404(Customer.objects.select_related('user'), pk=pk)
    subscriptions = customer.subscriptions.select_related('plan').order_by('-created_at')
    invoices = customer.invoices.order_by('-invoice_date')[:10]

    return render(request, 'staff/customer_detail.html', {
        'customer': customer,
        'subscriptions': subscriptions,
        'invoices': invoices,
    })


@login_required
@staff_or_admin_required
def customer_edit_view(request, pk):
    """Staff/Admin modifies customer information."""
    customer = get_object_or_404(Customer.objects.select_related('user'), pk=pk)
    form = CustomerAdminForm(request.POST or None, instance=customer)

    if request.method == 'POST' and form.is_valid():
        ip = get_client_ip(request)
        try:
            CustomerService.update_customer_profile(
                customer=customer,
                data=form.cleaned_data,
                actor_user=request.user,
                ip_address=ip
            )
            messages.success(request, f'Customer {customer.display_name} updated successfully.')
            return redirect('accounts:customer_detail', pk=customer.pk)
        except ValueError as e:
            form.add_error(None, str(e))

    return render(request, 'staff/customer_form.html', {
        'form': form,
        'customer': customer,
        'title': f'Edit Customer: {customer.display_name}',
        'is_create': False,
    })


@login_required
@staff_or_admin_required
def customer_toggle_active_view(request, pk):
    """Activate or deactivate a customer account."""
    customer = get_object_or_404(Customer.objects.select_related('user'), pk=pk)
    ip = get_client_ip(request)
    new_state = CustomerService.toggle_customer_status(customer, actor_user=request.user, ip_address=ip)
    label = 'activated' if new_state else 'suspended'
    messages.success(request, f'Customer {customer.display_name} has been {label}.')
    return redirect('accounts:customer_list')


# ── Staff Management (Admin Only) ─────────────────────────────────────────────

@login_required
@admin_required
def staff_list_view(request):
    """Admin view listing all operational staff members."""
    staff_members = Staff.objects.select_related('user').order_by('-created_at')
    return render(request, 'admin_dash/staff_list.html', {
        'staff_members': staff_members
    })


@login_required
@admin_required
def staff_create_view(request):
    """Admin provisioning of new Staff or Admin accounts."""
    form = StaffCreationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        ip = get_client_ip(request)
        try:
            staff = StaffService.create_staff(
                email=form.cleaned_data['email'],
                password=form.cleaned_data['password'],
                name=form.cleaned_data['name'],
                role=form.cleaned_data['role'],
                employee_code=form.cleaned_data['employee_code'],
                department=form.cleaned_data.get('department', ''),
                designation=form.cleaned_data.get('designation', ''),
                creator_user=request.user,
                ip_address=ip,
            )
            messages.success(request, f'Staff member {staff.user.name} ({staff.employee_code}) created.')
            return redirect('accounts:staff_list')
        except ValueError as e:
            form.add_error(None, str(e))

    return render(request, 'admin_dash/staff_form.html', {
        'form': form,
        'title': 'Add Staff Member',
        'is_create': True,
    })


@login_required
@admin_required
def staff_edit_view(request, pk):
    """Admin edits staff information and designation."""
    staff = get_object_or_404(Staff.objects.select_related('user'), pk=pk)
    form = StaffUpdateForm(request.POST or None, instance=staff)

    if request.method == 'POST' and form.is_valid():
        ip = get_client_ip(request)
        try:
            StaffService.update_staff(
                staff=staff,
                data=form.cleaned_data,
                actor_user=request.user,
                ip_address=ip,
            )
            messages.success(request, f'Staff member {staff.user.name} updated.')
            return redirect('accounts:staff_list')
        except ValueError as e:
            form.add_error(None, str(e))

    return render(request, 'admin_dash/staff_form.html', {
        'form': form,
        'staff': staff,
        'title': f'Edit Staff: {staff.user.name}',
        'is_create': False,
    })


@login_required
@admin_required
def staff_toggle_active_view(request, pk):
    """Admin activates or suspends a staff member."""
    staff = get_object_or_404(Staff.objects.select_related('user'), pk=pk)
    if staff.user_id == request.user.id:
        messages.error(request, 'You cannot deactivate your own account.')
        return redirect('accounts:staff_list')

    ip = get_client_ip(request)
    new_state = StaffService.toggle_staff_status(staff, actor_user=request.user, ip_address=ip)
    label = 'activated' if new_state else 'suspended'
    messages.success(request, f'Staff member {staff.user.name} has been {label}.')
    return redirect('accounts:staff_list')


# ── System User Management (Admin Only) ───────────────────────────────────────

@login_required
@admin_required
def user_management_view(request):
    """
    Admin control center displaying all system users across all 3 roles:
    Admin, Staff, Customer with activation toggle and security audit logs.
    """
    search = request.GET.get('q', '').strip()
    role_filter = request.GET.get('role', '').strip()
    status_filter = request.GET.get('status', '').strip()

    users_qs = User.objects.all().order_by('-date_joined')

    if search:
        from django.db.models import Q
        users_qs = users_qs.filter(Q(first_name__icontains=search) | Q(last_name__icontains=search) | Q(email__icontains=search))

    if role_filter:
        users_qs = users_qs.filter(role=role_filter)
    if status_filter:
        is_active = (status_filter == 'active')
        users_qs = users_qs.filter(is_active=is_active)

    paginator = Paginator(users_qs, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    # Recent security audit events
    recent_audits = UserAuditLog.objects.select_related('user', 'actor').order_by('-timestamp')[:20]

    return render(request, 'admin_dash/user_management.html', {
        'users': page_obj,
        'search': search,
        'role_filter': role_filter,
        'status_filter': status_filter,
        'role_choices': User.ROLE_CHOICES,
        'total_count': users_qs.count(),
        'recent_audits': recent_audits,
    })


@login_required
@admin_required
def user_toggle_active_view(request, user_id):
    """Admin toggles active state of any user account."""
    target_user = get_object_or_404(User, pk=user_id)
    if target_user.pk == request.user.pk:
        messages.error(request, 'You cannot deactivate your own account.')
        return redirect('accounts:user_management')

    target_user.is_active = not target_user.is_active
    target_user.save(update_fields=['is_active'])

    # Sync linked customer or staff
    if hasattr(target_user, 'customer_profile'):
        target_user.customer_profile.status = 'Active' if target_user.is_active else 'Inactive'
        target_user.customer_profile.save(update_fields=['status'])
    if hasattr(target_user, 'staff_profile'):
        target_user.staff_profile.is_active = target_user.is_active
        target_user.staff_profile.save(update_fields=['is_active'])

    ip = get_client_ip(request)
    UserAuditLog.objects.create(
        user=target_user,
        actor=request.user,
        action='STATUS_TOGGLED',
        ip_address=ip,
        details=f'User {target_user.email} status toggled to {target_user.is_active} by admin {request.user.email}'
    )

    state_str = 'activated' if target_user.is_active else 'deactivated'
    messages.success(request, f'User {target_user.name} ({target_user.email}) has been {state_str}.')
    return redirect('accounts:user_management')


# ── Notifications ─────────────────────────────────────────────────────────────

@login_required
def notifications_view(request):
    """View recent system notifications and mark all as read."""
    from billing.models import Notification
    notifs = Notification.objects.filter(user=request.user).order_by('-created_at')[:50]
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return render(request, 'shared/notifications.html', {'notifications': notifs})


@login_required
def mark_notification_read(request, pk):
    """Async API endpoint to mark single notification as read."""
    from billing.models import Notification
    Notification.objects.filter(pk=pk, user=request.user).update(is_read=True)
    return JsonResponse({'status': 'ok'})
