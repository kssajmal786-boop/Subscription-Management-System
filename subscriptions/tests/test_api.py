from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from decimal import Decimal
from datetime import date, timedelta
from subscriptions.models import Customer, Product, ProductVariant, Plan, Subscription


class ApiEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.customer = Customer.objects.create(
            name='API User',
            company_name='CloudScale Analytics',
            email='api@cloudscale.io',
            billing_address='Bangalore'
        )

        self.product = Product.objects.create(
            name='Software A',
            product_type=Product.ProductType.LICENSE,
            base_sales_price=Decimal('2000.00'),
            tax_rate=Decimal('18.00')
        )

        self.variant = ProductVariant.objects.create(
            product=self.product,
            attribute_name='Edition',
            attribute_value='Odoo Enterprise',
            additional_price=Decimal('560.00'),
            sku='API-SOFT-ODOO'
        )

        self.plan = Plan.objects.create(
            plan_name='Odoo Plan',
            product=self.product,
            variant=self.variant,
            billing_cycle=Plan.BillingCycle.MONTHLY,
            base_price=Decimal('2560.00'),
            min_quantity=1
        )

    def test_products_api(self):
        # List products
        response = self.client.get('/api/v1/products/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)

        # Archive product
        archive_resp = self.client.post(f'/api/v1/products/{self.product.product_id}/archive/')
        self.assertEqual(archive_resp.status_code, status.HTTP_200_OK)
        self.assertFalse(archive_resp.data['is_active'])

    def test_calculate_quotation_api(self):
        payload = {
            'lines': [
                {'product_id': self.product.product_id, 'variant_id': self.variant.variant_id, 'quantity': 2}
            ]
        }
        response = self.client.post('/api/v1/subscriptions/calculate/', payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['subtotal'], '5120.00')
        self.assertEqual(response.data['total_tax'], '921.60')
        self.assertEqual(response.data['grand_total'], '6041.60')

    def test_quotation_and_subscription_api_flow(self):
        # 1. Create draft quotation
        payload = {
            'customer_id': self.customer.customer_id,
            'plan_id': self.plan.plan_id,
            'lines': [
                {'product_id': self.product.product_id, 'variant_id': self.variant.variant_id, 'quantity': 1}
            ],
            'validity_days': 20,
            'notes': 'Created via REST API'
        }
        create_resp = self.client.post('/api/v1/subscriptions/', payload, format='json')
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)
        sub_id = create_resp.data['subscription_id']
        self.assertEqual(create_resp.data['status'], 'Draft')

        # 2. Send quotation
        send_resp = self.client.post(f'/api/v1/subscriptions/{sub_id}/send/')
        self.assertEqual(send_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(send_resp.data['status'], 'Quotation')

        # 3. Confirm quotation
        confirm_resp = self.client.post(f'/api/v1/subscriptions/{sub_id}/confirm/')
        self.assertEqual(confirm_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(confirm_resp.data['status'], 'Confirmed')
        self.assertTrue(confirm_resp.data['subscription_number'].startswith('SUB-'))

        # 4. Activate subscription
        activate_resp = self.client.post(f'/api/v1/subscriptions/{sub_id}/activate/')
        self.assertEqual(activate_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(activate_resp.data['status'], 'Active')

        # 5. Pause subscription
        pause_resp = self.client.post(f'/api/v1/subscriptions/{sub_id}/pause/', {'reason': 'API pause'}, format='json')
        self.assertEqual(pause_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(pause_resp.data['status'], 'Paused')

        # 6. Resume subscription
        resume_resp = self.client.post(f'/api/v1/subscriptions/{sub_id}/resume/', format='json')
        self.assertEqual(resume_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resume_resp.data['status'], 'Active')

    def test_due_billing_endpoint(self):
        # Create active subscription with next_billing_date = today
        sub = Subscription.objects.create(
            subscription_number='SUB-DUE-001',
            customer=self.customer,
            plan=self.plan,
            status=Subscription.Status.ACTIVE,
            next_billing_date=date.today()
        )
        response = self.client.get('/api/v1/subscriptions/due-billing/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        found_ids = [s['subscription_id'] for s in response.data]
        self.assertIn(sub.subscription_id, found_ids)
