"""
billing/pdf_service.py
======================
ReportLab-based professional PDF invoice and payment receipt generator.
Outputs GST-compliant tax invoices with company branding.
"""
import os
import io
from decimal import Decimal
from django.conf import settings
from django.utils import timezone

# ReportLab imports
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, HRFlowable, KeepTogether
)
from reportlab.platypus.flowables import HRFlowable

# Brand colors
BRAND_PURPLE = colors.HexColor("#6C3CE1")
BRAND_DARK = colors.HexColor("#1A1035")
BRAND_LIGHT_BG = colors.HexColor("#F4F1FD")
BRAND_BORDER = colors.HexColor("#DDD6FE")
TEXT_MUTED = colors.HexColor("#6B7280")
SUCCESS_GREEN = colors.HexColor("#10B981")
DANGER_RED = colors.HexColor("#EF4444")
WARNING_AMBER = colors.HexColor("#F59E0B")


def _styles():
    base = getSampleStyleSheet()
    styles = {
        "company_name": ParagraphStyle("CompanyName", fontSize=20, textColor=BRAND_PURPLE,
                                       fontName="Helvetica-Bold", spaceAfter=2),
        "company_detail": ParagraphStyle("CompanyDetail", fontSize=8, textColor=TEXT_MUTED,
                                         fontName="Helvetica", spaceAfter=1),
        "invoice_title": ParagraphStyle("InvoiceTitle", fontSize=26, textColor=BRAND_DARK,
                                        fontName="Helvetica-Bold", alignment=TA_RIGHT),
        "invoice_number": ParagraphStyle("InvoiceNumber", fontSize=11, textColor=BRAND_PURPLE,
                                         fontName="Helvetica-Bold", alignment=TA_RIGHT),
        "section_header": ParagraphStyle("SectionHeader", fontSize=9, textColor=BRAND_PURPLE,
                                         fontName="Helvetica-Bold", spaceBefore=4, spaceAfter=2),
        "body": ParagraphStyle("Body", fontSize=9, textColor=BRAND_DARK,
                               fontName="Helvetica", spaceAfter=1),
        "body_bold": ParagraphStyle("BodyBold", fontSize=9, textColor=BRAND_DARK,
                                    fontName="Helvetica-Bold", spaceAfter=1),
        "small": ParagraphStyle("Small", fontSize=8, textColor=TEXT_MUTED, fontName="Helvetica"),
        "total_label": ParagraphStyle("TotalLabel", fontSize=11, textColor=BRAND_DARK,
                                      fontName="Helvetica-Bold", alignment=TA_RIGHT),
        "total_value": ParagraphStyle("TotalValue", fontSize=13, textColor=BRAND_PURPLE,
                                      fontName="Helvetica-Bold", alignment=TA_RIGHT),
        "status_paid": ParagraphStyle("StatusPaid", fontSize=24, textColor=SUCCESS_GREEN,
                                      fontName="Helvetica-Bold", alignment=TA_CENTER),
        "status_due": ParagraphStyle("StatusDue", fontSize=24, textColor=DANGER_RED,
                                     fontName="Helvetica-Bold", alignment=TA_CENTER),
        "footer": ParagraphStyle("Footer", fontSize=8, textColor=TEXT_MUTED,
                                 fontName="Helvetica", alignment=TA_CENTER),
    }
    return styles


def generate_invoice_pdf(invoice) -> bytes:
    """
    Generate a professional A4 PDF for the given Invoice instance.
    Returns the PDF as bytes.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=20 * mm,
        title=f"Invoice {invoice.invoice_number}",
        author=settings.COMPANY_NAME,
    )

    S = _styles()
    story = []
    page_width = A4[0] - 30 * mm  # usable width

    # ── Header: Company info (left) + Invoice title (right) ──────────
    header_data = [
        [
            Paragraph(settings.COMPANY_NAME, S["company_name"]),
            Paragraph("TAX INVOICE", S["invoice_title"]),
        ],
        [
            Paragraph(settings.COMPANY_ADDRESS, S["company_detail"]),
            Paragraph(invoice.invoice_number, S["invoice_number"]),
        ],
        [
            Paragraph(f"GSTIN: {settings.COMPANY_GSTIN}", S["company_detail"]),
            Paragraph(f"Date: {invoice.invoice_date.strftime('%d %b %Y')}", S["small"]),
        ],
        [
            Paragraph(f"Phone: {settings.COMPANY_PHONE} | {settings.COMPANY_EMAIL}", S["company_detail"]),
            Paragraph(f"Due: {invoice.due_date.strftime('%d %b %Y')}", S["small"]),
        ],
    ]
    header_table = Table(header_data, colWidths=[page_width * 0.6, page_width * 0.4])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(header_table)
    story.append(HRFlowable(width="100%", thickness=2, color=BRAND_PURPLE, spaceAfter=8))

    # ── Status watermark ─────────────────────────────────────────────
    if invoice.status == "Paid":
        story.append(Paragraph("✓ PAID", S["status_paid"]))
    elif invoice.status == "Overdue":
        story.append(Paragraph("⚠ OVERDUE", S["status_due"]))
    story.append(Spacer(1, 4 * mm))

    # ── Bill To / Subscription Info ──────────────────────────────────
    customer = invoice.customer
    sub = invoice.subscription
    bill_info = [
        [
            _section_block("BILL TO", [
                customer.user.get_full_name(),
                customer.company_name or "",
                customer.billing_address or "",
                f"GSTIN: {customer.gst_number}" if customer.gst_number else "",
                f"Phone: {customer.phone}" if customer.phone else "",
                customer.user.email,
            ], S),
            _section_block("SUBSCRIPTION DETAILS", [
                f"Ref: {sub.subscription_number}",
                f"Plan: {sub.plan.plan_name}",
                f"Billing Cycle: {sub.plan.billing_cycle}",
                f"Period: {invoice.billing_period_start.strftime('%d %b %Y')} – {invoice.billing_period_end.strftime('%d %b %Y')}",
            ], S),
        ]
    ]
    bill_table = Table(bill_info, colWidths=[page_width * 0.5, page_width * 0.5])
    bill_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BRAND_LIGHT_BG),
        ("BOX", (0, 0), (-1, -1), 0.5, BRAND_BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, BRAND_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(bill_table)
    story.append(Spacer(1, 5 * mm))

    # ── Line Items Table ─────────────────────────────────────────────
    story.append(Paragraph("ITEM DETAILS", S["section_header"]))
    col_labels = ["#", "Description", "Qty", "Unit Price", "Discount", "Taxable", "Tax %", "Tax Amt", "Total"]
    col_widths = [8 * mm, 55 * mm, 12 * mm, 22 * mm, 18 * mm, 22 * mm, 12 * mm, 18 * mm, 22 * mm]

    lines = invoice.lines.select_related("product", "variant").all()
    item_data = [col_labels]
    for idx, line in enumerate(lines, 1):
        item_data.append([
            str(idx),
            Paragraph(line.description, S["body"]),
            str(line.quantity),
            f"₹{line.unit_price:,.2f}",
            f"₹{line.discount_amount:,.2f}" if line.discount_amount else "—",
            f"₹{line.taxable_amount:,.2f}",
            f"{line.tax_rate}%",
            f"₹{line.tax_amount:,.2f}",
            f"₹{line.line_total:,.2f}",
        ])

    line_table = Table(item_data, colWidths=col_widths, repeatRows=1)
    line_table.setStyle(TableStyle([
        # Header
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_PURPLE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        # Rows
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 1), (0, -1), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BRAND_LIGHT_BG]),
        ("GRID", (0, 0), (-1, -1), 0.4, BRAND_BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(line_table)
    story.append(Spacer(1, 4 * mm))

    # ── Totals Block ─────────────────────────────────────────────────
    totals_data = [
        ["Subtotal:", f"₹{invoice.subtotal:,.2f}"],
        ["Discount:", f"– ₹{invoice.discount_amount:,.2f}"],
        ["Taxable Amount:", f"₹{invoice.taxable_amount:,.2f}"],
        ["GST / Tax:", f"₹{invoice.tax_amount:,.2f}"],
        ["", ""],  # separator
        ["TOTAL:", f"₹{invoice.total_amount:,.2f}"],
        ["Amount Paid:", f"₹{invoice.amount_paid:,.2f}"],
        ["Balance Due:", f"₹{invoice.balance_due:,.2f}"],
    ]
    totals_table = Table(totals_data, colWidths=[page_width - 50 * mm, 50 * mm])
    totals_style = [
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 5), (1, 5), "Helvetica-Bold"),
        ("FONTSIZE", (0, 5), (1, 5), 11),
        ("TEXTCOLOR", (0, 5), (1, 5), BRAND_PURPLE),
        ("FONTNAME", (1, 7), (1, 7), "Helvetica-Bold"),
        ("TEXTCOLOR", (1, 7), (1, 7), DANGER_RED if invoice.balance_due > 0 else SUCCESS_GREEN),
        ("LINEABOVE", (0, 5), (-1, 5), 1.5, BRAND_PURPLE),
        ("LINEBELOW", (0, 7), (-1, 7), 1.5, BRAND_PURPLE),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    totals_table.setStyle(TableStyle(totals_style))
    story.append(totals_table)

    # ── Discount info ────────────────────────────────────────────────
    if invoice.discount:
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph(
            f"✔ Discount Applied: {invoice.discount.name} ({invoice.discount.code})",
            S["small"]
        ))

    # ── Payment Instructions ─────────────────────────────────────────
    story.append(Spacer(1, 5 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BRAND_BORDER))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("PAYMENT INSTRUCTIONS", S["section_header"]))
    pay_text = (
        "Pay by Bank Transfer (NEFT/RTGS): Account details available on request. "
        "UPI: billing@brightloop | Please quote your invoice number as payment reference. "
        f"Payment due by <b>{invoice.due_date.strftime('%d %b %Y')}</b>."
    )
    story.append(Paragraph(pay_text, S["body"]))

    # ── Footer ───────────────────────────────────────────────────────
    story.append(Spacer(1, 5 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BRAND_BORDER))
    story.append(Paragraph(
        f"This is a computer-generated invoice. No signature required. | "
        f"Generated by Subscribify on {timezone.now().strftime('%d %b %Y %H:%M IST')} | "
        f"{settings.COMPANY_NAME} · {settings.COMPANY_GSTIN}",
        S["footer"]
    ))

    doc.build(story)
    return buffer.getvalue()


def generate_payment_receipt_pdf(payment) -> bytes:
    """Generate a payment receipt PDF."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
        title=f"Receipt {payment.payment_number}",
    )
    S = _styles()
    story = []
    page_width = A4[0] - 40 * mm
    invoice = payment.invoice

    # Header
    story.append(Paragraph(settings.COMPANY_NAME, S["company_name"]))
    story.append(Paragraph("PAYMENT RECEIPT", S["invoice_title"]))
    story.append(HRFlowable(width="100%", thickness=2, color=BRAND_PURPLE, spaceAfter=8))
    story.append(Paragraph("✓ PAYMENT RECEIVED", S["status_paid"]))
    story.append(Spacer(1, 5 * mm))

    receipt_data = [
        ["Receipt Number:", payment.payment_number],
        ["Invoice Number:", invoice.invoice_number],
        ["Customer:", payment.customer.user.get_full_name()],
        ["Payment Date:", payment.payment_date.strftime("%d %b %Y")],
        ["Payment Method:", payment.get_payment_method_display()],
        ["Transaction Ref:", payment.transaction_reference or "—"],
        ["Amount Paid:", f"₹{payment.amount:,.2f}"],
        ["Balance Remaining:", f"₹{invoice.balance_due:,.2f}"],
    ]

    t = Table(receipt_data, colWidths=[60 * mm, page_width - 60 * mm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTNAME", (1, 6), (1, 6), "Helvetica-Bold"),
        ("FONTSIZE", (1, 6), (1, 6), 14),
        ("TEXTCOLOR", (1, 6), (1, 6), SUCCESS_GREEN),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, BRAND_LIGHT_BG]),
        ("BOX", (0, 0), (-1, -1), 0.5, BRAND_BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, BRAND_BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(t)
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(
        f"Thank you for your payment! | {settings.COMPANY_NAME} · {settings.COMPANY_GSTIN}",
        S["footer"]
    ))

    doc.build(story)
    return buffer.getvalue()


def save_invoice_pdf(invoice) -> str:
    """Generate PDF and save to MEDIA_ROOT. Returns relative file path."""
    pdf_bytes = generate_invoice_pdf(invoice)
    rel_path = f"{settings.PDF_STORAGE_PATH}{invoice.invoice_number}.pdf"
    abs_path = os.path.join(settings.MEDIA_ROOT, rel_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "wb") as f:
        f.write(pdf_bytes)
    return rel_path


def _section_block(title: str, lines: list, S: dict):
    """Helper: returns a Paragraph block for bill-to / subscription sections."""
    from reportlab.platypus import KeepInFrame
    parts = [Paragraph(f"<b>{title}</b>", S["section_header"])]
    for line in lines:
        if line:
            parts.append(Paragraph(line, S["body"]))
    from reportlab.platypus import ListFlowable
    return parts


def generate_financial_report_pdf(summary_data, snapshots) -> bytes:
    """Generate an executive financial analytics PDF report."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title="Subscribify Financial Report",
    )
    S = _styles()
    story = []
    page_width = A4[0] - 30 * mm

    # Header
    story.append(Paragraph(settings.COMPANY_NAME, S["company_name"]))
    story.append(Paragraph("EXECUTIVE FINANCIAL REPORT", S["invoice_title"]))
    story.append(HRFlowable(width="100%", thickness=2, color=BRAND_PURPLE, spaceAfter=8))
    story.append(Paragraph(f"Generated on {timezone.now().strftime('%d %B %Y, %I:%M %p IST')}", S["small"]))
    story.append(Spacer(1, 4 * mm))

    # KPI Summary Grid
    kpi_rows = [
        ["Total Billed Revenue:", f"₹{summary_data.get('billed', 0):,.2f}",
         "Total Collected Revenue:", f"₹{summary_data.get('collected', 0):,.2f}"],
        ["Pending Receivables:", f"₹{summary_data.get('pending', 0):,.2f}",
         "Overdue Amount:", f"₹{summary_data.get('overdue', 0):,.2f}"],
        ["Active Subscriptions:", str(summary_data.get('active_subs', 0)),
         "Total Customers:", str(summary_data.get('customers', 0))],
    ]
    kpi_table = Table(kpi_rows, colWidths=[40 * mm, 45 * mm, 45 * mm, 40 * mm])
    kpi_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, -1), BRAND_LIGHT_BG),
        ("BOX", (0, 0), (-1, -1), 0.5, BRAND_BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, BRAND_BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(kpi_table)
    story.append(Spacer(1, 6 * mm))

    # Monthly Trends Table
    story.append(Paragraph("<b>12-Month Revenue & Collection Trends</b>", S["section_header"]))
    snap_headers = ["Month", "Billed (₹)", "Collected (₹)", "Tax (₹)", "Discounts (₹)", "Active Subs"]
    snap_rows = [snap_headers]
    for s in snapshots:
        snap_rows.append([
            s.year_month,
            f"{s.billed_amount:,.2f}",
            f"{s.collected_amount:,.2f}",
            f"{s.tax_collected:,.2f}",
            f"{s.discounts_given:,.2f}",
            str(s.active_subscriptions_count),
        ])

    if len(snap_rows) == 1:
        snap_rows.append(["No monthly snapshots recorded yet.", "—", "—", "—", "—", "—"])

    snap_table = Table(snap_rows, colWidths=[page_width / 6] * 6)
    snap_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_PURPLE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BRAND_LIGHT_BG]),
        ("BOX", (0, 0), (-1, -1), 0.5, BRAND_BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, BRAND_BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(snap_table)
    story.append(Spacer(1, 8 * mm))

    story.append(Paragraph(
        f"Confidential Financial Report | {settings.COMPANY_NAME} | Subscribify Automated Billing Platform",
        S["footer"]
    ))
    doc.build(story)
    return buffer.getvalue()

