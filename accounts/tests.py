"""
accounts/tests.py
Comprehensive unit and integration test suite for Authentication,
RBAC authorization, IDOR protection, Brute-force lockout, and REST APIs.
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APITestCase
from rest_framework import status

from accounts.models import (
    User, Customer, Staff, PasswordResetToken,
    EmailVerificationToken, UserAuditLog
)
from accounts.services import AuthService, PasswordPolicyValidator, CustomerService, StaffService


class PasswordPolicyTests(TestCase):
    """Test password policy validator rules."""

    def test_valid_strong_password(self):
        errors = PasswordPolicyValidator.validate('SecureP@ssw0rd!')
        self.assertEqual(len(errors), 0)

    def test_short_password(self):
        errors = PasswordPolicyValidator.validate('Sh0rt!')
        self.assertTrue(any('at least 9 characters' in e for e in errors))

    def test_missing_uppercase(self):
        errors = PasswordPolicyValidator.validate('securep@ssw0rd!')
        self.assertTrue(any('uppercase letter' in e for e in errors))

    def test_missing_digit(self):
        errors = PasswordPolicyValidator.validate('SecureP@ssword!')
        self.assertTrue(any('number' in e for e in errors))

    def test_missing_special_char(self):
        errors = PasswordPolicyValidator.validate('SecurePassword123')
        self.assertTrue(any('special character' in e for e in errors))


class AuthenticationServiceTests(TestCase):
    """Test AuthService business logic for registration, login, lockout, and password recovery."""

    def setUp(self):
        self.client = Client()

    def test_customer_registration_success(self):
        user, customer, token = AuthService.register_customer(
            name='Alice Smith',
            email='alice@example.com',
            password='ComplexPassword123!',
            company_name='Acme Corp',
            phone='+91 99999 88888',
            gst_number='27AABCS1429B1Z0',
            ip_address='127.0.0.1'
        )
        self.assertEqual(user.email, 'alice@example.com')
        self.assertEqual(user.role, 'Customer')
        self.assertFalse(user.email_verified)
        self.assertEqual(customer.company_name, 'Acme Corp')
        self.assertTrue(token.is_valid())
        # Audit log verification
        self.assertTrue(UserAuditLog.objects.filter(user=user, action='REGISTER').exists())

    def test_customer_registration_duplicate_email(self):
        AuthService.register_customer(
            name='Alice', email='alice@example.com', password='ComplexPassword123!'
        )
        with self.assertRaises(ValueError):
            AuthService.register_customer(
                name='Alice Two', email='alice@example.com', password='ComplexPassword123!'
            )

    def test_login_brute_force_lockout(self):
        user, customer, _ = AuthService.register_customer(
            name='Bob', email='bob@example.com', password='CorrectPassword123!'
        )

        # 4 failed attempts - account should NOT be locked yet
        for i in range(4):
            u, err = AuthService.authenticate_user(None, 'bob@example.com', 'WrongPassword123!')
            self.assertIsNone(u)
            self.assertIn('attempts remaining', err)
            user.refresh_from_db()
            self.assertFalse(user.is_locked())

        # 5th failed attempt - account should now be locked
        u, err = AuthService.authenticate_user(None, 'bob@example.com', 'WrongPassword123!')
        self.assertIsNone(u)
        self.assertIn('locked for 15 minutes', err)
        user.refresh_from_db()
        self.assertTrue(user.is_locked())

        # Even with the CORRECT password, locked account must be rejected
        u, err = AuthService.authenticate_user(None, 'bob@example.com', 'CorrectPassword123!')
        self.assertIsNone(u)
        self.assertIn('temporarily locked', err)

    def test_login_success_resets_failures(self):
        user, _, _ = AuthService.register_customer(
            name='Charlie', email='charlie@example.com', password='GoodPassword123!'
        )
        # 2 failed attempts
        AuthService.authenticate_user(None, 'charlie@example.com', 'Wrong123!')
        AuthService.authenticate_user(None, 'charlie@example.com', 'Wrong123!')
        user.refresh_from_db()
        self.assertEqual(user.failed_login_attempts, 2)

        # Successful attempt
        u, err = AuthService.authenticate_user(None, 'charlie@example.com', 'GoodPassword123!')
        self.assertIsNotNone(u)
        self.assertIsNone(err)
        user.refresh_from_db()
        self.assertEqual(user.failed_login_attempts, 0)

    def test_email_verification_workflow(self):
        user, customer, token = AuthService.register_customer(
            name='Diana', email='diana@example.com', password='GoodPassword123!'
        )
        self.assertFalse(user.email_verified)

        # Redeem token
        success, msg = AuthService.verify_email(token.token)
        self.assertTrue(success)
        user.refresh_from_db()
        self.assertTrue(user.email_verified)

        # Token cannot be reused
        success, msg = AuthService.verify_email(token.token)
        self.assertFalse(success)

    def test_password_reset_workflow(self):
        user, _, _ = AuthService.register_customer(
            name='Eve', email='eve@example.com', password='OldPassword123!'
        )
        token = AuthService.request_password_reset('eve@example.com')
        self.assertIsNotNone(token)

        success, msg = AuthService.reset_password(token.token, 'NewPassword123!')
        self.assertTrue(success)

        # Verify old password fails and new password succeeds
        u_old, _ = AuthService.authenticate_user(None, 'eve@example.com', 'OldPassword123!')
        self.assertIsNone(u_old)
        u_new, _ = AuthService.authenticate_user(None, 'eve@example.com', 'NewPassword123!')
        self.assertIsNotNone(u_new)


class RoleBasedAuthorizationWebTests(TestCase):
    """Test RBAC web access control on views."""

    def setUp(self):
        self.client = Client()
        # Admin user
        self.admin_user = User.objects.create_user(
            email='admin@test.com', password='AdminPassword123!', name='Admin User',
            role='Admin', is_staff=True
        )
        Staff.objects.create(user=self.admin_user, employee_code='ADM-001', department='IT')

        # Staff user
        self.staff_user = User.objects.create_user(
            email='staff@test.com', password='StaffPassword123!', name='Staff User',
            role='Staff', is_staff=True
        )
        Staff.objects.create(user=self.staff_user, employee_code='STF-001', department='Billing')

        # Customer A
        self.customer_user_a, self.customer_a, _ = AuthService.register_customer(
            name='Customer A', email='customer_a@test.com', password='CustPassword123!',
            company_name='Alpha Ltd'
        )

        # Customer B
        self.customer_user_b, self.customer_b, _ = AuthService.register_customer(
            name='Customer B', email='customer_b@test.com', password='CustPassword123!',
            company_name='Beta Ltd'
        )

    def test_admin_can_access_staff_and_user_management(self):
        self.client.force_login(self.admin_user)
        # Staff list
        resp = self.client.get(reverse('accounts:staff_list'))
        self.assertEqual(resp.status_code, 200)
        # User management
        resp2 = self.client.get(reverse('accounts:user_management'))
        self.assertEqual(resp2.status_code, 200)

    def test_staff_cannot_access_staff_or_user_management(self):
        self.client.force_login(self.staff_user)
        # Staff list (Admin only)
        resp = self.client.get(reverse('accounts:staff_list'))
        self.assertEqual(resp.status_code, 302)
        # User directory (Admin only)
        resp2 = self.client.get(reverse('accounts:user_management'))
        self.assertEqual(resp2.status_code, 302)

    def test_staff_can_access_customer_directory(self):
        self.client.force_login(self.staff_user)
        resp = self.client.get(reverse('accounts:customer_list'))
        self.assertEqual(resp.status_code, 200)

    def test_customer_cannot_access_customer_directory(self):
        self.client.force_login(self.customer_user_a)
        resp = self.client.get(reverse('accounts:customer_list'))
        self.assertEqual(resp.status_code, 302)

    def test_customer_idor_prevention(self):
        """Customer A cannot view Customer B's detail page."""
        self.client.force_login(self.customer_user_a)
        # Attempt to access Customer B
        resp = self.client.get(reverse('accounts:customer_detail', kwargs={'pk': self.customer_b.pk}))
        # Redirected due to IDOR prevention
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('dashboard:customer'), resp.url)

        # Customer A CAN view Customer A's own detail page
        resp_own = self.client.get(reverse('accounts:customer_detail', kwargs={'pk': self.customer_a.pk}))
        self.assertEqual(resp_own.status_code, 200)

    def test_staff_and_admin_can_view_any_customer_detail(self):
        self.client.force_login(self.staff_user)
        resp_a = self.client.get(reverse('accounts:customer_detail', kwargs={'pk': self.customer_a.pk}))
        self.assertEqual(resp_a.status_code, 200)
        resp_b = self.client.get(reverse('accounts:customer_detail', kwargs={'pk': self.customer_b.pk}))
        self.assertEqual(resp_b.status_code, 200)


class AccountsAPITests(APITestCase):
    """Test Django REST Framework accounts endpoints."""

    def setUp(self):
        # Admin
        self.admin = User.objects.create_user(
            email='api_admin@test.com', password='AdminPassword123!',
            name='API Admin', role='Admin', is_staff=True
        )
        # Staff
        self.staff = User.objects.create_user(
            email='api_staff@test.com', password='StaffPassword123!',
            name='API Staff', role='Staff', is_staff=True
        )
        # Customer A
        self.user_a, self.customer_a, _ = AuthService.register_customer(
            name='API Customer A', email='api_cust_a@test.com', password='CustPassword123!'
        )
        # Customer B
        self.user_b, self.customer_b, _ = AuthService.register_customer(
            name='API Customer B', email='api_cust_b@test.com', password='CustPassword123!'
        )

    def test_api_registration(self):
        url = reverse('accounts:api:api_register')
        payload = {
            'name': 'API Tester',
            'email': 'api_tester@test.com',
            'password': 'StrongPassword123!',
            'confirm_password': 'StrongPassword123!',
            'company_name': 'Test Tech',
        }
        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(resp.data['success'])
        self.assertEqual(resp.data['data']['company_name'], 'Test Tech')

    def test_api_login_success(self):
        url = reverse('accounts:api:api_login')
        payload = {'email': 'api_cust_a@test.com', 'password': 'CustPassword123!'}
        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data['success'])
        self.assertEqual(resp.data['data']['email'], 'api_cust_a@test.com')

    def test_api_login_bad_credentials(self):
        url = reverse('accounts:api:api_login')
        payload = {'email': 'api_cust_a@test.com', 'password': 'WrongPassword123!'}
        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(resp.data['success'])

    def test_api_customer_list_authorization(self):
        url = reverse('accounts:api:api_customer_list_create')

        # Customer forbidden
        self.client.force_authenticate(user=self.user_a)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        # Staff authorized
        self.client.force_authenticate(user=self.staff)
        resp2 = self.client.get(url)
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)
        self.assertTrue(resp2.data['success'])

    def test_api_customer_detail_idor_prevention(self):
        """Customer A cannot read Customer B through REST API."""
        url_b = reverse('accounts:api:api_customer_detail', kwargs={'pk': self.customer_b.pk})

        self.client.force_authenticate(user=self.user_a)
        resp = self.client.get(url_b)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        # Customer A CAN read own record
        url_a = reverse('accounts:api:api_customer_detail', kwargs={'pk': self.customer_a.pk})
        resp_own = self.client.get(url_a)
        self.assertEqual(resp_own.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_own.data['data']['id'], self.customer_a.id)

    def test_api_staff_list_admin_only(self):
        url = reverse('accounts:api:api_staff_list_create')

        # Staff user is forbidden
        self.client.force_authenticate(user=self.staff)
        resp_staff = self.client.get(url)
        self.assertEqual(resp_staff.status_code, status.HTTP_403_FORBIDDEN)

        # Admin user is permitted
        self.client.force_authenticate(user=self.admin)
        resp_admin = self.client.get(url)
        self.assertEqual(resp_admin.status_code, status.HTTP_200_OK)
