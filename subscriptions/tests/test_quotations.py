from django.test import TestCase
from decimal import Decimal
from subscriptions.models import Customer, Product, ProductVariant, Plan, Discount, Subscription
from subscriptions.services import QuotationService


class QuotationTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            name='Rajesh Sharma',
            company_name='Brightloop Software',
            email='rajesh@brightloop.io',
            billing_address='Bangalore, India'
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
            sku='SOFT-A-ODOO'
        )

        self.plan = Plan.objects.create(
            plan_name='Odoo Monthly Plan',
            product=self.product,
            variant=self.variant,
            billing_cycle=Plan.BillingCycle.MONTHLY,
            base_price=Decimal('2560.00'),
            min_quantity=1
        )

        self.discount = Discount.objects.create(
            code='SAVE10',
            name='10% Off',
            discount_type=Discount.DiscountType.PERCENTAGE,
            discount_value=Decimal('10.00'),
            min_purchase_amount=Decimal('1000.00'),
            is_active=True
        )

    def test_calculate_quotation_totals(self):
        lines_data = [
            {'product_id': self.product.product_id, 'variant_id': self.variant.variant_id, 'quantity': 2}
        ]
        res = QuotationService.calculate_quotation_totals(lines_data, discount_code='SAVE10')
        
        # Subtotal: 2 * 2560 = 5120.00
        self.assertEqual(res['subtotal'], Decimal('5120.00'))
        # Discount: 10% of 5120 = 512.00
        self.assertEqual(res['discount_amount'], Decimal('512.00'))
        # Tax: 18% of 5120 = 921.60
        self.assertEqual(res['total_tax'], Decimal('921.60'))
        # Grand total: (5120 - 512) + 921.60 = 4608 + 921.60 = 5529.60
        self.assertEqual(res['grand_total'], Decimal('5529.60'))

    def test_create_and_send_quotation(self):
        lines_data = [
            {'product_id': self.product.product_id, 'variant_id': self.variant.variant_id, 'quantity': 2}
        ]
        sub = QuotationService.create_quotation(
            customer=self.customer,
            plan=self.plan,
            lines_data=lines_data,
            validity_days=15,
            discount_code='SAVE10',
            notes='Test quotation'
        )

        self.assertTrue(sub.subscription_number.startswith('QUO-'))
        self.assertEqual(sub.status, Subscription.Status.DRAFT)
        self.assertEqual(sub.lines.count(), 1)
        self.assertEqual(sub.total_amount, Decimal('5529.60'))

        # Send quotation
        sent_sub = QuotationService.send_quotation(sub.pk, user_name='Staff')
        self.assertEqual(sent_sub.status, Subscription.Status.QUOTATION)
        self.assertEqual(sent_sub.history.count(), 2)

    def test_min_quantity_validation(self):
        self.plan.min_quantity = 5
        self.plan.save()

        lines_data = [
            {'product_id': self.product.product_id, 'variant_id': self.variant.variant_id, 'quantity': 2}
        ]
        with self.assertRaises(ValueError):
            QuotationService.create_quotation(
                customer=self.customer,
                plan=self.plan,
                lines_data=lines_data
            )
