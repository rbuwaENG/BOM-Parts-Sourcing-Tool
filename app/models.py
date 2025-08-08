from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Text,
    Boolean,
    ForeignKey,
    Index,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Supplier(Base):
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True, index=True)
    base_url = Column(String(1024), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    rules = relationship("SupplierRule", back_populates="supplier", cascade="all, delete-orphan")
    parts = relationship("Part", back_populates="supplier", cascade="all, delete-orphan")


class SupplierRule(Base):
    __tablename__ = "supplier_rules"

    id = Column(Integer, primary_key=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False, index=True)

    # Template search URL that includes '{query}' placeholder
    search_url_template = Column(String(2048), nullable=True)

    # CSS selectors for auto/manual mapping
    product_container_selector = Column(String(512), nullable=True)
    name_selector = Column(String(512), nullable=True)
    price_selector = Column(String(512), nullable=True)
    availability_selector = Column(String(512), nullable=True)
    part_number_selector = Column(String(512), nullable=True)
    datasheet_selector = Column(String(512), nullable=True)
    purchase_link_selector = Column(String(512), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    supplier = relationship("Supplier", back_populates="rules")


class Part(Base):
    __tablename__ = "parts"

    id = Column(Integer, primary_key=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False, index=True)

    part_number = Column(String(255), nullable=True, index=True)
    name = Column(String(512), nullable=True)
    description = Column(Text, nullable=True)
    package = Column(String(255), nullable=True)
    voltage = Column(String(255), nullable=True)
    other_specs = Column(Text, nullable=True)

    stock = Column(String(255), nullable=True)
    price_tiers_json = Column(Text, nullable=True)  # JSON string

    datasheet_url = Column(String(2048), nullable=True)
    purchase_url = Column(String(2048), nullable=True)

    last_updated = Column(DateTime, default=datetime.utcnow, nullable=False)

    supplier = relationship("Supplier", back_populates="parts")


Index("ix_parts_supplier_part", Part.supplier_id, Part.part_number)