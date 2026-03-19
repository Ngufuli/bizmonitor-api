"""
schemas.py — Pydantic request/response models
"""

from pydantic import BaseModel, Field, EmailStr, validator
from typing import Optional
from datetime import date, datetime
from models import UserRole

MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
VALID_CATEGORIES = ["Operations","Marketing","Payroll","Travel","Utilities","Office Supplies","Software","Other"]

def month_from_date(d: date) -> str:
    return MONTHS[d.month - 1]


# ── Auth ──────────────────────────────────────────────────────────────────────
class Token(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    user:         "UserOut"

class TokenData(BaseModel):
    user_id: Optional[int] = None


# ── Users ─────────────────────────────────────────────────────────────────────
class UserCreate(BaseModel):
    email:      EmailStr
    full_name:  str = Field(..., min_length=2, max_length=200)
    password:   str = Field(..., min_length=8)
    role:       UserRole = UserRole.employee
    department: Optional[str] = None

    @validator("password")
    def strong_password(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v

class UserUpdate(BaseModel):
    full_name:  Optional[str] = None
    role:       Optional[UserRole] = None
    department: Optional[str] = None
    is_active:  Optional[bool] = None

class UserOut(BaseModel):
    id:         int
    email:      str
    full_name:  str
    role:       UserRole
    department: Optional[str]
    is_active:  bool
    created_at: datetime

    class Config:
        from_attributes = True

class ChangePassword(BaseModel):
    current_password: str
    new_password:     str = Field(..., min_length=8)


# ── Sales ─────────────────────────────────────────────────────────────────────
class SaleCreate(BaseModel):
    date:    date
    product: str = Field(..., min_length=1, max_length=200)
    amount:  float = Field(..., gt=0)
    units:   int   = Field(..., gt=0)
    rep:     Optional[str] = None
    notes:   Optional[str] = None

class SaleOut(SaleCreate):
    id:         int
    month:      str
    created_by_id: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True


# ── Expenses ──────────────────────────────────────────────────────────────────
class ExpenseCreate(BaseModel):
    date:         date
    category:     str
    amount:       float = Field(..., gt=0)
    vendor:       str   = Field(..., min_length=1)
    description:  str   = Field(..., min_length=1)
    submitted_by: Optional[str] = None

    @validator("category")
    def valid_category(cls, v):
        if v not in VALID_CATEGORIES:
            raise ValueError(f"Must be one of: {VALID_CATEGORIES}")
        return v

class ExpenseOut(ExpenseCreate):
    id:            int
    month:         str
    created_by_id: Optional[int]
    created_at:    datetime

    class Config:
        from_attributes = True


# ── Inventory ─────────────────────────────────────────────────────────────────
class InventoryCreate(BaseModel):
    sku:       str   = Field(..., min_length=1, max_length=50)
    name:      str   = Field(..., min_length=1, max_length=200)
    stock:     int   = Field(0, ge=0)
    reorder:   int   = Field(50, ge=0)
    unit_cost: float = Field(0.0, ge=0)

class InventoryOut(InventoryCreate):
    id:         int
    status:     str
    updated_at: datetime

    class Config:
        from_attributes = True

class StockMovement(BaseModel):
    movement_type: str = Field(..., description="add | remove | adjust")
    qty:           int = Field(..., gt=0)
    reason:        Optional[str] = None
    received_by:   Optional[str] = None

    @validator("movement_type")
    def valid_type(cls, v):
        if v not in ("add", "remove", "adjust"):
            raise ValueError("Must be add, remove, or adjust")
        return v

class StockMovementOut(BaseModel):
    id:            int
    sku:           str
    movement_type: str
    qty:           int
    stock_before:  int
    stock_after:   int
    reason:        Optional[str]
    received_by:   Optional[str]
    created_at:    datetime

    class Config:
        from_attributes = True


# ── Summary ───────────────────────────────────────────────────────────────────
class SummaryOut(BaseModel):
    total_revenue:        float
    total_expenses:       float
    net_profit:           float
    profit_margin:        float
    inventory_value:      float
    low_stock_count:      int
    out_of_stock_count:   int
    total_sales_entries:  int
    total_expense_entries: int


# Fix forward reference
Token.model_rebuild()
