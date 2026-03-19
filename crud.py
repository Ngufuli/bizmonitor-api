"""
crud.py — Database read/write operations
"""

from sqlalchemy.orm import Session
from sqlalchemy import func
import models, schemas
from auth import hash_password
from datetime import date

MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

def month_str(d: date) -> str:
    return MONTHS[d.month - 1]

def compute_status(stock: int, reorder: int) -> str:
    if stock == 0:   return "out"
    if stock < reorder: return "low"
    return "ok"


# ── Users ─────────────────────────────────────────────────────────────────────
def get_users(db: Session):
    return db.query(models.User).order_by(models.User.full_name).all()

def get_user(db: Session, user_id: int):
    return db.query(models.User).filter(models.User.id == user_id).first()

def create_user(db: Session, user: schemas.UserCreate) -> models.User:
    db_user = models.User(
        email           = user.email.lower(),
        full_name       = user.full_name,
        hashed_password = hash_password(user.password),
        role            = user.role,
        department      = user.department,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def update_user(db: Session, user_id: int, data: schemas.UserUpdate) -> models.User:
    user = get_user(db, user_id)
    if not user:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user

def change_password(db: Session, user: models.User, new_password: str):
    user.hashed_password = hash_password(new_password)
    db.commit()

def count_users(db: Session) -> int:
    return db.query(func.count(models.User.id)).scalar()


# ── Sales ─────────────────────────────────────────────────────────────────────
def get_sales(db: Session, skip: int = 0, limit: int = 500):
    return db.query(models.Sale).order_by(models.Sale.date.desc()).offset(skip).limit(limit).all()

def create_sale(db: Session, sale: schemas.SaleCreate, created_by_id: int = None):
    db_sale = models.Sale(
        date          = sale.date,
        month         = month_str(sale.date),
        product       = sale.product,
        amount        = sale.amount,
        units         = sale.units,
        rep           = sale.rep,
        notes         = sale.notes,
        created_by_id = created_by_id,
    )
    db.add(db_sale)
    db.commit()
    db.refresh(db_sale)
    return db_sale

def delete_sale(db: Session, sale_id: int) -> bool:
    obj = db.query(models.Sale).filter(models.Sale.id == sale_id).first()
    if not obj: return False
    db.delete(obj)
    db.commit()
    return True


# ── Expenses ──────────────────────────────────────────────────────────────────
def get_expenses(db: Session, skip: int = 0, limit: int = 500):
    return db.query(models.Expense).order_by(models.Expense.date.desc()).offset(skip).limit(limit).all()

def create_expense(db: Session, expense: schemas.ExpenseCreate, created_by_id: int = None):
    db_exp = models.Expense(
        date          = expense.date,
        month         = month_str(expense.date),
        category      = expense.category,
        amount        = expense.amount,
        vendor        = expense.vendor,
        description   = expense.description,
        submitted_by  = expense.submitted_by,
        created_by_id = created_by_id,
    )
    db.add(db_exp)
    db.commit()
    db.refresh(db_exp)
    return db_exp

def delete_expense(db: Session, expense_id: int) -> bool:
    obj = db.query(models.Expense).filter(models.Expense.id == expense_id).first()
    if not obj: return False
    db.delete(obj)
    db.commit()
    return True


# ── Inventory ─────────────────────────────────────────────────────────────────
def get_inventory(db: Session):
    return db.query(models.InventoryItem).order_by(models.InventoryItem.sku).all()

def create_product(db: Session, product: schemas.InventoryCreate):
    db_item = models.InventoryItem(
        sku       = product.sku.upper(),
        name      = product.name,
        stock     = product.stock,
        reorder   = product.reorder,
        unit_cost = product.unit_cost,
        status    = compute_status(product.stock, product.reorder),
    )
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item

def update_stock(db: Session, sku: str, movement: schemas.StockMovement, created_by_id: int = None):
    item = db.query(models.InventoryItem).filter(models.InventoryItem.sku == sku.upper()).first()
    if not item: return None

    stock_before = item.stock
    delta        = movement.qty if movement.movement_type in ("add","adjust") else -movement.qty
    stock_after  = max(0, item.stock + delta)

    log = models.StockMovementLog(
        sku           = sku.upper(),
        movement_type = movement.movement_type,
        qty           = movement.qty,
        stock_before  = stock_before,
        stock_after   = stock_after,
        reason        = movement.reason,
        received_by   = movement.received_by,
        created_by_id = created_by_id,
    )
    db.add(log)
    item.stock  = stock_after
    item.status = compute_status(stock_after, item.reorder)
    db.commit()
    db.refresh(item)
    return item

def get_stock_movements(db: Session, sku: str = None, limit: int = 100):
    q = db.query(models.StockMovementLog).order_by(models.StockMovementLog.created_at.desc())
    if sku:
        q = q.filter(models.StockMovementLog.sku == sku.upper())
    return q.limit(limit).all()

def delete_product(db: Session, sku: str) -> bool:
    obj = db.query(models.InventoryItem).filter(models.InventoryItem.sku == sku.upper()).first()
    if not obj: return False
    db.delete(obj)
    db.commit()
    return True


# ── Summary ───────────────────────────────────────────────────────────────────
def get_summary(db: Session) -> dict:
    total_revenue  = db.query(func.sum(models.Sale.amount)).scalar()    or 0
    total_expenses = db.query(func.sum(models.Expense.amount)).scalar() or 0
    inventory      = get_inventory(db)
    inv_value      = sum(i.stock * i.unit_cost for i in inventory)
    net            = total_revenue - total_expenses

    return {
        "total_revenue":         round(total_revenue,  2),
        "total_expenses":        round(total_expenses, 2),
        "net_profit":            round(net,            2),
        "profit_margin":         round(net / total_revenue * 100, 1) if total_revenue else 0,
        "inventory_value":       round(inv_value, 2),
        "low_stock_count":       sum(1 for i in inventory if i.status == "low"),
        "out_of_stock_count":    sum(1 for i in inventory if i.status == "out"),
        "total_sales_entries":   db.query(func.count(models.Sale.id)).scalar(),
        "total_expense_entries": db.query(func.count(models.Expense.id)).scalar(),
    }
