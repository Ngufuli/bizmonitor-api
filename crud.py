"""
crud.py — All database operations, business-scoped
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
    if stock == 0:      return "out"
    if stock < reorder: return "low"
    return "ok"

def log_activity(db: Session, action: str, detail: str, user_id: int = None, business_id: int = None):
    entry = models.ActivityLog(action=action, detail=detail, user_id=user_id, business_id=business_id)
    db.add(entry)


# ── Businesses ────────────────────────────────────────────────────────────────
def get_businesses_for_user(db: Session, user_id: int):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user and user.role == "admin":
        return db.query(models.Business).filter(models.Business.is_active == True).all()
    memberships = db.query(models.BusinessMember).filter(models.BusinessMember.user_id == user_id).all()
    business_ids = [m.business_id for m in memberships]
    return db.query(models.Business).filter(
        models.Business.id.in_(business_ids),
        models.Business.is_active == True
    ).all()

def get_all_businesses(db: Session):
    return db.query(models.Business).order_by(models.Business.name).all()

def create_business(db: Session, data: schemas.BusinessCreate, creator_id: int):
    biz = models.Business(name=data.name, industry=data.industry, currency=data.currency)
    db.add(biz)
    db.flush()
    member = models.BusinessMember(business_id=biz.id, user_id=creator_id, role="admin")
    db.add(member)
    log_activity(db, "created_business", f"Created: {data.name}", user_id=creator_id, business_id=biz.id)
    db.commit()
    db.refresh(biz)
    return biz

def get_user_role_in_business(db: Session, user_id: int, business_id: int):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user and user.role == "admin":
        return "admin"
    member = db.query(models.BusinessMember).filter(
        models.BusinessMember.user_id == user_id,
        models.BusinessMember.business_id == business_id,
    ).first()
    return member.role if member else None

def add_member(db: Session, business_id: int, data: schemas.BusinessMemberAdd, added_by_id: int):
    existing = db.query(models.BusinessMember).filter(
        models.BusinessMember.business_id == business_id,
        models.BusinessMember.user_id == data.user_id
    ).first()
    if existing:
        existing.role = data.role
        db.commit()
        db.refresh(existing)
        return existing
    member = models.BusinessMember(business_id=business_id, user_id=data.user_id, role=data.role)
    db.add(member)
    log_activity(db, "added_member", f"Added user {data.user_id} as {data.role}", user_id=added_by_id, business_id=business_id)
    db.commit()
    db.refresh(member)
    return member

def get_members(db: Session, business_id: int):
    return db.query(models.BusinessMember).filter(models.BusinessMember.business_id == business_id).all()

def remove_member(db: Session, business_id: int, user_id: int) -> bool:
    member = db.query(models.BusinessMember).filter(
        models.BusinessMember.business_id == business_id,
        models.BusinessMember.user_id == user_id
    ).first()
    if not member: return False
    db.delete(member)
    db.commit()
    return True


# ── Users ─────────────────────────────────────────────────────────────────────
def get_users(db: Session):
    return db.query(models.User).order_by(models.User.full_name).all()

def get_user(db: Session, user_id: int):
    return db.query(models.User).filter(models.User.id == user_id).first()

def create_user(db: Session, user: schemas.UserCreate, created_by_id: int = None):
    db_user = models.User(
        email=user.email.lower(), full_name=user.full_name,
        hashed_password=hash_password(user.password),
        role=user.role, department=user.department,
    )
    db.add(db_user)
    db.flush()
    log_activity(db, "created_user", f"Created: {user.email} [{user.role}]", user_id=created_by_id)
    db.commit()
    db.refresh(db_user)
    return db_user

def update_user(db: Session, user_id: int, data: schemas.UserUpdate, updated_by_id: int = None):
    user = get_user(db, user_id)
    if not user: return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    log_activity(db, "updated_user", f"Updated user {user_id}", user_id=updated_by_id)
    db.commit()
    db.refresh(user)
    return user

def reset_password(db: Session, user_id: int, new_password: str, reset_by_id: int = None):
    user = get_user(db, user_id)
    if not user: return False
    user.hashed_password = hash_password(new_password)
    log_activity(db, "reset_password", f"Password reset for user {user_id}", user_id=reset_by_id)
    db.commit()
    return True

def change_password(db: Session, user: models.User, new_password: str):
    user.hashed_password = hash_password(new_password)
    db.commit()

def count_users(db: Session) -> int:
    return db.query(func.count(models.User.id)).scalar()


# ── Sales ─────────────────────────────────────────────────────────────────────
def get_sales(db: Session, business_id: int, skip: int = 0, limit: int = 500):
    return db.query(models.Sale).filter(
        models.Sale.business_id == business_id
    ).order_by(models.Sale.date.desc()).offset(skip).limit(limit).all()

def create_sale(db: Session, sale: schemas.SaleCreate, business_id: int, created_by_id: int = None):
    # Safely get unit_cost — only if sku provided AND columns exist in DB
    unit_cost = 0.0
    try:
        if sale.sku:
            item = db.query(models.InventoryItem).filter(
                models.InventoryItem.sku == sale.sku.upper(),
                models.InventoryItem.business_id == business_id,
            ).first()
            if item:
                unit_cost = item.unit_cost or 0.0
                stock_before = item.stock
                stock_after  = max(0, item.stock - sale.units)
                movement = models.StockMovementLog(
                    business_id=business_id, sku=item.sku,
                    movement_type="remove", qty=sale.units,
                    stock_before=stock_before, stock_after=stock_after,
                    reason=f"Sale on {sale.date}", received_by=sale.rep,
                    created_by_id=created_by_id,
                )
                db.add(movement)
                item.stock  = stock_after
                item.status = compute_status(stock_after, item.reorder)
    except Exception:
        unit_cost = 0.0

    db_sale = models.Sale(
        business_id   = business_id,
        date          = sale.date,
        month         = month_str(sale.date),
        product       = sale.product,
        amount        = sale.amount,
        units         = sale.units,
        rep           = sale.rep,
        notes         = sale.notes,
        created_by_id = created_by_id,
    )
    # Only set new columns if they exist in the DB (safe assignment)
    try:
        db_sale.sku        = sale.sku.upper() if sale.sku else None
        db_sale.unit_price = sale.unit_price
        db_sale.unit_cost  = unit_cost
    except Exception:
        pass

    db.add(db_sale)
    log_activity(db, "created_sale", f"Sold {sale.units}x {sale.product} @ {sale.amount}", user_id=created_by_id, business_id=business_id)
    db.commit()
    db.refresh(db_sale)
    return db_sale

def delete_sale(db: Session, sale_id: int, business_id: int) -> bool:
    obj = db.query(models.Sale).filter(models.Sale.id == sale_id, models.Sale.business_id == business_id).first()
    if not obj: return False
    db.delete(obj)
    db.commit()
    return True


# ── Expenses ──────────────────────────────────────────────────────────────────
def get_expenses(db: Session, business_id: int, skip: int = 0, limit: int = 500):
    return db.query(models.Expense).filter(
        models.Expense.business_id == business_id
    ).order_by(models.Expense.date.desc()).offset(skip).limit(limit).all()

def create_expense(db: Session, expense: schemas.ExpenseCreate, business_id: int, created_by_id: int = None):
    db_exp = models.Expense(
        business_id=business_id, date=expense.date, month=month_str(expense.date),
        category=expense.category, amount=expense.amount, vendor=expense.vendor,
        description=expense.description, submitted_by=expense.submitted_by,
        created_by_id=created_by_id,
    )
    db.add(db_exp)
    log_activity(db, "created_expense", f"Expense: {expense.vendor} ${expense.amount}", user_id=created_by_id, business_id=business_id)
    db.commit()
    db.refresh(db_exp)
    return db_exp

def delete_expense(db: Session, expense_id: int, business_id: int) -> bool:
    obj = db.query(models.Expense).filter(models.Expense.id == expense_id, models.Expense.business_id == business_id).first()
    if not obj: return False
    db.delete(obj)
    db.commit()
    return True


# ── Inventory ─────────────────────────────────────────────────────────────────
def get_inventory(db: Session, business_id: int):
    return db.query(models.InventoryItem).filter(
        models.InventoryItem.business_id == business_id
    ).order_by(models.InventoryItem.sku).all()

def create_product(db: Session, product: schemas.InventoryCreate, business_id: int):
    # Check for duplicate SKU in this business
    existing = db.query(models.InventoryItem).filter(
        models.InventoryItem.sku == product.sku.upper(),
        models.InventoryItem.business_id == business_id,
    ).first()
    if existing:
        # Update instead of duplicate
        existing.name      = product.name
        existing.stock     = product.stock
        existing.reorder   = product.reorder
        existing.unit_cost = product.unit_cost
        existing.status    = compute_status(product.stock, product.reorder)
        db.commit()
        db.refresh(existing)
        return existing

    db_item = models.InventoryItem(
        business_id = business_id,
        sku         = product.sku.upper(),
        name        = product.name,
        stock       = product.stock,
        reorder     = product.reorder,
        unit_cost   = product.unit_cost,
        status      = compute_status(product.stock, product.reorder),
    )
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item

def update_stock(db: Session, sku: str, business_id: int, movement: schemas.StockMovement, created_by_id: int = None):
    item = db.query(models.InventoryItem).filter(
        models.InventoryItem.sku == sku.upper(),
        models.InventoryItem.business_id == business_id,
    ).first()
    if not item: return None

    stock_before = item.stock
    delta        = movement.qty if movement.movement_type in ("add", "adjust") else -movement.qty
    stock_after  = max(0, item.stock + delta)

    log = models.StockMovementLog(
        business_id=business_id, sku=sku.upper(), movement_type=movement.movement_type,
        qty=movement.qty, stock_before=stock_before, stock_after=stock_after,
        reason=movement.reason, received_by=movement.received_by, created_by_id=created_by_id,
    )
    db.add(log)

    detail = f"Stock {sku}: {stock_before}→{stock_after} ({movement.movement_type})"
    if movement.new_unit_cost is not None:
        item.unit_cost = movement.new_unit_cost
        detail += f" · cost updated to {movement.new_unit_cost}"

    log_activity(db, "updated_stock", detail, user_id=created_by_id, business_id=business_id)

    item.stock  = stock_after
    item.status = compute_status(stock_after, item.reorder)
    db.commit()
    db.refresh(item)
    return item

def get_stock_movements(db: Session, business_id: int, limit: int = 500):
    return db.query(models.StockMovementLog).filter(
        models.StockMovementLog.business_id == business_id
    ).order_by(models.StockMovementLog.created_at.desc()).limit(limit).all()

def delete_product(db: Session, sku: str, business_id: int) -> bool:
    obj = db.query(models.InventoryItem).filter(
        models.InventoryItem.sku == sku.upper(),
        models.InventoryItem.business_id == business_id,
    ).first()
    if not obj: return False
    db.delete(obj)
    db.commit()
    return True


# ── Cash Balances ─────────────────────────────────────────────────────────────
def get_cash_balances(db: Session, business_id: int, limit: int = 90):
    return db.query(models.CashBalance).filter(
        models.CashBalance.business_id == business_id
    ).order_by(models.CashBalance.date.desc()).limit(limit).all()

def get_cash_balance_by_date(db: Session, business_id: int, d):
    return db.query(models.CashBalance).filter(
        models.CashBalance.business_id == business_id,
        models.CashBalance.date == d,
    ).first()

def upsert_cash_balance(db: Session, data: schemas.CashBalanceCreate, business_id: int, recorded_by_id: int = None):
    existing = get_cash_balance_by_date(db, business_id, data.date)
    if existing:
        existing.opening_balance = data.opening_balance
        existing.closing_balance = data.closing_balance
        existing.notes           = data.notes
        db.commit()
        db.refresh(existing)
        return existing
    record = models.CashBalance(
        business_id=business_id, date=data.date,
        opening_balance=data.opening_balance, closing_balance=data.closing_balance,
        notes=data.notes, recorded_by_id=recorded_by_id,
    )
    db.add(record)
    log_activity(db, "recorded_cash_balance", f"Balance for {data.date}", user_id=recorded_by_id, business_id=business_id)
    db.commit()
    db.refresh(record)
    return record

def delete_cash_balance(db: Session, balance_id: int, business_id: int) -> bool:
    obj = db.query(models.CashBalance).filter(
        models.CashBalance.id == balance_id,
        models.CashBalance.business_id == business_id,
    ).first()
    if not obj: return False
    db.delete(obj)
    db.commit()
    return True


# ── Activity Log ──────────────────────────────────────────────────────────────
def get_activity_log(db: Session, business_id: int = None, limit: int = 200):
    q = db.query(models.ActivityLog).order_by(models.ActivityLog.created_at.desc())
    if business_id:
        q = q.filter(models.ActivityLog.business_id == business_id)
    return q.limit(limit).all()


# ── Summary ───────────────────────────────────────────────────────────────────
def get_summary(db: Session, business_id: int) -> dict:
    sales     = get_sales(db, business_id, limit=10000)
    inventory = get_inventory(db, business_id)

    total_revenue  = sum(s.amount for s in sales)
    # Safe COGS — only calculate if unit_cost column exists and has data
    total_cogs = 0.0
    try:
        total_cogs = sum((getattr(s, 'unit_cost', None) or 0) * s.units for s in sales)
    except Exception:
        total_cogs = 0.0

    gross_profit   = total_revenue - total_cogs
    total_expenses = db.query(func.sum(models.Expense.amount)).filter(
        models.Expense.business_id == business_id
    ).scalar() or 0
    net_profit = gross_profit - total_expenses
    inv_value  = sum(i.stock * i.unit_cost for i in inventory)

    return {
        "total_revenue":         round(total_revenue,  2),
        "total_cogs":            round(total_cogs,     2),
        "gross_profit":          round(gross_profit,   2),
        "gross_margin":          round(gross_profit / total_revenue * 100, 1) if total_revenue else 0,
        "total_expenses":        round(total_expenses, 2),
        "net_profit":            round(net_profit,     2),
        "profit_margin":         round(net_profit / total_revenue * 100, 1) if total_revenue else 0,
        "inventory_value":       round(inv_value, 2),
        "low_stock_count":       sum(1 for i in inventory if i.status == "low"),
        "out_of_stock_count":    sum(1 for i in inventory if i.status == "out"),
        "total_sales_entries":   len(sales),
        "total_expense_entries": db.query(func.count(models.Expense.id)).filter(
            models.Expense.business_id == business_id
        ).scalar(),
    }
