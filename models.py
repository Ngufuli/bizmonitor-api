"""
models.py — All database tables
Roles: admin | manager | employee
"""

from sqlalchemy import (
    Column, Integer, String, Float, Date, DateTime,
    Text, Boolean, ForeignKey, Enum as SAEnum
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from database import Base
import enum


# ── Enums ─────────────────────────────────────────────────────────────────────
class UserRole(str, enum.Enum):
    admin    = "admin"     # full access + user management
    manager  = "manager"   # read all dashboards, cannot manage users
    employee = "employee"  # data entry only


class MovementType(str, enum.Enum):
    add    = "add"
    remove = "remove"
    adjust = "adjust"


# ── Users ─────────────────────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    id              = Column(Integer, primary_key=True, index=True)
    email           = Column(String(255), unique=True, nullable=False, index=True)
    full_name       = Column(String(200), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role            = Column(SAEnum(UserRole), nullable=False, default=UserRole.employee)
    department      = Column(String(100), nullable=True)
    is_active       = Column(Boolean, default=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    # Relationships — track who created what
    sales     = relationship("Sale",     back_populates="created_by_user")
    expenses  = relationship("Expense",  back_populates="created_by_user")


# ── Sales ─────────────────────────────────────────────────────────────────────
class Sale(Base):
    __tablename__ = "sales"

    id             = Column(Integer, primary_key=True, index=True)
    date           = Column(Date, nullable=False, index=True)
    month          = Column(String(10), nullable=False)
    product        = Column(String(200), nullable=False)
    amount         = Column(Float, nullable=False)
    units          = Column(Integer, nullable=False)
    rep            = Column(String(100), nullable=True)
    notes          = Column(Text, nullable=True)
    created_by_id  = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())

    created_by_user = relationship("User", back_populates="sales")


# ── Expenses ──────────────────────────────────────────────────────────────────
class Expense(Base):
    __tablename__ = "expenses"

    id             = Column(Integer, primary_key=True, index=True)
    date           = Column(Date, nullable=False, index=True)
    month          = Column(String(10), nullable=False)
    category       = Column(String(100), nullable=False)
    amount         = Column(Float, nullable=False)
    vendor         = Column(String(200), nullable=False)
    description    = Column(Text, nullable=False)
    submitted_by   = Column(String(100), nullable=True)
    created_by_id  = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())

    created_by_user = relationship("User", back_populates="expenses")


# ── Inventory ─────────────────────────────────────────────────────────────────
class InventoryItem(Base):
    __tablename__ = "inventory"

    id         = Column(Integer, primary_key=True, index=True)
    sku        = Column(String(50), unique=True, nullable=False, index=True)
    name       = Column(String(200), nullable=False)
    stock      = Column(Integer, nullable=False, default=0)
    reorder    = Column(Integer, nullable=False, default=50)
    unit_cost  = Column(Float, nullable=False, default=0.0)
    status     = Column(String(20), nullable=False, default="ok")
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    movements = relationship("StockMovementLog", back_populates="item_ref", foreign_keys="StockMovementLog.sku", primaryjoin="InventoryItem.sku == StockMovementLog.sku")


# ── Stock Movement Audit Log ──────────────────────────────────────────────────
class StockMovementLog(Base):
    __tablename__ = "stock_movements"

    id             = Column(Integer, primary_key=True, index=True)
    sku            = Column(String(50), nullable=False, index=True)
    movement_type  = Column(String(20), nullable=False)
    qty            = Column(Integer, nullable=False)
    stock_before   = Column(Integer, nullable=False)
    stock_after    = Column(Integer, nullable=False)
    reason         = Column(String(300), nullable=True)
    received_by    = Column(String(100), nullable=True)
    created_by_id  = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())

    item_ref = relationship("InventoryItem", back_populates="movements", foreign_keys=[sku], primaryjoin="StockMovementLog.sku == InventoryItem.sku")
