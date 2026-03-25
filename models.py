"""
models.py — All database tables
"""

from sqlalchemy import (
    Column, Integer, String, Float, Date, DateTime,
    Text, Boolean, ForeignKey, Enum as SAEnum, Numeric
)
from sqlalchemy.sql import func, text
from sqlalchemy.orm import relationship
from database import Base
import enum


class UserRole(str, enum.Enum):
    admin    = "admin"
    manager  = "manager"
    employee = "employee"


# ── Business ──────────────────────────────────────────────────────────────────
class Business(Base):
    __tablename__ = "businesses"
    id         = Column(Integer, primary_key=True, index=True)
    name       = Column(String(200), nullable=False)
    industry   = Column(String(100), nullable=True)
    currency   = Column(String(10),  nullable=False, default="USD")
    is_active  = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    members   = relationship("BusinessMember", back_populates="business")
    sales     = relationship("Sale",           back_populates="business")
    expenses  = relationship("Expense",        back_populates="business")
    inventory = relationship("InventoryItem",  back_populates="business")


# ── BusinessMember ────────────────────────────────────────────────────────────
class BusinessMember(Base):
    __tablename__ = "business_members"
    id          = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=False)
    user_id     = Column(Integer, ForeignKey("users.id"),      nullable=False)
    role        = Column(SAEnum(UserRole), nullable=False, default=UserRole.employee)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    business = relationship("Business", back_populates="members")
    user     = relationship("User",     back_populates="memberships")


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

    memberships = relationship("BusinessMember", back_populates="user")
    sales       = relationship("Sale",     back_populates="created_by_user")
    expenses    = relationship("Expense",  back_populates="created_by_user")


# ── Sales ─────────────────────────────────────────────────────────────────────
class Sale(Base):
    __tablename__ = "sales"
    id            = Column(Integer, primary_key=True, index=True)
    business_id   = Column(Integer, ForeignKey("businesses.id"), nullable=False, index=True)
    date          = Column(Date,    nullable=False, index=True)
    month         = Column(String(10), nullable=False)
    product       = Column(String(200), nullable=False)
    amount        = Column(Float, nullable=False)
    units         = Column(Integer, nullable=False)
    rep           = Column(String(100), nullable=True)
    notes         = Column(Text,    nullable=True)
    # These columns added via migration — nullable so existing rows work
    sku           = Column(String(50),  nullable=True)
    unit_price    = Column(Float,       nullable=True)
    unit_cost     = Column(Float,       nullable=True, server_default=text("0"))
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())

    business        = relationship("Business", back_populates="sales")
    created_by_user = relationship("User",     back_populates="sales")


# ── Expenses ──────────────────────────────────────────────────────────────────
class Expense(Base):
    __tablename__ = "expenses"
    id            = Column(Integer, primary_key=True, index=True)
    business_id   = Column(Integer, ForeignKey("businesses.id"), nullable=False, index=True)
    date          = Column(Date,    nullable=False, index=True)
    month         = Column(String(10), nullable=False)
    category      = Column(String(100), nullable=False)
    amount        = Column(Float,   nullable=False)
    vendor        = Column(String(200), nullable=False)
    description   = Column(Text,    nullable=False)
    submitted_by  = Column(String(100), nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())

    business        = relationship("Business", back_populates="expenses")
    created_by_user = relationship("User",     back_populates="expenses")


# ── Inventory ─────────────────────────────────────────────────────────────────
class InventoryItem(Base):
    __tablename__ = "inventory"
    id          = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=False, index=True)
    sku         = Column(String(50),  nullable=False, index=True)
    name        = Column(String(200), nullable=False)
    stock       = Column(Integer, nullable=False, default=0)
    reorder     = Column(Integer, nullable=False, default=50)
    unit_cost   = Column(Float,   nullable=False, default=0.0)
    status      = Column(String(20), nullable=False, default="ok")
    updated_at  = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    business = relationship("Business", back_populates="inventory")


# ── Stock Movement Audit Log ──────────────────────────────────────────────────
class StockMovementLog(Base):
    __tablename__ = "stock_movements"
    id            = Column(Integer, primary_key=True, index=True)
    business_id   = Column(Integer, ForeignKey("businesses.id"), nullable=False)
    sku           = Column(String(50), nullable=False, index=True)
    movement_type = Column(String(20), nullable=False)
    qty           = Column(Integer, nullable=False)
    stock_before  = Column(Integer, nullable=False)
    stock_after   = Column(Integer, nullable=False)
    reason        = Column(String(300), nullable=True)
    received_by   = Column(String(100), nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())


# ── Cash Balances ─────────────────────────────────────────────────────────────
class CashBalance(Base):
    __tablename__ = "cash_balances"
    id              = Column(Integer, primary_key=True, index=True)
    business_id     = Column(Integer, ForeignKey("businesses.id"), nullable=False, index=True)
    date            = Column(Date,    nullable=False, index=True)
    opening_balance = Column(Float,   nullable=False, default=0.0)
    closing_balance = Column(Float,   nullable=False, default=0.0)
    notes           = Column(Text,    nullable=True)
    recorded_by_id  = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    business = relationship("Business", foreign_keys=[business_id])


# ── Activity Log ──────────────────────────────────────────────────────────────
class ActivityLog(Base):
    __tablename__ = "activity_logs"
    id          = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=True)
    user_id     = Column(Integer, ForeignKey("users.id"),      nullable=True)
    action      = Column(String(100), nullable=False)
    detail      = Column(Text,        nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
