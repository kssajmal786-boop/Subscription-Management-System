"""
accounts/permissions.py
Django REST Framework permission classes for role-based authorization and IDOR protection.
"""
from rest_framework import permissions


class IsAdminRole(permissions.BasePermission):
    """Allows access only to Admin users."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == 'Admin')


class IsStaffOrAdminRole(permissions.BasePermission):
    """Allows access to Staff and Admin users."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role in ('Admin', 'Staff'))


class IsCustomerRole(permissions.BasePermission):
    """Allows access only to Customer users."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == 'Customer')


class IsSelfOrStaffAdmin(permissions.BasePermission):
    """
    Object-level permission to prevent IDOR on customer and user resources.
    Allows staff/admins full access, while customers can only access their own profile.
    """
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False

        # Staff and Admins have system-wide access
        if request.user.role in ('Admin', 'Staff'):
            return True

        # Check if obj is a User instance
        if hasattr(obj, 'email') and hasattr(obj, 'role'):
            return obj.pk == request.user.pk

        # Check if obj is a Customer instance
        if hasattr(obj, 'user'):
            return obj.user_id == request.user.pk

        return False


class IsEmailVerified(permissions.BasePermission):
    """Ensure customer has completed email verification."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        # Only enforce on customers
        if request.user.role == 'Customer':
            return request.user.email_verified
        return True
