# app/models/invoice.py
import uuid
from datetime import datetime, date
from sqlalchemy import Column, String, Float, DateTime, ForeignKey, Text, Integer, Date, DECIMAL
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import relationship
from app.db.base import Base

class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)

    # Numéro unique
    invoice_number = Column(String(50), unique=True, nullable=False, index=True)

    # Client
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=True)
    client_name = Column(String(100), nullable=False)
    client_address = Column(Text, nullable=True)
    client_tax_id = Column(String(50), nullable=True)

    # Vente associée
    sale_id = Column(UUID(as_uuid=True), ForeignKey("sales.id"), nullable=True)

    # Créateur
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    # Dates
    issue_date = Column(Date, nullable=False, default=date.today)
    due_date = Column(Date, nullable=True)

    # Montants financiers
    subtotal = Column(DECIMAL(15, 2), nullable=False, default=0.0)
    total_tax = Column(DECIMAL(15, 2), nullable=False, default=0.0)
    total_discount = Column(DECIMAL(15, 2), nullable=False, default=0.0)
    total_amount = Column(DECIMAL(15, 2), nullable=False, default=0.0)

    # Taxe
    tax_details = Column(JSON, default=dict)

    # Statut
    status = Column(String(20), default="draft", comment="draft, issued, sent, paid, overdue, cancelled")

    # Paiement
    payment_status = Column(String(20), default="pending", comment="pending, partially_paid, paid, overdue")
    amount_paid = Column(DECIMAL(15, 2), default=0.0)
    last_payment_date = Column(DateTime, nullable=True)

    # Métadonnées et fichiers
    notes = Column(Text, nullable=True)
    terms = Column(Text, nullable=True)
    footer = Column(Text, nullable=True)
    invoice_meta = Column(JSON, default=dict)
    pdf_path = Column(String(500), nullable=True)
    xml_path = Column(String(500), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    sent_at = Column(DateTime, nullable=True)
    paid_at = Column(DateTime, nullable=True)

    # =====================================
    # RELATIONS
    # =====================================
    tenant = relationship("Tenant")
    client = relationship("Client")
    sale = relationship("Sale")
    creator = relationship("User", foreign_keys=[created_by])
    items = relationship("InvoiceItem", back_populates="invoice", cascade="all, delete-orphan")
    payments = relationship("InvoicePayment", back_populates="invoice", cascade="all, delete-orphan")

    # =====================================
    # PROPRIÉTÉS
    # =====================================
    @property
    def amount_due(self):
        return float(self.total_amount - self.amount_paid)

    @property
    def days_overdue(self):
        if self.status == "overdue" and self.due_date:
            return (datetime.utcnow().date() - self.due_date).days
        return 0


class InvoiceItem(Base):
    __tablename__ = "invoice_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id = Column(UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)

    # Description
    description = Column(String(500), nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=True)

    # Quantité et prix
    quantity = Column(Integer, nullable=False, default=1)
    unit_price = Column(DECIMAL(15, 2), nullable=False)

    # Taxe et remise
    tax_rate = Column(DECIMAL(5, 2), default=0.0)
    discount_percent = Column(DECIMAL(5, 2), default=0.0)

    # Calculs
    subtotal = Column(DECIMAL(15, 2), nullable=False, default=0.0)
    tax_amount = Column(DECIMAL(15, 2), nullable=False, default=0.0)
    total = Column(DECIMAL(15, 2), nullable=False, default=0.0)

    # Métadonnées
    notes = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relations
    invoice = relationship("Invoice", back_populates="items")
    tenant = relationship("Tenant")
    product = relationship("Product")


class InvoicePayment(Base):
    __tablename__ = "invoice_payments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    invoice_id = Column(UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False)

    # Paiement
    amount = Column(DECIMAL(15, 2), nullable=False)
    payment_method = Column(String(20), nullable=False)
    reference = Column(String(100), nullable=True)

    # Métadonnées
    notes = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relations
    tenant = relationship("Tenant")
    invoice = relationship("Invoice", back_populates="payments")
