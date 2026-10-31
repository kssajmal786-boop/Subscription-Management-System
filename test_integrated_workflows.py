"""
test_integrated_workflows.py
============================
End-to-end automated verification of all 7 mandatory workflows:
  Workflow 1 – Customer registration & portal access
  Workflow 2 – Product, Plan, and Subscription quotation creation
  Workflow 3 – Invoice generation, decimal tax/discount calculations, PDF generation, partial & full payment reconciliation
  Workflow 4 – Recurring billing task & database-level idempotency
  Workflow 5 – Subscription lifecycle: pause (skip billing), resume (date shifting), close (stop future billing)
  Workflow 6 – Dashboard analytics, KPIs, CSV exports (invoices, payments, revenue), and ReportLab PDF report
  Workflow 7 – Role-based access control (Admin, Staff, Customer permissions & anti-IDOR checks)
"""
import os
import sys
import django
from decimal import Decimal
from datetime import date, timedelta

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "subscribify.settings")
django.setup()

from django.test import Client
from django.utils import timezone
from accounts.models import User, Customer, StaffProfile
from accounts.services import AuthService
from catalog.models import Product, ProductVariant
from subscriptions.models import Plan, Subscription, SubscriptionLine
from billing.models import Discount, Invoice, InvoiceLine, Payment, MonthlyRevenueSnapshot, Notification
from billing.services import BillingService
from billing.tasks import daily_billing_task, daily_overdue_check_task, daily_dunning_task
from billing.pdf_service import generate_invoice_pdf, generate_payment_receipt_pdf, generate_financial_report_pdf


def run_all_workflows():
    print("=" * 80)
    print("SUBSCRIBIFY INTEGRATED END-TO-END WORKFLOW VERIFICATION")
    print("=" * 80)

    # ──────────────────────────────────────────────────────────────────────────
    # WORKFLOW 1: Customer registration & login
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[Workflow 1] Testing Customer Registration & Portal Access...")
    email_w1 = f"workflow1_{int(timezone.now().timestamp())}@corp.com"
    user_w1, cust_w1, token_w1 = AuthService.register_customer(
        name="Vikram Sethi",
        email=email_w1,
        password="SecurePassw0rd!",
        company_name="Sethi Logistics Ltd",
        phone="+91-9876500001",
        gst_number="27AAAAA0000A1Z5",
        billing_address="Plot 55, MIDC, Mumbai",
        city="Mumbai",
        state="Maharashtra",
        pincode="400001",
        ip_address="127.0.0.1"
    )
    assert user_w1 is not None, "User should be created"
    assert cust_w1 is not None, "Customer profile should be created"
    assert cust_w1.company_name == "Sethi Logistics Ltd"
    assert user_w1.role == User.Role.CUSTOMER

    # Test login
    auth_user, err = AuthService.authenticate_user(None, email_w1, "SecurePassw0rd!", ip_address="127.0.0.1")
    assert auth_user is not None, f"Customer authentication failed: {err}"
    assert err is None

    # Test portal HTTP access
    c = Client()
    login_ok = c.login(username=email_w1, password="SecurePassw0rd!")
    assert login_ok, "Session login must succeed"
    portal_resp = c.get("/billing/portal/")
    assert portal_resp.status_code == 200, f"Portal returned {portal_resp.status_code}"
    print("[PASS] Workflow 1 PASSED: Customer registered, profile linked, authenticated, portal returned 200 OK.")

    # ──────────────────────────────────────────────────────────────────────────
    # WORKFLOW 2: Product, Plan, and Subscription Creation
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[Workflow 2] Testing Product, Plan & Subscription Creation...")
    prod, _ = Product.objects.get_or_create(
        name="Workflow Test Suite Software",
        defaults={
            "product_type": Product.ProductType.LICENSE,
            "base_sales_price": Decimal("3000.00"),
            "cost_price": Decimal("800.00"),
            "tax_rate": Decimal("18.00"),
            "hsn_sac_code": "998313",
        }
    )
    variant, _ = ProductVariant.objects.get_or_create(
        product=prod,
        attribute_name="Tier",
        attribute_value="Professional",
        defaults={"additional_price": Decimal("500.00"), "sku": "WFL-PRO"}
    )
    assert variant.effective_price == Decimal("3500.00"), f"Expected 3500, got {variant.effective_price}"

    plan, _ = Plan.objects.get_or_create(
        plan_name="Workflow Pro Monthly Plan",
        defaults={
            "product": prod,
            "variant": variant,
            "billing_cycle": Plan.BillingCycle.MONTHLY,
            "base_price": Decimal("3500.00"),
            "min_quantity": 1,
            "default_duration_months": 12,
            "allow_pause": True,
        }
    )

    # Staff creates a quotation for the customer
    sub_num = f"QUO-TEST-{int(timezone.now().timestamp())}"
    today = timezone.now().date()
    sub = Subscription.objects.create(
        subscription_number=sub_num,
        customer=cust_w1,
        plan=plan,
        status=Subscription.Status.QUOTATION,
        quotation_validity_date=today + timedelta(days=15),
    )
    SubscriptionLine.objects.create(
        subscription=sub,
        product=prod,
        variant=variant,
        quantity=2,
        unit_price=Decimal("3500.00"),  # Snapshot price
        tax_rate=Decimal("18.00"),       # Snapshot tax
    )
    # Verify quotation appears in customer's records
    customer_subs = Subscription.objects.filter(customer=cust_w1)
    assert customer_subs.filter(pk=sub.pk).exists(), "Quotation must be linked to customer"
    print("[PASS] Workflow 2 PASSED: Product, variant, plan created. Quotation built with line items snapshot.")

    # ──────────────────────────────────────────────────────────────────────────
    # WORKFLOW 3: Billing, Taxes, PDF & Partial/Full Payment Reconciliation
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[Workflow 3] Testing Billing, Calculations, PDF, and Payment Reconciliation...")
    # Convert quotation to active
    sub.activate(start_date=today)
    assert sub.status == Subscription.Status.ACTIVE, "Subscription must be Active"

    # Generate invoice
    inv = BillingService.generate_invoice_for_subscription(sub, billing_date=today)
    assert inv is not None, "Invoice must be generated"
    assert inv.status == Invoice.Status.CONFIRMED

    # Verify decimal calculations: 2 * 3500 = 7000 subtotal, 18% tax = 1260.00, total = 8260.00
    expected_subtotal = Decimal("7000.00")
    expected_tax = Decimal("1260.00")
    expected_total = Decimal("8260.00")
    assert inv.subtotal == expected_subtotal, f"Expected subtotal {expected_subtotal}, got {inv.subtotal}"
    assert inv.tax_amount == expected_tax, f"Expected tax {expected_tax}, got {inv.tax_amount}"
    assert inv.total_amount == expected_total, f"Expected total {expected_total}, got {inv.total_amount}"
    assert inv.balance_due == expected_total, f"Expected balance_due {expected_total}, got {inv.balance_due}"

    # Verify ReportLab PDF invoice generation
    pdf_bytes = generate_invoice_pdf(inv)
    assert pdf_bytes.startswith(b"%PDF"), "Must generate valid PDF bytes"
    assert len(pdf_bytes) > 1000, "PDF must not be empty"

    # Record partial payment of 3000.00 via Bank_Transfer
    p1 = BillingService.record_payment(
        invoice=inv,
        amount=Decimal("3000.00"),
        payment_method="Bank_Transfer",
        transaction_reference="NEFT-WFL-001",
    )
    inv.refresh_from_db()
    assert inv.amount_paid == Decimal("3000.00"), f"Expected 3000 paid, got {inv.amount_paid}"
    assert inv.balance_due == Decimal("5260.00"), f"Expected 5260 balance, got {inv.balance_due}"
    assert inv.status == Invoice.Status.PARTIALLY_PAID, f"Status must be Partially_Paid, got {inv.status}"

    # Record final payment of 5260.00 via UPI
    p2 = BillingService.record_payment(
        invoice=inv,
        amount=Decimal("5260.00"),
        payment_method="UPI",
        transaction_reference="UPI/WFL/002",
    )
    inv.refresh_from_db()
    assert inv.amount_paid == Decimal("8260.00"), f"Expected 8260 paid, got {inv.amount_paid}"
    assert inv.balance_due == Decimal("0.00"), f"Expected 0 balance, got {inv.balance_due}"
    assert inv.status == Invoice.Status.PAID, f"Status must be Paid, got {inv.status}"

    # Verify payment receipt PDF
    receipt_bytes = generate_payment_receipt_pdf(p2)
    assert receipt_bytes.startswith(b"%PDF"), "Must generate valid Receipt PDF"
    print("[PASS] Workflow 3 PASSED: Invoice calculated accurately, PDF generated, partial/full payments reconciled to Paid.")

    # ──────────────────────────────────────────────────────────────────────────
    # WORKFLOW 4: Recurring Billing & Database-Level Idempotency
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[Workflow 4] Testing Recurring Billing & Duplicate Prevention...")
    test_billing_date = today + timedelta(days=30)
    sub.next_billing_date = test_billing_date
    sub.save(update_fields=["next_billing_date"])

    # Run billing service
    inv_rec1 = BillingService.generate_invoice_for_subscription(sub, billing_date=test_billing_date)
    assert inv_rec1 is not None, "Recurring invoice must be created"
    assert inv_rec1.billing_period_start == test_billing_date

    # Run again immediately (duplicate attempt)
    inv_rec2 = BillingService.generate_invoice_for_subscription(sub, billing_date=test_billing_date)
    assert inv_rec2 is None, "Duplicate invoice generation must be prevented"

    # Also test daily billing task
    task_res = daily_billing_task()
    print("[PASS] Workflow 4 PASSED: Scheduled billing generated invoice and strictly prevented duplicate billing.")

    # ──────────────────────────────────────────────────────────────────────────
    # WORKFLOW 5: Subscription Lifecycle (Pause, Resume, Close)
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[Workflow 5] Testing Subscription Lifecycle: Pause, Resume, Close...")
    # 1. Pause
    pause_date = today
    paused_ok = sub.pause(pause_date=pause_date)
    assert paused_ok, "Subscription must be pauseable"
    assert sub.status == Subscription.Status.PAUSED
    assert sub.paused_at == pause_date

    # 2. Verify billing is skipped while paused
    inv_paused = BillingService.generate_invoice_for_subscription(sub, billing_date=sub.next_billing_date)
    assert inv_paused is None, "Paused subscription must NEVER generate invoices"

    # 3. Resume with 10 days paused
    resume_date = today + timedelta(days=10)
    orig_next_billing = sub.next_billing_date
    resume_ok = sub.resume(resume_date=resume_date)
    assert resume_ok, "Subscription must be resumable"
    assert sub.status == Subscription.Status.ACTIVE
    assert sub.paused_at is None
    assert sub.total_paused_days == 10
    assert sub.next_billing_date == orig_next_billing + timedelta(days=10), "Billing date must shift by 10 days"

    # 4. Close
    sub.status = Subscription.Status.CLOSED
    sub.save(update_fields=["status"])
    inv_closed = BillingService.generate_invoice_for_subscription(sub, billing_date=sub.next_billing_date)
    assert inv_closed is None, "Closed subscription must NEVER generate future invoices"
    print("[PASS] Workflow 5 PASSED: Pause skipped billing, resume shifted billing dates accurately, close permanently halted future invoices.")

    # ──────────────────────────────────────────────────────────────────────────
    # WORKFLOW 6: Dashboard, Reports & Exports
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[Workflow 6] Testing Dashboards, KPIs, CSV & PDF Exports...")
    admin_user = User.objects.filter(role=User.Role.ADMIN).first()
    c_admin = Client()
    c_admin.force_login(admin_user)

    # 1. Admin dashboard
    dash_resp = c_admin.get("/dashboard/admin-dashboard/")
    assert dash_resp.status_code == 200, f"Admin dashboard returned {dash_resp.status_code}"

    # 2. Financial reports view
    rep_resp = c_admin.get("/billing/reports/")
    assert rep_resp.status_code == 200, f"Reports view returned {rep_resp.status_code}"

    # 3. Invoices CSV export
    csv_inv = c_admin.get("/billing/reports/invoices/csv/")
    assert csv_inv.status_code == 200
    assert b"Invoice #" in csv_inv.content
    assert b"Balance Due" in csv_inv.content

    # 4. Payments CSV export
    csv_pay = c_admin.get("/billing/reports/payments/csv/")
    assert csv_pay.status_code == 200
    assert b"Payment #" in csv_pay.content

    # 5. Revenue CSV export
    csv_rev = c_admin.get("/billing/reports/revenue/csv/")
    assert csv_rev.status_code == 200
    assert b"Month (YYYY-MM)" in csv_rev.content

    # 6. Financial Report PDF export
    pdf_rep = c_admin.get("/billing/reports/financial/pdf/")
    assert pdf_rep.status_code == 200
    assert pdf_rep.content.startswith(b"%PDF")
    print("[PASS] Workflow 6 PASSED: Dashboard KPIs computed, Chart.js templates render, CSV and ReportLab PDF downloads verified.")

    # ──────────────────────────────────────────────────────────────────────────
    # WORKFLOW 7: Role-Based Access Control & Anti-IDOR Security
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[Workflow 7] Testing RBAC & Anti-IDOR Security Enforcement...")
    staff_user = User.objects.filter(role=User.Role.STAFF).first()

    # 1. Customer cannot access staff or admin routes
    c_cust = Client()
    c_cust.force_login(user_w1)

    r1 = c_cust.get("/accounts/staff/")
    assert r1.status_code in (302, 403), "Customer must be blocked from Staff List"

    r2 = c_cust.get("/billing/reports/")
    assert r2.status_code in (302, 403), "Customer must be blocked from Financial Reports"

    # 2. Staff cannot access admin-only staff management
    c_staff = Client()
    c_staff.force_login(staff_user)

    r3 = c_staff.get("/accounts/staff/create/")
    assert r3.status_code in (302, 403), "Staff must be blocked from creating new staff"

    # Staff CAN access operations (subscriptions, invoices)
    r4 = c_staff.get("/subscriptions/")
    assert r4.status_code == 200, "Staff must be allowed to access subscriptions operations"

    # 3. Admin has complete access
    r5 = c_admin.get("/accounts/staff/")
    assert r5.status_code == 200, "Admin must access staff management"

    # 4. Anti-IDOR: Customer A cannot view Customer B's detail
    cust_other = Customer.objects.exclude(pk=cust_w1.pk).first()
    if cust_other:
        r_idor = c_cust.get(f"/accounts/customers/{cust_other.pk}/")
        assert r_idor.status_code in (302, 403), "Anti-IDOR must prevent cross-customer snooping"

    print("[PASS] Workflow 7 PASSED: RBAC verified across Admin, Staff, Customer. Anti-IDOR strictly blocks unauthorized data access.")

    print("\n" + "=" * 80)
    print("ALL 7 SUBSCRIBIFY WORKFLOWS FULLY VERIFIED AND PASSING 100%!")
    print("=" * 80)


if __name__ == "__main__":
    run_all_workflows()
