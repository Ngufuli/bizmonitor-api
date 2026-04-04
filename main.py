"""
main.py — BizMonitor API v3
Multi-business + Admin Panel + Activity Log
"""

from fastapi import FastAPI, HTTPException, Depends, status, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta
from typing import Optional

import models, schemas, crud
from database import engine, get_db
from auth import (
    authenticate_user, create_access_token, get_current_user,
    verify_password, require_employee, require_manager, require_admin,
)
from config import get_settings

settings = get_settings()
models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.APP_NAME,
    version="3.0.0",
    description="BizMonitor — Multi-business, JWT auth, Admin panel",
)

# Parse allowed origins — handle wildcard and trim whitespace
_raw_origins = settings.ALLOWED_ORIGINS.strip()
if _raw_origins == "*":
    _allow_origins = ["*"]
else:
    _allow_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=True if _allow_origins != ["*"] else False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Business Access Helper ────────────────────────────────────────────────────
def get_business_or_403(business_id: int, current_user: models.User, db: Session):
    """Raises 403 if user has no access to this business."""
    role = crud.get_user_role_in_business(db, current_user.id, business_id)
    if not role:
        raise HTTPException(status_code=403, detail="You are not a member of this business")
    return role

def require_business_manager(business_id: int, current_user: models.User, db: Session):
    role = get_business_or_403(business_id, current_user, db)
    if role == "employee":
        raise HTTPException(status_code=403, detail="Managers and above only")
    return role


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/", tags=["Health"])
def root():
    return {"status": "ok", "app": settings.APP_NAME, "version": "3.0.0"}

@app.get("/health", tags=["Health"])
def health(db: Session = Depends(get_db)):
    try:
        db.execute(models.User.__table__.select().limit(1))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# ── Auth ──────────────────────────────────────────────────────────────────────
@app.post("/auth/login", response_model=schemas.Token, tags=["Auth"])
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = authenticate_user(db, form.username, form.password)
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect email or password", headers={"WWW-Authenticate": "Bearer"})
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")
    token = create_access_token(data={"sub": str(user.id)}, expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    return {"access_token": token, "token_type": "bearer", "user": user}

@app.get("/auth/me", response_model=schemas.UserOut, tags=["Auth"])
def me(current_user: models.User = Depends(get_current_user)):
    return current_user

@app.post("/auth/change-password", tags=["Auth"])
def change_password(data: schemas.ChangePassword, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not data.current_password:
        raise HTTPException(status_code=400, detail="Current password required")
    if not verify_password(data.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    crud.change_password(db, current_user, data.new_password)
    return {"message": "Password changed successfully"}


# ── First-Run Setup ───────────────────────────────────────────────────────────
@app.post("/setup", response_model=schemas.UserOut, status_code=201, tags=["Setup"])
def first_run_setup(user: schemas.UserCreate, db: Session = Depends(get_db)):
    if crud.count_users(db) > 0:
        raise HTTPException(status_code=403, detail="Setup already complete")
    user.role = "admin"
    return crud.create_user(db, user)


# ── Businesses ────────────────────────────────────────────────────────────────
@app.get("/businesses", response_model=list[schemas.BusinessOut], tags=["Businesses"])
def list_my_businesses(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Returns all businesses the logged-in user has access to."""
    return crud.get_businesses_for_user(db, current_user.id)

@app.post("/businesses", response_model=schemas.BusinessOut, status_code=201, tags=["Businesses"])
def create_business(data: schemas.BusinessCreate, current_user: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    return crud.create_business(db, data, creator_id=current_user.id)

@app.get("/businesses/all", response_model=list[schemas.BusinessOut], tags=["Businesses"])
def list_all_businesses(_: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    return crud.get_all_businesses(db)

@app.patch("/businesses/{business_id}", response_model=schemas.BusinessOut, tags=["Businesses"])
def update_business(business_id: int, data: schemas.BusinessUpdate, current_user: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    biz = db.query(models.Business).filter(models.Business.id == business_id).first()
    if not biz:
        raise HTTPException(status_code=404, detail="Business not found")
    if data.name      is not None: biz.name      = data.name
    if data.industry  is not None: biz.industry  = data.industry
    if data.currency  is not None: biz.currency  = data.currency
    if data.is_active is not None: biz.is_active = data.is_active
    db.commit()
    db.refresh(biz)
    return biz

@app.get("/businesses/{business_id}/members", response_model=list[schemas.BusinessMemberOut], tags=["Businesses"])
def get_members(business_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    get_business_or_403(business_id, current_user, db)
    return crud.get_members(db, business_id)

@app.post("/businesses/{business_id}/members", tags=["Businesses"])
def add_member(business_id: int, data: schemas.BusinessMemberAdd, current_user: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    return crud.add_member(db, business_id, data, added_by_id=current_user.id)

@app.delete("/businesses/{business_id}/members/{user_id}", tags=["Businesses"])
def remove_member(business_id: int, user_id: int, _: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    ok = crud.remove_member(db, business_id, user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Member not found")
    return {"removed": user_id}


# ── Admin — Users ─────────────────────────────────────────────────────────────
@app.get("/admin/users", response_model=list[schemas.UserOut], tags=["Admin"])
def list_users(_: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    return crud.get_users(db)

@app.post("/admin/users", response_model=schemas.UserOut, status_code=201, tags=["Admin"])
def create_user(user: schemas.UserCreate, current_user: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    from auth import get_user_by_email
    if get_user_by_email(db, user.email):
        raise HTTPException(status_code=409, detail="Email already registered")
    return crud.create_user(db, user, created_by_id=current_user.id)

@app.patch("/admin/users/{user_id}", response_model=schemas.UserOut, tags=["Admin"])
def update_user(user_id: int, data: schemas.UserUpdate, current_user: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    user = crud.update_user(db, user_id, data, updated_by_id=current_user.id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@app.post("/admin/users/{user_id}/reset-password", tags=["Admin"])
def admin_reset_password(user_id: int, data: schemas.ChangePassword, current_user: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    ok = crud.reset_password(db, user_id, data.new_password, reset_by_id=current_user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": f"Password reset for user {user_id}"}


# ── Admin — Activity Log ──────────────────────────────────────────────────────
@app.get("/admin/activity", response_model=list[schemas.ActivityLogOut], tags=["Admin"])
def get_global_activity(_: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    return crud.get_activity_log(db, limit=200)

@app.get("/businesses/{business_id}/activity", response_model=list[schemas.ActivityLogOut], tags=["Admin"])
def get_business_activity(business_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_business_manager(business_id, current_user, db)
    return crud.get_activity_log(db, business_id=business_id, limit=100)


# ── Sales (business-scoped) ───────────────────────────────────────────────────
@app.get("/businesses/{business_id}/sales", response_model=list[schemas.SaleOut], tags=["Sales"])
def get_sales(business_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    get_business_or_403(business_id, current_user, db)
    return crud.get_sales(db, business_id)

@app.post("/businesses/{business_id}/sales", response_model=schemas.SaleOut, status_code=201, tags=["Sales"])
def create_sale(business_id: int, sale: schemas.SaleCreate, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    get_business_or_403(business_id, current_user, db)
    return crud.create_sale(db, sale, business_id=business_id, created_by_id=current_user.id)

@app.delete("/businesses/{business_id}/sales/{sale_id}", tags=["Sales"])
def delete_sale(business_id: int, sale_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_business_manager(business_id, current_user, db)
    if not crud.delete_sale(db, sale_id, business_id):
        raise HTTPException(status_code=404, detail="Sale not found")
    return {"deleted": sale_id}


# ── Expenses (business-scoped) ────────────────────────────────────────────────
@app.get("/businesses/{business_id}/expenses", response_model=list[schemas.ExpenseOut], tags=["Expenses"])
def get_expenses(business_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    get_business_or_403(business_id, current_user, db)
    return crud.get_expenses(db, business_id)

@app.post("/businesses/{business_id}/expenses", response_model=schemas.ExpenseOut, status_code=201, tags=["Expenses"])
def create_expense(business_id: int, expense: schemas.ExpenseCreate, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    get_business_or_403(business_id, current_user, db)
    return crud.create_expense(db, expense, business_id=business_id, created_by_id=current_user.id)

@app.delete("/businesses/{business_id}/expenses/{expense_id}", tags=["Expenses"])
def delete_expense(business_id: int, expense_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_business_manager(business_id, current_user, db)
    if not crud.delete_expense(db, expense_id, business_id):
        raise HTTPException(status_code=404, detail="Expense not found")
    return {"deleted": expense_id}


# ── Inventory (business-scoped) ───────────────────────────────────────────────
@app.get("/businesses/{business_id}/inventory", response_model=list[schemas.InventoryOut], tags=["Inventory"])
def get_inventory(business_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    get_business_or_403(business_id, current_user, db)
    return crud.get_inventory(db, business_id)

@app.post("/businesses/{business_id}/inventory", response_model=schemas.InventoryOut, status_code=201, tags=["Inventory"])
def create_product(business_id: int, product: schemas.InventoryCreate, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_business_manager(business_id, current_user, db)
    return crud.create_product(db, product, business_id=business_id)

@app.patch("/businesses/{business_id}/inventory/{sku}/stock", response_model=schemas.InventoryOut, tags=["Inventory"])
def update_stock(business_id: int, sku: str, movement: schemas.StockMovement, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    get_business_or_403(business_id, current_user, db)
    item = crud.update_stock(db, sku, business_id, movement, created_by_id=current_user.id)
    if not item:
        raise HTTPException(status_code=404, detail=f"SKU '{sku}' not found")
    return item

@app.delete("/businesses/{business_id}/inventory/{sku}", tags=["Inventory"])
def delete_product(business_id: int, sku: str, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_business_manager(business_id, current_user, db)
    if not crud.delete_product(db, sku, business_id):
        raise HTTPException(status_code=404, detail="Product not found")
    return {"deleted": sku}


@app.get("/businesses/{business_id}/stock-movements", response_model=list[schemas.StockMovementOut], tags=["Inventory"])
def get_stock_movements(business_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    get_business_or_403(business_id, current_user, db)
    return crud.get_stock_movements(db, business_id)


# ── Cash Balances (business-scoped) ──────────────────────────────────────────
@app.get("/businesses/{business_id}/cash", response_model=list[schemas.CashBalanceOut], tags=["Cash"])
def get_cash_balances(business_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    get_business_or_403(business_id, current_user, db)
    return crud.get_cash_balances(db, business_id)

@app.post("/businesses/{business_id}/cash", response_model=schemas.CashBalanceOut, status_code=201, tags=["Cash"])
def record_cash_balance(business_id: int, data: schemas.CashBalanceCreate, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    get_business_or_403(business_id, current_user, db)
    return crud.upsert_cash_balance(db, data, business_id=business_id, recorded_by_id=current_user.id)

@app.delete("/businesses/{business_id}/cash/{balance_id}", tags=["Cash"])
def delete_cash_balance(business_id: int, balance_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_business_manager(business_id, current_user, db)
    if not crud.delete_cash_balance(db, balance_id, business_id):
        raise HTTPException(status_code=404, detail="Balance record not found")
    return {"deleted": balance_id}


# ── Summary (business-scoped) ─────────────────────────────────────────────────
@app.get("/businesses/{business_id}/summary", response_model=schemas.SummaryOut, tags=["Summary"])
def get_summary(business_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    get_business_or_403(business_id, current_user, db)   # employees allowed
    return crud.get_summary(db, business_id)
