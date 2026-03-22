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
    if stock == 0:        return "out"
    if stock < reorder:   return "low"
    return "ok"

def log_activity(db: Session, action: str, detail: str, user_id: int = None, business_id: int = None):
    entry = models.ActivityLog(
        action=action, detail=detail,
        user_id=user_id, business_id=business_id
    )
    db.add(entry)
    # don't commit here — caller commits


# ── Businesses ────────────────────────────────────────────────────────────────
def get_businesses_for_user(db: Session, user_id: int):
    """Returns all businesses a user is a member of."""
    memberships = db.query(models.BusinessMember).filter(
        models.BusinessMember.user_id == user_id
    ).all()
    business_ids = [m.business_id for m in memberships]

    # Admins (global) can also see all businesses
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user and user.role == "admin":
        return db.query(models.Business).filter(models.Business.is_active == True).all()

    return db.query(models.Business).filter(
        models.Business.id.in_(business_ids),
        models.Business.is_active == True
    ).all()

def get_all_businesses(db: Session):
    return db.query(models.Business).order_by(models.Business.name).all()

def create_business(db: Session, data: schemas.BusinessCreate, creator_id: int):
    biz = models.Business(name=data.name, industry=data.industry, currency=data.currency)
    db.add(biz)
    db.flush()  # get ID without full commit

    # Auto-add creator as admin member
    member = models.BusinessMember(business_id=biz.id, user_id=creator_id, role="admin")
    db.add(member)

    log_activity(db, "created_business", f"Created business: {data.name}", user_id=creator_id, business_id=biz.id)
    db.commit()
    db.refresh(biz)
    return biz

def get_user_role_in_business(db: Session, user_id: int, business_id: int) -> str:
    """Returns the user's role within a specific business, or None if not a member."""
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
    return db.query(models.BusinessMember).filter(
        models.BusinessMember.business_id == business_id
    ).all()

def remove_member(db: Session, business_id: int, user_id: int) -> bool:
    member = db.query(models.BusinessMember).filter(
        models.BusinessMember.business_id == business_id,
        models.BusinessMember.user_id == user_id
    ).first()
    if not member:
        return False
    db.delete(member)
    db.commit()
    return True


# ── Users ─────────────────────────────────────────────────────────────────────
def get_users(db: Session):
    return db.query(models.User).order_by(models.User.full_name).all()

def get_user(db: Session, user_id: int):
    return db.query(models.User).filter(models.User.id == user_id).first()

def create_user(db: Session, user: schemas.UserCreate, created_by_id: int = None) -> models.User:
    db_user = models.User(
        email=user.email.lower(), full_name=user.full_name,
        hashed_password=hash_password(user.password),
        role=user.role, department=user.department,
    )
    db.add(db_user)
    db.flush()
    log_activity(db, "created_user", f"Created user: {user.email} [{user.role}]", user_id=created_by_id)
    db.commit()
    db.refresh(db_user)
    return db_user

def update_user(db: Session, user_id: int, data: schemas.UserUpdate, updated_by_id: int = None) -> models.User:
    user = get_user(db, user_id)
    if not user:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    log_activity(db, "updated_user", f"Updated user {user_id}: {data.model_dump(exclude_unset=True)}", user_id=updated_by_id)
    db.commit()
    db.refresh(user)
    return user

def reset_password(db: Session, user_id: int, new_password: str, reset_by_id: int = None):
    user = get_user(db, user_id)
    if not user:
        return False
    user.hashed_password = hash_password(new_password)
    log_activity(db, "reset_password", f"Password reset for user {user_id}", user_id=reset_by_id)
    db.commit()
    return True

def change_password(db: Session, user: models.User, new_password: str):
    user.hashed_password = hash_password(new_password)
    log_activity(db, "changed_password", f"User {user.id} changed their password", user_id=user.id)
    db.commit()

def count_users(db: Session) -> int:
    return db.query(func.count(models.User.id)).scalar()


# ── Sales ─────────────────────────────────────────────────────────────────────
def get_sales(db: Session, business_id: int, skip: int = 0, limit: int = 500):
    return db.query(models.Sale).filter(
        models.Sale.business_id == business_id
    ).order_by(models.Sale.date.desc()).offset(skip).limit(limit).all()

def create_sale(db: Session, sale: schemas.SaleCreate, business_id: int, created_by_id: int = None):
    db_sale = models.Sale(
        business_id=business_id, date=sale.date, month=month_str(sale.date),
        product=sale.product, amount=sale.amount, units=sale.units,
        rep=sale.rep, notes=sale.notes, created_by_id=created_by_id,
    )
    db.add(db_sale)
    log_activity(db, "created_sale", f"Logged sale: {sale.product} ${sale.amount}", user_id=created_by_id, business_id=business_id)
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
    log_activity(db, "created_expense", f"Recorded expense: {expense.vendor} ${expense.amount}", user_id=created_by_id, business_id=business_id)
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
    db_item = models.InventoryItem(
        business_id=business_id, sku=product.sku.upper(), name=product.name,
        stock=product.stock, reorder=product.reorder, unit_cost=product.unit_cost,
        status=compute_status(product.stock, product.reorder),
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
    delta        = movement.qty if movement.movement_type in ("add","adjust") else -movement.qty
    stock_after  = max(0, item.stock + delta)

    log = models.StockMovementLog(
        business_id=business_id, sku=sku.upper(), movement_type=movement.movement_type,
        qty=movement.qty, stock_before=stock_before, stock_after=stock_after,
        reason=movement.reason, received_by=movement.received_by, created_by_id=created_by_id,
    )
    db.add(log)
    log_activity(db, "updated_stock", f"Stock {sku}: {stock_before}→{stock_after} ({movement.movement_type})", user_id=created_by_id, business_id=business_id)

    item.stock  = stock_after
    item.status = compute_status(stock_after, item.reorder)
    db.commit()
    db.refresh(item)
    return item

def delete_product(db: Session, sku: str, business_id: int) -> bool:
    obj = db.query(models.InventoryItem).filter(
        models.InventoryItem.sku == sku.upper(),
        models.InventoryItem.business_id == business_id,
    ).first()
    if not obj: return False
    db.delete(obj)
    db.commit()
    return True


# ── Activity Log ──────────────────────────────────────────────────────────────
def get_activity_log(db: Session, business_id: int = None, limit: int = 100):
    q = db.query(models.ActivityLog).order_by(models.ActivityLog.created_at.desc())
    if business_id:
        q = q.filter(models.ActivityLog.business_id == business_id)
    return q.limit(limit).all()


# ── Summary ───────────────────────────────────────────────────────────────────
def get_summary(db: Session, business_id: int) -> dict:
    total_revenue  = db.query(func.sum(models.Sale.amount)).filter(models.Sale.business_id == business_id).scalar() or 0
    total_expenses = db.query(func.sum(models.Expense.amount)).filter(models.Expense.business_id == business_id).scalar() or 0
    inventory      = get_inventory(db, business_id)
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
        "total_sales_entries":   db.query(func.count(models.Sale.id)).filter(models.Sale.business_id == business_id).scalar(),
        "total_expense_entries": db.query(func.count(models.Expense.id)).filter(models.Expense.business_id == business_id).scalar(),
    }
