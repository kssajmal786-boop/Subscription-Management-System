"""
accounts/management/commands/seed_data.py
=========================================
Populate Subscribify with realistic seed data:
  - Users: Admin, Staff, Customer
  - Products with Variants
  - Subscription Plans
  - Discount Coupons
  - Active Subscriptions, Invoices, and Payments
  - Monthly Revenue Snapshots
"""
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.utils import timezone
from dateutil.relativedelta import relativedelta
from accounts.models import User, Customer, StaffProfile
from catalog.models import Product, ProductVariant
from subscriptions.models import Plan, Subscription, SubscriptionLine
from billing.models import Discount, Invoice, InvoiceLine, Payment, MonthlyRevenueSnapshot
from billing.services import BillingService


class Command(BaseCommand):
    help = "Seeds database with demo users, catalog products, plans, subscriptions, and billing data."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Seeding Subscribify database..."))

        # 1. Create Users
        admin_user, _ = User.objects.get_or_create(
            email="admin@subscribify.com",
            defaults={
                "first_name": "Antigravity",
                "last_name": "Administrator",
                "role": User.Role.ADMIN,
                "is_staff": True,
                "is_superuser": True,
            }
        )
        admin_user.set_password("Admin@1234")
        admin_user.save()

        staff_user, _ = User.objects.get_or_create(
            email="staff@subscribify.com",
            defaults={
                "first_name": "Operations",
                "last_name": "Officer",
                "role": User.Role.STAFF,
                "is_staff": True,
            }
        )
        staff_user.set_password("Staff@1234")
        staff_user.save()
        StaffProfile.objects.get_or_create(
            user=staff_user,
            defaults={"employee_code": "EMP00101", "department": "Billing Operations", "designation": "Billing Analyst"}
        )

        customer_user, _ = User.objects.get_or_create(
            email="customer@brightloop.in",
            defaults={
                "first_name": "Rohan",
                "last_name": "Sharma",
                "role": User.Role.CUSTOMER,
            }
        )
        customer_user.set_password("Customer@1234")
        customer_user.save()

        customer, _ = Customer.objects.get_or_create(
            user=customer_user,
            defaults={
                "company_name": "Acme Tech Solutions Pvt Ltd",
                "gst_number": "29ABCDE1234F1Z5",
                "state": "Karnataka",
                "city": "Bengaluru",
                "pincode": "560025",
                "phone": "+91-9876543210",
                "billing_address": "42 Residency Road, Bengaluru, Karnataka 560025",
            }
        )

        # 2. Products & Variants
        cloud_suite, _ = Product.objects.get_or_create(
            name="Brightloop Cloud ERP Suite",
            defaults={
                "product_type": Product.ProductType.LICENSE,
                "base_sales_price": Decimal("2500.00"),
                "cost_price": Decimal("600.00"),
                "tax_rate": Decimal("18.00"),
                "hsn_sac_code": "998314",
                "description": "Full-featured SaaS platform with ERP, CRM, and accounting.",
            }
        )
        v_std, _ = ProductVariant.objects.get_or_create(
            product=cloud_suite,
            attribute_name="Edition",
            attribute_value="Standard",
            defaults={"additional_price": Decimal("0.00"), "sku": "ERP-STD"}
        )
        v_ent, _ = ProductVariant.objects.get_or_create(
            product=cloud_suite,
            attribute_name="Edition",
            attribute_value="Enterprise",
            defaults={"additional_price": Decimal("1500.00"), "sku": "ERP-ENT"}
        )

        server_prod, _ = Product.objects.get_or_create(
            name="Dedicated High-Availability Node",
            defaults={
                "product_type": Product.ProductType.SERVICE,
                "base_sales_price": Decimal("5000.00"),
                "cost_price": Decimal("1800.00"),
                "tax_rate": Decimal("18.00"),
                "hsn_sac_code": "998315",
                "description": "Enterprise cloud host node with 99.99% SLA guarantee.",
            }
        )

        # 3. Plans
        monthly_plan, _ = Plan.objects.get_or_create(
            plan_name="Cloud ERP – Monthly Standard",
            defaults={
                "product": cloud_suite,
                "variant": v_std,
                "billing_cycle": Plan.BillingCycle.MONTHLY,
                "base_price": Decimal("2500.00"),
                "min_quantity": 1,
                "default_duration_months": 12,
                "auto_renew_default": True,
                "allow_pause": True,
                "max_pause_days": 30,
                "grace_period_days": 7,
            }
        )

        yearly_ent_plan, _ = Plan.objects.get_or_create(
            plan_name="Cloud ERP – Annual Enterprise",
            defaults={
                "product": cloud_suite,
                "variant": v_ent,
                "billing_cycle": Plan.BillingCycle.YEARLY,
                "base_price": Decimal("40000.00"),
                "min_quantity": 1,
                "default_duration_months": 12,
                "auto_renew_default": True,
                "allow_pause": False,
                "grace_period_days": 15,
            }
        )

        # 4. Discounts
        d_welcome, _ = Discount.objects.get_or_create(
            code="WELCOME20",
            defaults={
                "name": "New Customer 20% Off",
                "discount_type": Discount.DiscountType.PERCENTAGE,
                "discount_value": Decimal("20.00"),
                "max_discount_cap": Decimal("1000.00"),
                "min_purchase_amount": Decimal("1000.00"),
                "start_date": timezone.now().date() - relativedelta(months=1),
                "end_date": timezone.now().date() + relativedelta(months=6),
                "is_active": True,
            }
        )

        # 5. Active Subscription
        today = timezone.now().date()
        sub, created = Subscription.objects.get_or_create(
            subscription_number="SUB-2026-00001",
            defaults={
                "customer": customer,
                "plan": monthly_plan,
                "status": Subscription.Status.ACTIVE,
                "start_date": today - relativedelta(months=2),
                "next_billing_date": today + relativedelta(days=10),
                "expiry_date": today + relativedelta(months=10),
                "auto_renew": True,
                "applied_discount": d_welcome,
                "created_by": admin_user,
            }
        )
        if created:
            SubscriptionLine.objects.create(
                subscription=sub,
                product=cloud_suite,
                variant=v_std,
                quantity=1,
                unit_price=monthly_plan.base_price,
                tax_rate=cloud_suite.tax_rate,
            )

        # 6. Sample Invoices and Payments
        inv1, inv1_created = Invoice.objects.get_or_create(
            invoice_number="INV-2026-00001",
            defaults={
                "subscription": sub,
                "customer": customer,
                "discount": d_welcome,
                "billing_period_start": today - relativedelta(months=2),
                "billing_period_end": today - relativedelta(months=1) - relativedelta(days=1),
                "invoice_date": today - relativedelta(months=2),
                "due_date": today - relativedelta(months=2) + relativedelta(days=15),
                "subtotal": Decimal("2500.00"),
                "discount_amount": Decimal("500.00"),
                "taxable_amount": Decimal("2000.00"),
                "tax_amount": Decimal("360.00"),
                "total_amount": Decimal("2360.00"),
                "amount_paid": Decimal("2360.00"),
                "balance_due": Decimal("0.00"),
                "status": Invoice.Status.PAID,
            }
        )
        if inv1_created:
            InvoiceLine.objects.create(
                invoice=inv1,
                product=cloud_suite,
                variant=v_std,
                description="Cloud ERP Suite – Standard Edition",
                quantity=1,
                unit_price=Decimal("2500.00"),
                discount_amount=Decimal("500.00"),
                tax_rate=Decimal("18.00"),
                taxable_amount=Decimal("2000.00"),
                tax_amount=Decimal("360.00"),
                line_total=Decimal("2360.00"),
            )
            Payment.objects.create(
                payment_number="PAY-2026-00001",
                invoice=inv1,
                customer=customer,
                amount=Decimal("2360.00"),
                payment_method=Payment.Method.UPI,
                payment_date=today - relativedelta(months=2) + relativedelta(days=2),
                status=Payment.Status.SUCCESS,
                transaction_reference="UPI/20260815/99881122",
                recorded_by=staff_user,
            )

        # Current pending invoice
        inv2, inv2_created = Invoice.objects.get_or_create(
            invoice_number="INV-2026-00002",
            defaults={
                "subscription": sub,
                "customer": customer,
                "discount": d_welcome,
                "billing_period_start": today - relativedelta(months=1),
                "billing_period_end": today - relativedelta(days=1),
                "invoice_date": today - relativedelta(months=1),
                "due_date": today - relativedelta(months=1) + relativedelta(days=15),
                "subtotal": Decimal("2500.00"),
                "discount_amount": Decimal("500.00"),
                "taxable_amount": Decimal("2000.00"),
                "tax_amount": Decimal("360.00"),
                "total_amount": Decimal("2360.00"),
                "amount_paid": Decimal("1000.00"),
                "balance_due": Decimal("1360.00"),
                "status": Invoice.Status.PARTIALLY_PAID,
            }
        )
        if inv2_created:
            InvoiceLine.objects.create(
                invoice=inv2,
                product=cloud_suite,
                variant=v_std,
                description="Cloud ERP Suite – Standard Edition",
                quantity=1,
                unit_price=Decimal("2500.00"),
                discount_amount=Decimal("500.00"),
                tax_rate=Decimal("18.00"),
                taxable_amount=Decimal("2000.00"),
                tax_amount=Decimal("360.00"),
                line_total=Decimal("2360.00"),
            )
            Payment.objects.create(
                payment_number="PAY-2026-00002",
                invoice=inv2,
                customer=customer,
                amount=Decimal("1000.00"),
                payment_method=Payment.Method.CARD,
                payment_date=today - relativedelta(months=1) + relativedelta(days=5),
                status=Payment.Status.SUCCESS,
                transaction_reference="CARD/AUTH-441290",
                recorded_by=staff_user,
            )

        # 7. Monthly Revenue Snapshots (Past 6 months)
        for i in range(6, -1, -1):
            ym = (today - relativedelta(months=i)).strftime("%Y-%m")
            MonthlyRevenueSnapshot.objects.update_or_create(
                year_month=ym,
                defaults={
                    "billed_amount": Decimal("15000.00") + Decimal(i * 1200),
                    "collected_amount": Decimal("14000.00") + Decimal(i * 1000),
                    "tax_collected": Decimal("2700.00"),
                    "discounts_given": Decimal("1500.00"),
                }
            )

        self.stdout.write(self.style.SUCCESS("Demo dataset seeded successfully!"))
        self.stdout.write(self.style.SUCCESS(
            "\nCredentials:\n"
            "  Admin:    admin@subscribify.com    / Admin@1234\n"
            "  Staff:    staff@subscribify.com    / Staff@1234\n"
            "  Customer: customer@brightloop.in   / Customer@1234\n"
        ))
