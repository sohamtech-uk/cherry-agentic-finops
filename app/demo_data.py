from __future__ import annotations

from datetime import date

from app.models import BankTransaction, DocumentExtraction, InvoiceLine


def autonomous_scenario() -> tuple[DocumentExtraction, list[BankTransaction]]:
    extraction = DocumentExtraction(
        document_type="invoice",
        supplier_name="Office Solutions Co.",
        supplier_registration="GB 428 5512 17",
        invoice_number="INV-98214",
        issue_date=date(2026, 8, 18),
        due_date=date(2026, 8, 22),
        currency="GBP",
        subtotal="2041.67",
        tax="408.33",
        total="2450.00",
        payment_reference="INV-98214",
        suggested_category="Office equipment and supplies",
        vat_treatment="Standard-rated purchase (20%)",
        lines=[
            InvoiceLine(
                description="Ergonomic workspace equipment",
                quantity=1,
                unit_price="2041.67",
                net_amount="2041.67",
                tax_amount="408.33",
            )
        ],
        confidence=98,
        source="demo",
    )
    transactions = [
        BankTransaction(
            transaction_id="bank_tx_98214",
            booking_date=date(2026, 8, 22),
            amount="2450.00",
            currency="GBP",
            direction="debit",
            description="OFFICE SOLUTIONS CO INV-98214",
            merchant_name="Office Solutions Co.",
            reference="INV-98214",
        ),
        BankTransaction(
            transaction_id="bank_tx_nearby_1",
            booking_date=date(2026, 8, 21),
            amount="2410.00",
            currency="GBP",
            direction="debit",
            description="OFFICE FURNITURE DIRECT",
            merchant_name="Office Furniture Direct",
            reference="ORDER-5509",
        ),
        BankTransaction(
            transaction_id="bank_tx_nearby_2",
            booking_date=date(2026, 8, 25),
            amount="2450.00",
            currency="GBP",
            direction="debit",
            description="COMMERCIAL SERVICES LTD",
            merchant_name="Commercial Services Ltd",
            reference="PAYMENT",
        ),
    ]
    return extraction, transactions


def approval_scenario() -> tuple[DocumentExtraction, list[BankTransaction]]:
    extraction = DocumentExtraction(
        document_type="invoice",
        supplier_name="Northstar Digital Systems Ltd",
        supplier_registration="GB 776 4021 91",
        invoice_number="NDS-2048",
        issue_date=date(2026, 8, 16),
        due_date=date(2026, 8, 23),
        currency="GBP",
        subtotal="10416.67",
        tax="2083.33",
        total="12500.00",
        payment_reference="NDS-2048",
        suggested_category="Software and technology services",
        vat_treatment="Standard-rated purchase (20%)",
        lines=[
            InvoiceLine(
                description="Finance platform implementation milestone",
                quantity=1,
                unit_price="10416.67",
                net_amount="10416.67",
                tax_amount="2083.33",
            )
        ],
        confidence=97,
        source="demo",
    )
    transactions = [
        BankTransaction(
            transaction_id="bank_tx_nds_2048",
            booking_date=date(2026, 8, 23),
            amount="12500.00",
            currency="GBP",
            direction="debit",
            description="NORTHSTAR DIGITAL NDS-2048",
            merchant_name="Northstar Digital Systems Ltd",
            reference="NDS-2048",
        ),
        BankTransaction(
            transaction_id="bank_tx_nds_alt",
            booking_date=date(2026, 8, 22),
            amount="12400.00",
            currency="GBP",
            direction="debit",
            description="NORTHSTAR DIGITAL",
            merchant_name="Northstar Digital Systems",
            reference="NDS-MILESTONE",
        ),
    ]
    return extraction, transactions


def exception_scenario() -> tuple[DocumentExtraction, list[BankTransaction]]:
    extraction = DocumentExtraction(
        document_type="receipt",
        supplier_name="Brightline Events",
        invoice_number="BL-7781",
        issue_date=date(2026, 8, 20),
        due_date=date(2026, 8, 20),
        currency="GBP",
        subtotal="1100.00",
        tax="220.00",
        total="1320.00",
        payment_reference="BL-7781",
        suggested_category="Events and community engagement",
        vat_treatment="Standard-rated purchase (20%)",
        confidence=91,
        source="demo",
        warnings=["The bank amount is expected to require supporting evidence."],
    )
    transactions = [
        BankTransaction(
            transaction_id="bank_tx_bl_7781",
            booking_date=date(2026, 8, 20),
            amount="1520.00",
            currency="GBP",
            direction="debit",
            description="BRIGHTLINE EVENTS BL-7781",
            merchant_name="Brightline Events",
            reference="BL-7781",
        ),
        BankTransaction(
            transaction_id="bank_tx_bl_small",
            booking_date=date(2026, 8, 18),
            amount="320.00",
            currency="GBP",
            direction="debit",
            description="BRIGHTLINE EVENTS DEPOSIT",
            merchant_name="Brightline Events",
            reference="BL-DEPOSIT",
        ),
    ]
    return extraction, transactions


SCENARIOS = {
    "autonomous": autonomous_scenario,
    "approval": approval_scenario,
    "exception": exception_scenario,
}
