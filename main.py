"""
main.py — BizMonitor API v2
FastAPI + PostgreSQL + JWT Auth + Role-Based Access
"""

from fastapi import FastAPI, HTTPException, Depends, status
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

# Create tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="BizMonitor — production API with JWT auth and role-based access",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/", tags=["Health"])
def root():
    return {"status": "ok", "app": settings.APP_NAME, "version": settings.APP_VERSION}

@app.get("/health", tags=["Health"])
def health(db: Session = Depends(get_db)):
    try:
        db.execute(models.User.__table__.select().limit(1))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error: {str(e)}")


# ── Auth ──────────────────────────────────────────────────────────────────────
@app.post("/auth/login", response_model=schemas.Token, tags=["Auth"])
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Login with email + password. Returns a JWT token."""
    user = authenticate_user(db, form.username, form.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return {"access_token": token, "token_type": "bearer", "user": user}


@app.get("/auth/me", response_model=schemas.UserOut, tags=["Auth"])
def me(current_user: models.User = Depends(get_current_user)):
    """Returns the currently authenticated user's profile."""
    return current_user


@app.post("/auth/change-password", tags=["Auth"])
def change_password(
    data: schemas.ChangePassword,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not verify_password(data.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    crud.change_password(db, current_user, data.new_password)
    return {"message": "Password changed successfully"}


# ── Users (admin only) ────────────────────────────────────────────────────────
@app.get("/users", response_model=list[schemas.UserOut], tags=["Users"])
def list_users(
    _: models.User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    return crud.get_users(db)


@app.post("/users", response_model=schemas.UserOut, status_code=201, tags=["Users"])
def create_user(
    user: schemas.UserCreate,
    _: models.User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Admin creates a new user account."""
    from auth import get_user_by_email
    if get_user_by_email(db, user.email):
        raise HTTPException(status_code=409, detail="Email already registered")
    return crud.create_user(db, user)


@app.patch("/users/{user_id}", response_model=schemas.UserOut, tags=["Users"])
def update_user(
    user_id: int,
    data: schemas.UserUpdate,
    _: models.User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    user = crud.update_user(db, user_id, data)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# ── First-run admin setup (only works if no users exist) ─────────────────────
@app.post("/setup", response_model=schemas.UserOut, status_code=201, tags=["Setup"])
def first_run_setup(user: schemas.UserCreate, db: Session = Depends(get_db)):
    """
    Creates the first admin account.
    Only works when the users table is empty — disabled after first use.
    """
    if crud.count_users(db) > 0:
        raise HTTPException(status_code=403, detail="Setup already complete. Use /users to manage accounts.")
    user.role = "admin"  # Force admin role for first user
    return crud.create_user(db, user)


# ── Sales ─────────────────────────────────────────────────────────────────────
@app.get("/sales", response_model=list[schemas.SaleOut], tags=["Sales"])
def get_sales(
    skip: int = 0,
    limit: int = 500,
    current_user: models.User = Depends(require_employee),
    db: Session = Depends(get_db)
):
    # Employees see only their own entries; managers/admins see all
    sales = crud.get_sales(db, skip=skip, limit=limit)
    if current_user.role == "employee":
        sales = [s for s in sales if s.created_by_id == current_user.id]
    return sales


@app.post("/sales", response_model=schemas.SaleOut, status_code=201, tags=["Sales"])
def create_sale(
    sale: schemas.SaleCreate,
    current_user: models.User = Depends(require_employee),
    db: Session = Depends(get_db)
):
    return crud.create_sale(db, sale, created_by_id=current_user.id)


@app.delete("/sales/{sale_id}", tags=["Sales"])
def delete_sale(
    sale_id: int,
    _: models.User = Depends(require_manager),
    db: Session = Depends(get_db)
):
    if not crud.delete_sale(db, sale_id):
        raise HTTPException(status_code=404, detail="Sale not found")
    return {"deleted": sale_id}


# ── Expenses ──────────────────────────────────────────────────────────────────
@app.get("/expenses", response_model=list[schemas.ExpenseOut], tags=["Expenses"])
def get_expenses(
    skip: int = 0,
    limit: int = 500,
    current_user: models.User = Depends(require_employee),
    db: Session = Depends(get_db)
):
    expenses = crud.get_expenses(db, skip=skip, limit=limit)
    if current_user.role == "employee":
        expenses = [e for e in expenses if e.created_by_id == current_user.id]
    return expenses


@app.post("/expenses", response_model=schemas.ExpenseOut, status_code=201, tags=["Expenses"])
def create_expense(
    expense: schemas.ExpenseCreate,
    current_user: models.User = Depends(require_employee),
    db: Session = Depends(get_db)
):
    return crud.create_expense(db, expense, created_by_id=current_user.id)


@app.delete("/expenses/{expense_id}", tags=["Expenses"])
def delete_expense(
    expense_id: int,
    _: models.User = Depends(require_manager),
    db: Session = Depends(get_db)
):
    if not crud.delete_expense(db, expense_id):
        raise HTTPException(status_code=404, detail="Expense not found")
    return {"deleted": expense_id}


# ── Inventory ─────────────────────────────────────────────────────────────────
@app.get("/inventory", response_model=list[schemas.InventoryOut], tags=["Inventory"])
def get_inventory(
    _: models.User = Depends(require_employee),
    db: Session = Depends(get_db)
):
    return crud.get_inventory(db)


@app.post("/inventory", response_model=schemas.InventoryOut, status_code=201, tags=["Inventory"])
def create_product(
    product: schemas.InventoryCreate,
    _: models.User = Depends(require_manager),
    db: Session = Depends(get_db)
):
    return crud.create_product(db, product)


@app.patch("/inventory/{sku}/stock", response_model=schemas.InventoryOut, tags=["Inventory"])
def update_stock(
    sku: str,
    movement: schemas.StockMovement,
    current_user: models.User = Depends(require_employee),
    db: Session = Depends(get_db)
):
    item = crud.update_stock(db, sku, movement, created_by_id=current_user.id)
    if not item:
        raise HTTPException(status_code=404, detail=f"SKU '{sku}' not found")
    return item


@app.get("/inventory/{sku}/movements", response_model=list[schemas.StockMovementOut], tags=["Inventory"])
def get_stock_movements(
    sku: str,
    _: models.User = Depends(require_manager),
    db: Session = Depends(get_db)
):
    """Full audit log for a specific SKU — managers and admins only."""
    return crud.get_stock_movements(db, sku=sku)


@app.delete("/inventory/{sku}", tags=["Inventory"])
def delete_product(
    sku: str,
    _: models.User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    if not crud.delete_product(db, sku):
        raise HTTPException(status_code=404, detail="Product not found")
    return {"deleted": sku}


# ── Summary ───────────────────────────────────────────────────────────────────
@app.get("/summary", response_model=schemas.SummaryOut, tags=["Summary"])
def get_summary(
    _: models.User = Depends(require_manager),
    db: Session = Depends(get_db)
):
    """Dashboard KPIs — managers and admins only."""
    return crud.get_summary(db)
