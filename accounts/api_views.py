"""
accounts/api_views.py
Django REST Framework API views with uniform JSON responses, strict RBAC,
and Anti-IDOR object-level authorization.
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.shortcuts import get_object_or_404

from accounts.models import User, Customer, Staff, UserAuditLog
from accounts.serializers import (
    UserSerializer, CustomerSerializer, CustomerRegistrationSerializer,
    CustomerCreateUpdateSerializer, StaffSerializer, StaffCreateSerializer,
    StaffUpdateSerializer, LoginSerializer, PasswordResetRequestSerializer,
    PasswordResetConfirmSerializer, ChangePasswordSerializer,
    UserAuditLogSerializer
)
from accounts.services import AuthService, CustomerService, StaffService
from accounts.permissions import (
    IsAdminRole, IsStaffOrAdminRole, IsCustomerRole, IsSelfOrStaffAdmin
)
from accounts.views import get_client_ip


def api_response(success=True, message='', data=None, status_code=status.HTTP_200_OK):
    """Uniform REST JSON envelope."""
    payload = {
        'success': success,
        'message': message,
        'data': data if data is not None else {},
    }
    return Response(payload, status=status_code)


class RegisterAPIView(APIView):
    """Customer self-registration endpoint."""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = CustomerRegistrationSerializer(data=request.data)
        if not serializer.is_valid():
            return api_response(
                success=False,
                message='Validation failed.',
                data=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST
            )
        ip = get_client_ip(request)
        try:
            user, customer, token = AuthService.register_customer(
                name=serializer.validated_data['name'],
                email=serializer.validated_data['email'],
                password=serializer.validated_data['password'],
                company_name=serializer.validated_data.get('company_name', ''),
                phone=serializer.validated_data.get('phone', ''),
                gst_number=serializer.validated_data.get('gst_number', ''),
                billing_address=serializer.validated_data.get('billing_address', ''),
                city=serializer.validated_data.get('city', ''),
                state=serializer.validated_data.get('state', ''),
                pincode=serializer.validated_data.get('pincode', ''),
                ip_address=ip,
            )
            data = CustomerSerializer(customer).data
            data['verification_token'] = token.token
            return api_response(
                success=True,
                message='Account registered successfully. Verification email dispatched.',
                data=data,
                status_code=status.HTTP_201_CREATED
            )
        except ValueError as e:
            return api_response(success=False, message=str(e), status_code=status.HTTP_400_BAD_REQUEST)


class LoginAPIView(APIView):
    """Session-based authentication with brute-force lockout protection."""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            return api_response(
                success=False,
                message='Invalid login payload.',
                data=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST
            )
        email = serializer.validated_data['email']
        password = serializer.validated_data['password']
        ip = get_client_ip(request)

        user, err = AuthService.authenticate_user(request, email, password, ip_address=ip)
        if not user:
            return api_response(
                success=False,
                message=err,
                status_code=status.HTTP_401_UNAUTHORIZED
            )

        auth_login(request, user)
        if serializer.validated_data.get('remember_me'):
            request.session.set_expiry(60 * 60 * 24 * 30)

        data = UserSerializer(user).data
        if hasattr(user, 'customer_profile'):
            data['customer_id'] = user.customer_profile.id
        elif hasattr(user, 'staff_profile'):
            data['staff_id'] = user.staff_profile.id

        return api_response(
            success=True,
            message=f'Welcome back, {user.name}!',
            data=data
        )


class LogoutAPIView(APIView):
    """Terminates active session."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        ip = get_client_ip(request)
        UserAuditLog.objects.create(
            user=request.user,
            actor=request.user,
            action='LOGOUT',
            ip_address=ip,
            details=f'API sign-out by {request.user.email}'
        )
        auth_logout(request)
        return api_response(success=True, message='Successfully signed out.')


class MeAPIView(APIView):
    """Returns currently authenticated user profile and allows updates."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        data = UserSerializer(request.user).data
        if hasattr(request.user, 'customer_profile'):
            data['customer'] = CustomerSerializer(request.user.customer_profile).data
        elif hasattr(request.user, 'staff_profile'):
            data['staff'] = StaffSerializer(request.user.staff_profile).data
        return api_response(success=True, data=data)

    def put(self, request):
        user = request.user
        name = request.data.get('name')
        if name:
            user.name = name.strip()
            user.save(update_fields=['name'])

        if hasattr(user, 'customer_profile'):
            CustomerService.update_customer_profile(
                customer=user.customer_profile,
                data=request.data,
                actor_user=user,
                ip_address=get_client_ip(request)
            )

        return self.get(request)


class ForgotPasswordAPIView(APIView):
    """Requests password reset token."""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return api_response(success=False, message='Invalid email.', data=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)

        ip = get_client_ip(request)
        AuthService.request_password_reset(serializer.validated_data['email'], ip_address=ip)
        return api_response(success=True, message='If your email exists in our records, reset instructions have been sent.')


class ResetPasswordAPIView(APIView):
    """Redeems password reset token."""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        if not serializer.is_valid():
            return api_response(success=False, message='Validation failed.', data=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)

        ip = get_client_ip(request)
        success, msg = AuthService.reset_password(
            token_str=serializer.validated_data['token'],
            new_password=serializer.validated_data['new_password'],
            ip_address=ip
        )
        if not success:
            return api_response(success=False, message=msg, status_code=status.HTTP_400_BAD_REQUEST)
        return api_response(success=True, message=msg)


class VerifyEmailAPIView(APIView):
    """Validates email verification token."""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        token = request.data.get('token')
        if not token:
            return api_response(success=False, message='Token is required.', status_code=status.HTTP_400_BAD_REQUEST)
        ip = get_client_ip(request)
        success, msg = AuthService.verify_email(token, ip_address=ip)
        if not success:
            return api_response(success=False, message=msg, status_code=status.HTTP_400_BAD_REQUEST)
        return api_response(success=True, message=msg)


class ChangePasswordAPIView(APIView):
    """Changes password for authenticated session."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return api_response(success=False, message='Validation failed.', data=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)

        cur = serializer.validated_data['current_password']
        if not request.user.check_password(cur):
            return api_response(success=False, message='Current password is incorrect.', status_code=status.HTTP_400_BAD_REQUEST)

        request.user.set_password(serializer.validated_data['new_password'])
        request.user.save()
        ip = get_client_ip(request)
        UserAuditLog.objects.create(
            user=request.user,
            actor=request.user,
            action='PASSWORD_RESET_DONE',
            ip_address=ip,
            details='Password changed via API.'
        )
        return api_response(success=True, message='Password successfully updated.')


# ── Customer Management APIs ──────────────────────────────────────────────────

class CustomerListCreateAPIView(APIView):
    """List or create customers (Staff & Admin only)."""
    permission_classes = [IsStaffOrAdminRole]

    def get(self, request):
        query = request.GET.get('q', '')
        cust_status = request.GET.get('status', '')
        customers = CustomerService.search_and_filter(query=query, status=cust_status)
        serializer = CustomerSerializer(customers, many=True)
        return api_response(success=True, data={'count': customers.count(), 'results': serializer.data})

    def post(self, request):
        serializer = CustomerCreateUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return api_response(success=False, message='Validation failed.', data=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)

        ip = get_client_ip(request)
        try:
            customer = CustomerService.create_customer_by_staff(
                data=serializer.validated_data,
                creator_user=request.user,
                ip_address=ip
            )
            return api_response(
                success=True,
                message='Customer created successfully.',
                data=CustomerSerializer(customer).data,
                status_code=status.HTTP_201_CREATED
            )
        except ValueError as e:
            return api_response(success=False, message=str(e), status_code=status.HTTP_400_BAD_REQUEST)


class CustomerDetailAPIView(APIView):
    """
    Customer detail endpoint.
    Protected with IsSelfOrStaffAdmin to prevent horizontal IDOR privilege escalation!
    """
    permission_classes = [IsSelfOrStaffAdmin]

    def get_object(self, pk):
        customer = get_object_or_404(Customer.objects.select_related('user'), pk=pk)
        self.check_object_permissions(self.request, customer)
        return customer

    def get(self, request, pk):
        customer = self.get_object(pk)
        return api_response(success=True, data=CustomerSerializer(customer).data)

    def put(self, request, pk):
        customer = self.get_object(pk)
        ip = get_client_ip(request)
        try:
            updated = CustomerService.update_customer_profile(
                customer=customer,
                data=request.data,
                actor_user=request.user,
                ip_address=ip
            )
            return api_response(success=True, message='Customer updated.', data=CustomerSerializer(updated).data)
        except ValueError as e:
            return api_response(success=False, message=str(e), status_code=status.HTTP_400_BAD_REQUEST)

    def patch(self, request, pk):
        return self.put(request, pk)


class CustomerToggleActiveAPIView(APIView):
    """Staff/Admin toggles customer active status."""
    permission_classes = [IsStaffOrAdminRole]

    def post(self, request, pk):
        customer = get_object_or_404(Customer.objects.select_related('user'), pk=pk)
        ip = get_client_ip(request)
        new_active = CustomerService.toggle_customer_status(customer, actor_user=request.user, ip_address=ip)
        return api_response(
            success=True,
            message=f'Customer {"activated" if new_active else "suspended"}.',
            data={'is_active': new_active, 'status': customer.status}
        )


# ── Staff Management APIs (Admin Only) ────────────────────────────────────────

class StaffListCreateAPIView(APIView):
    """List or provision staff members (Admin only)."""
    permission_classes = [IsAdminRole]

    def get(self, request):
        staff_qs = Staff.objects.select_related('user').order_by('-created_at')
        serializer = StaffSerializer(staff_qs, many=True)
        return api_response(success=True, data={'count': staff_qs.count(), 'results': serializer.data})

    def post(self, request):
        serializer = StaffCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return api_response(success=False, message='Validation failed.', data=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)

        ip = get_client_ip(request)
        try:
            staff = StaffService.create_staff(
                email=serializer.validated_data['email'],
                password=serializer.validated_data['password'],
                name=serializer.validated_data['name'],
                role=serializer.validated_data.get('role', 'Staff'),
                employee_code=serializer.validated_data['employee_code'],
                department=serializer.validated_data.get('department', ''),
                designation=serializer.validated_data.get('designation', ''),
                creator_user=request.user,
                ip_address=ip,
            )
            return api_response(
                success=True,
                message='Staff member created.',
                data=StaffSerializer(staff).data,
                status_code=status.HTTP_201_CREATED
            )
        except ValueError as e:
            return api_response(success=False, message=str(e), status_code=status.HTTP_400_BAD_REQUEST)


class StaffDetailAPIView(APIView):
    """Retrieve or update staff record (Admin only)."""
    permission_classes = [IsAdminRole]

    def get_object(self, pk):
        return get_object_or_404(Staff.objects.select_related('user'), pk=pk)

    def get(self, request, pk):
        staff = self.get_object(pk)
        return api_response(success=True, data=StaffSerializer(staff).data)

    def put(self, request, pk):
        staff = self.get_object(pk)
        serializer = StaffUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return api_response(success=False, message='Validation failed.', data=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)

        ip = get_client_ip(request)
        try:
            updated = StaffService.update_staff(
                staff=staff,
                data=serializer.validated_data,
                actor_user=request.user,
                ip_address=ip
            )
            return api_response(success=True, message='Staff member updated.', data=StaffSerializer(updated).data)
        except ValueError as e:
            return api_response(success=False, message=str(e), status_code=status.HTTP_400_BAD_REQUEST)


class StaffToggleActiveAPIView(APIView):
    """Admin toggles staff active status."""
    permission_classes = [IsAdminRole]

    def post(self, request, pk):
        staff = get_object_or_404(Staff.objects.select_related('user'), pk=pk)
        if staff.user_id == request.user.id:
            return api_response(success=False, message='Cannot deactivate your own account.', status_code=status.HTTP_400_BAD_REQUEST)

        ip = get_client_ip(request)
        new_active = StaffService.toggle_staff_status(staff, actor_user=request.user, ip_address=ip)
        return api_response(
            success=True,
            message=f'Staff member {"activated" if new_active else "suspended"}.',
            data={'is_active': new_active}
        )


# ── System User Management APIs (Admin Only) ──────────────────────────────────

class UserListAPIView(APIView):
    """Admin view of all users across all roles."""
    permission_classes = [IsAdminRole]

    def get(self, request):
        role = request.GET.get('role')
        search = request.GET.get('q')
        users = User.objects.all().order_by('-created_at')
        if role:
            users = users.filter(role=role)
        if search:
            from django.db.models import Q
            users = users.filter(Q(name__icontains=search) | Q(email__icontains=search))

        serializer = UserSerializer(users, many=True)
        return api_response(success=True, data={'count': users.count(), 'results': serializer.data})


class UserToggleActiveAPIView(APIView):
    """Admin toggles active flag on any user."""
    permission_classes = [IsAdminRole]

    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        if user.pk == request.user.pk:
            return api_response(success=False, message='Cannot deactivate your own account.', status_code=status.HTTP_400_BAD_REQUEST)

        user.is_active = not user.is_active
        user.save(update_fields=['is_active'])

        if hasattr(user, 'customer_profile'):
            user.customer_profile.status = 'Active' if user.is_active else 'Inactive'
            user.customer_profile.save(update_fields=['status'])
        if hasattr(user, 'staff_profile'):
            user.staff_profile.is_active = user.is_active
            user.staff_profile.save(update_fields=['is_active'])

        ip = get_client_ip(request)
        UserAuditLog.objects.create(
            user=user,
            actor=request.user,
            action='STATUS_TOGGLED',
            ip_address=ip,
            details=f'User active status toggled to {user.is_active} via API by admin {request.user.email}'
        )

        return api_response(
            success=True,
            message=f'User {"activated" if user.is_active else "deactivated"}.',
            data={'is_active': user.is_active}
        )


class AuditLogListAPIView(APIView):
    """Security audit logs (Admin only)."""
    permission_classes = [IsAdminRole]

    def get(self, request):
        action = request.GET.get('action')
        logs = UserAuditLog.objects.select_related('user', 'actor').order_by('-timestamp')
        if action:
            logs = logs.filter(action=action)
        logs = logs[:100]
        serializer = UserAuditLogSerializer(logs, many=True)
        return api_response(success=True, data={'count': len(logs), 'results': serializer.data})
