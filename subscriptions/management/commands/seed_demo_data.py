from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import date, timedelta
from decimal import Decimal

from accounts.models import User, Customer
from catalog.models import Product, ProductVariant
from billing.models import Discount
from subscriptions.models import (
    Plan, Subscription, SubscriptionLine, SubscriptionHistory
)
from subscriptions.services import QuotationService, LifecycleService, PauseResumeService


class Command(BaseCommand):
    help = "Seeds comprehensive demo data matching the Brightloop Software scenario"

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Seeding Subscribify demo data..."))

        today = timezone.localdate() if timezone.is_aware(timezone.now()) else date.today()

        def get_or_create_cust(email, name, company_name, phone, billing_address, gst_number):
            user, _ = User.objects.get_or_create(
                email=email,
                defaults={
                    'first_name': name.split()[0] if name else '',
                    'last_name': ' '.join(name.split()[1:]) if len(name.split()) > 1 else '',
                    'role': User.Role.CUSTOMER,
                    'is_active': True,
                }
            )
            user.set_password('Customer@1234')
            user.save()
            cust, _ = Customer.objects.get_or_create(
                user=user,
                defaults={
                    'company_name': company_name,
                    'phone': phone,
                    'billing_address': billing_address,
                    'gst_number': gst_number,
                    'status': 'Active',
                }
            )
            return cust

        # 1. Customers
        c1 = get_or_create_cust(
            'billing@brightloop.io', 'Rajesh Sharma',
            'Brightloop Software Solutions Pvt Ltd',
            '+91 98765 43210',
            'Plot 42, Tech Park, Whitefield, Bangalore, Karnataka - 560066',
            '29AABCB1234F1Z5'
        )

        c2 = get_or_create_cust(
            'accounts@techcorp.in', 'Priya Iyer',
            'TechCorp Systems India',
            '+91 98220 11223',
            'Building 7, Cyber City, Gurugram, Haryana - 122002',
            '06AAACT5566G1ZV'
        )

        c3 = get_or_create_cust(
            'finance@cloudscale.co', 'Ananya Sen',
            'CloudScale Analytics Ltd',
            '+91 97110 99887',
            'Sector V, Salt Lake, Kolkata, West Bengal - 700091',
            '19AAACC9988H1ZS'
        )

        # 2. Products & Variants (Matching Module 2 scenario)
        p1, _ = Product.objects.get_or_create(
            name='Software A',
            defaults={
                'product_type': Product.ProductType.LICENSE,
                'base_sales_price': Decimal('2000.00'),
                'cost_price': Decimal('900.00'),
                'tax_rate': Decimal('18.00'),
                'hsn_sac_code': '997331',
                'description': 'Enterprise Business Management & ERP Suite',
                'is_active': True,
            }
        )

        v1_odoo, _ = ProductVariant.objects.get_or_create(
            product=p1,
            attribute_name='Edition',
            attribute_value='Odoo Enterprise',
            defaults={
                'additional_price': Decimal('560.00'),
                'sku': 'SOFT-A-ODOO-ENT',
                'is_active': True,
            }
        )

        v1_std, _ = ProductVariant.objects.get_or_create(
            product=p1,
            attribute_name='Edition',
            attribute_value='Standard Edition',
            defaults={
                'additional_price': Decimal('0.00'),
                'sku': 'SOFT-A-STD',
                'is_active': True,
            }
        )

        v1_cloud, _ = ProductVariant.objects.get_or_create(
            product=p1,
            attribute_name='Edition',
            attribute_value='Cloud Edition',
            defaults={
                'additional_price': Decimal('350.00'),
                'sku': 'SOFT-A-CLOUD',
                'is_active': True,
            }
        )

        p2, _ = Product.objects.get_or_create(
            name='ERP Implementation & Consulting',
            defaults={
                'product_type': Product.ProductType.SERVICE,
                'base_sales_price': Decimal('15000.00'),
                'cost_price': Decimal('6000.00'),
                'tax_rate': Decimal('18.00'),
                'hsn_sac_code': '998313',
                'description': 'Professional onboarding, business process mapping, and custom workflow engineering',
                'is_active': True,
            }
        )

        p3, _ = Product.objects.get_or_create(
            name='Secure Cloud Backup Storage',
            defaults={
                'product_type': Product.ProductType.SERVICE,
                'base_sales_price': Decimal('800.00'),
                'cost_price': Decimal('250.00'),
                'tax_rate': Decimal('18.00'),
                'hsn_sac_code': '998315',
                'description': 'Automated offsite backup storage with AES-256 encryption',
                'is_active': True,
            }
        )

        v3_500, _ = ProductVariant.objects.get_or_create(
            product=p3,
            attribute_name='Storage Tier',
            attribute_value='500GB Standard',
            defaults={
                'additional_price': Decimal('0.00'),
                'sku': 'BKP-500GB',
                'is_active': True,
            }
        )

        v3_2tb, _ = ProductVariant.objects.get_or_create(
            product=p3,
            attribute_name='Storage Tier',
            attribute_value='2TB Enterprise',
            defaults={
                'additional_price': Decimal('1200.00'),
                'sku': 'BKP-2TB',
                'is_active': True,
            }
        )

        # 3. Plans
        plan_odoo_m, _ = Plan.objects.get_or_create(
            plan_name='Software A - Odoo Enterprise Monthly',
            defaults={
                'product': p1,
                'variant': v1_odoo,
                'billing_cycle': Plan.BillingCycle.MONTHLY,
                'base_price': Decimal('2560.00'),
                'min_quantity': 1,
                'default_duration_months': 12,
                'auto_renew_default': True,
                'allow_pause': True,
                'max_pause_days': 30,
                'grace_period_days': 10,
                'is_active': True,
            }
        )

        plan_std_y, _ = Plan.objects.get_or_create(
            plan_name='Software A - Standard Edition Yearly',
            defaults={
                'product': p1,
                'variant': v1_std,
                'billing_cycle': Plan.BillingCycle.YEARLY,
                'base_price': Decimal('22000.00'),
                'min_quantity': 1,
                'default_duration_months': 1,
                'auto_renew_default': True,
                'allow_pause': True,
                'max_pause_days': 45,
                'grace_period_days': 15,
                'is_active': True,
            }
        )

        plan_erp_q, _ = Plan.objects.get_or_create(
            plan_name='ERP Support Retainer Quarterly',
            defaults={
                'product': p2,
                'variant': None,
                'billing_cycle': Plan.BillingCycle.QUARTERLY,
                'base_price': Decimal('42000.00'),
                'min_quantity': 1,
                'default_duration_months': 4,
                'auto_renew_default': True,
                'allow_pause': False,
                'max_pause_days': 0,
                'grace_period_days': 7,
                'is_active': True,
            }
        )

        # 4. Discounts
        d1, _ = Discount.objects.get_or_create(
            code='WELCOME10',
            defaults={
                'name': 'New Customer Onboarding 10% Off',
                'discount_type': Discount.DiscountType.PERCENTAGE,
                'discount_value': Decimal('10.00'),
                'min_purchase_amount': Decimal('1000.00'),
                'min_quantity': 1,
                'start_date': today - timedelta(days=30),
                'end_date': today + timedelta(days=180),
                'max_usage_limit': 100,
                'used_count': 0,
                'is_active': True,
            }
        )

        d2, _ = Discount.objects.get_or_create(
            code='FLAT500',
            defaults={
                'name': 'Flat ₹500 Discount on Annual Commitment',
                'discount_type': Discount.DiscountType.FIXED,
                'discount_value': Decimal('500.00'),
                'min_purchase_amount': Decimal('3000.00'),
                'min_quantity': 1,
                'start_date': today - timedelta(days=30),
                'end_date': today + timedelta(days=90),
                'max_usage_limit': 50,
                'used_count': 0,
                'is_active': True,
            }
        )

        # 5. Quotations & Subscriptions Lifecycle Demo

        # A: Draft Quotation for TechCorp
        if not Subscription.objects.filter(customer=c2, status=Subscription.Status.DRAFT).exists():
            QuotationService.create_quotation(
                customer=c2,
                plan=plan_odoo_m,
                lines_data=[
                    {'product_id': p1.product_id, 'variant_id': v1_odoo.variant_id, 'quantity': 5},
                    {'product_id': p3.product_id, 'variant_id': v3_2tb.variant_id, 'quantity': 1},
                ],
                validity_days=15,
                discount_code='WELCOME10',
                notes='Initial Q4 ERP license quotation with 5 seats and 2TB cloud backup.',
                user_name='Sales Team'
            )

        # B: Sent Quotation for CloudScale
        if not Subscription.objects.filter(customer=c3, status=Subscription.Status.QUOTATION).exists():
            sub_sent = QuotationService.create_quotation(
                customer=c3,
                plan=plan_std_y,
                lines_data=[
                    {'product_id': p1.product_id, 'variant_id': v1_std.variant_id, 'quantity': 10},
                ],
                validity_days=30,
                discount_code='FLAT500',
                notes='Annual enterprise standard plan quotation.',
                user_name='Sales Team'
            )
            QuotationService.send_quotation(sub_sent.pk, user_name='Sales Team')

        # C: Active Recurring Subscription for Brightloop (Confirmed & Activated)
        if not Subscription.objects.filter(customer=c1, status=Subscription.Status.ACTIVE).exists():
            sub_active = QuotationService.create_quotation(
                customer=c1,
                plan=plan_odoo_m,
                lines_data=[
                    {'product_id': p1.product_id, 'variant_id': v1_odoo.variant_id, 'quantity': 10},
                    {'product_id': p2.product_id, 'variant_id': None, 'quantity': 1},
                ],
                validity_days=15,
                notes='Production contract for Brightloop Software HQ.',
                user_name='Admin'
            )
            LifecycleService.confirm_quotation(sub_active.pk, start_date=today - timedelta(days=20), user_name='Admin')
            LifecycleService.activate_subscription(sub_active.pk, user_name='Billing System')

        # D: Paused Subscription for TechCorp (Demonstrates pause/resume logic)
        if not Subscription.objects.filter(customer=c2, status=Subscription.Status.PAUSED).exists():
            sub_pause = QuotationService.create_quotation(
                customer=c2,
                plan=plan_odoo_m,
                lines_data=[
                    {'product_id': p1.product_id, 'variant_id': v1_odoo.variant_id, 'quantity': 2},
                ],
                validity_days=15,
                notes='Branch office license contract - temporarily paused for holiday maintenance.',
                user_name='Admin'
            )
            LifecycleService.confirm_quotation(sub_pause.pk, start_date=today - timedelta(days=40), user_name='Admin')
            LifecycleService.activate_subscription(sub_pause.pk, user_name='Admin')
            PauseResumeService.pause_subscription(
                sub_pause.pk,
                pause_date=today - timedelta(days=5),
                reason='Holiday infrastructure maintenance',
                user_name='TechCorp Operations'
            )

        self.stdout.write(self.style.SUCCESS("Demo data seeded successfully!"))
