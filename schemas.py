"""
schemas.py — Pydantic request/response models
"""

from pydantic import BaseModel, Field, EmailStr, validator
from typing import Optional, List
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


# ── Business ──────────────────────────────────────────────────────────────────
class BusinessCreate(BaseModel):
    name:     str = Field(..., min_length=1, max_length=200)
    industry: Optional[str] = None
    currency: str = "USD"

class BusinessUpdate(BaseModel):
    name:      Optional[str]  = None
    industry:  Optional[str]  = None
    currency:  Optional[str]  = None
    is_active: Optional[bool] = None

class BusinessOut(BaseModel):
    id:         int
    name:       str
    industry:   Optional[str]
    currency:   str
    is_active:  bool
    created_at: datetime

    class Config:
        from_attributes = True

class BusinessMemberAdd(BaseModel):
    user_id: int
    role:    UserRole = UserRole.employee

class BusinessMemberOut(BaseModel):
    id:          int
    user_id:     int
    business_id: int
    role:        UserRole
    user:        Optional["UserOut"] = None

    class Config:
        from_attributes = True


# ── Users ─────────────────────────────────────────────────────────────────────
class UserCreate(BaseModel):
    email:       EmailStr
    full_name:   str = Field(..., min_length=2, max_length=200)
    password:    str = Field(..., min_length=8)
    role:        UserRole = UserRole.employee
    department:  Optional[str] = None

class UserUpdate(BaseModel):
    full_name:  Optional[str]      = None
    role:       Optional[UserRole] = None
    department: Optional[str]      = None
    is_active:  Optional[bool]     = None

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
    user_id:      Optional[int] = None   # admin resetting another user's password
    new_password: str = Field(..., min_length=8)
    current_password: Optional[str] = None  # required when changing own password


# ── Sales ─────────────────────────────────────────────────────────────────────
class SaleCreate(BaseModel):
    date:       date
    sku:        Optional[str] = None        # inventory SKU if linked
    product:    str   = Field(..., min_length=1, max_length=200)
    unit_price: Optional[float] = Field(None, gt=0)
    unit_cost:  Optional[float] = Field(None, ge=0)
    amount:     float = Field(..., gt=0)    # total revenue (unit_price × units)
    units:      int   = Field(..., gt=0)
    rep:        Optional[str] = None
    notes:      Optional[str] = None

class SaleOut(SaleCreate):
    id:            int
    month:         str
    business_id:   int
    created_by_id: Optional[int]
    created_at:    datetime

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
    business_id:   int
    created_by_id: Optional[int]
    created_at:    datetime

    class Config:
        from_attributes = True


# ── Inventory ─────────────────────────────────────────────────────────────────
class InventoryCreate(BaseModel):
    sku:       str   = Field(..., min_length=1, max_length=50)
    name:      str   = Field(..., min_length=1, max_length=200)
    stock:     int   = Field(0,   ge=0)
    reorder:   int   = Field(50,  ge=0)
    unit_cost: float = Field(0.0, ge=0)

class InventoryOut(InventoryCreate):
    id:          int
    business_id: int
    status:      str
    updated_at:  datetime

    class Config:
        from_attributes = True

class InventoryPriceUpdate(BaseModel):
    unit_cost:  float = Field(..., ge=0)
    reorder:    Optional[int]   = Field(None, ge=0)
    name:       Optional[str]   = None

class BulkPriceItem(BaseModel):
    sku:       str
    unit_cost: float = Field(..., ge=0)

class BulkPriceUpdate(BaseModel):
    items: list[BulkPriceItem]

class StockMovement(BaseModel):
    movement_type: str = Field(..., description="add | remove | adjust")
    qty:           int = Field(..., gt=0)
    reason:        Optional[str]   = None
    received_by:   Optional[str]   = None
    new_unit_cost: Optional[float] = None   # optionally update unit cost when receiving stock

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


# ── Cash Balances ─────────────────────────────────────────────────────────────
class CashBalanceCreate(BaseModel):
    date:            date
    opening_balance: float = Field(..., ge=0)
    closing_balance: float = Field(..., ge=0)
    bank_balance:    Optional[float] = Field(None, ge=0)
    notes:           Optional[str] = None

class CashBalanceOut(CashBalanceCreate):
    id:             int
    business_id:    int
    recorded_by_id: Optional[int]
    created_at:     datetime
    updated_at:     datetime

    class Config:
        from_attributes = True

class CashBalanceUpdate(BaseModel):
    opening_balance: Optional[float] = Field(None, ge=0)
    closing_balance: Optional[float] = Field(None, ge=0)
    bank_balance:    Optional[float] = Field(None, ge=0)
    notes:           Optional[str]   = None


# ── Activity Log ──────────────────────────────────────────────────────────────
class ActivityLogOut(BaseModel):
    id:          int
    business_id: Optional[int]
    user_id:     Optional[int]
    action:      str
    detail:      Optional[str]
    created_at:  datetime

    class Config:
        from_attributes = True


# ── Summary ───────────────────────────────────────────────────────────────────
class SummaryOut(BaseModel):
    total_revenue:         float
    total_cogs:            float
    gross_profit:          float
    gross_margin:          float
    total_expenses:        float
    net_profit:            float
    profit_margin:         float
    inventory_value:       float
    low_stock_count:       int
    out_of_stock_count:    int
    total_sales_entries:   int
    total_expense_entries: int


# Fix forward refs
Token.model_rebuild()
BusinessMemberOut.model_rebuild()
