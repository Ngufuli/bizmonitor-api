"""
main.py — BizMonitor API v3
Multi-business + Admin Panel + Activity Log
"""

from fastapi import FastAPI, HTTPException, Depends, status, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import timedelta, date as date_type
from typing import Optional

import models, schemas, crud
from database import engine, get_db
from auth import (
    authenticate_user, create_access_token, get_current_user,
    verify_password, require_employee, require_manager, require_admin,
)
from config import get_settings
import notifications as notif

# Safe imports — won't crash server if apscheduler not yet installed
try:
    import reports as rpt
    import scheduler as sched
    _scheduler_available = True
except ImportError as _e:
    import logging
    logging.getLogger(__name__).warning(f"Scheduler not available: {_e}. Install apscheduler and pytz.")
    rpt  = None
    sched = None
    _scheduler_available = False

settings = get_settings()
models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.APP_NAME,
    version="3.0.0",
    description="BizMonitor — Multi-business, JWT auth, Admin panel",
)

@app.on_event("startup")
def startup_event():
    if _scheduler_available and sched:
        sched.start_scheduler()

@app.on_event("shutdown")
def shutdown_event():
    if _scheduler_available and sched:
        sched.stop_scheduler()

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

def get_biz_name(business_id: int, db: Session) -> str:
    """Return business name for notification titles. Falls back to ID if not found."""
    biz = db.query(models.Business).filter(models.Business.id == business_id).first()
    return biz.name if biz else f"Business #{business_id}"


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
    result = crud.create_user(db, user, created_by_id=current_user.id)
    notif.on_new_user(
        full_name  = user.full_name,
        role       = user.role,
        created_by = current_user.full_name,
    )
    return result

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
    result = crud.create_sale(db, sale, business_id=business_id, created_by_id=current_user.id)
    notif.on_sale_created(
        business_name = get_biz_name(business_id, db),
        product       = sale.product,
        units         = sale.units,
        amount        = sale.amount,
        rep           = sale.rep or current_user.full_name,
        business_id   = business_id,
    )
    return result

@app.delete("/businesses/{business_id}/sales/{sale_id}", tags=["Sales"])
def delete_sale(business_id: int, sale_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_business_manager(business_id, current_user, db)
    # Fetch sale BEFORE deleting so we can restore inventory
    sale = db.query(models.Sale).filter(
        models.Sale.id == sale_id,
        models.Sale.business_id == business_id
    ).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")

    # Restore inventory if this sale was linked to a SKU
    restored_sku = None
    if sale.sku:
        item = db.query(models.InventoryItem).filter(
            models.InventoryItem.sku == sale.sku,
            models.InventoryItem.business_id == business_id,
        ).first()
        if item and sale.units and sale.units > 0:
            import schemas as sc
            restore = sc.StockMovement(
                movement_type = "add",
                qty           = sale.units,
                reason        = f"Sale #{sale_id} deleted — {sale.units} units restored",
                received_by   = current_user.full_name,
            )
            crud.update_stock(db, sale.sku, business_id, restore, created_by_id=current_user.id)
            restored_sku = sale.sku

    if not crud.delete_sale(db, sale_id, business_id):
        raise HTTPException(status_code=404, detail="Sale not found")

    notif.on_sale_deleted(
        business_name = get_biz_name(business_id, db),
        product       = sale.product,
        amount        = sale.amount,
        deleted_by    = current_user.full_name,
    )
    return {
        "deleted":      sale_id,
        "restored_sku": restored_sku,
        "units_back":   sale.units if restored_sku else 0,
    }


# ── Expenses (business-scoped) ────────────────────────────────────────────────
@app.get("/businesses/{business_id}/expenses", response_model=list[schemas.ExpenseOut], tags=["Expenses"])
def get_expenses(business_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    get_business_or_403(business_id, current_user, db)
    return crud.get_expenses(db, business_id)

@app.post("/businesses/{business_id}/expenses", response_model=schemas.ExpenseOut, status_code=201, tags=["Expenses"])
def create_expense(business_id: int, expense: schemas.ExpenseCreate, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    get_business_or_403(business_id, current_user, db)
    result = crud.create_expense(db, expense, business_id=business_id, created_by_id=current_user.id)
    notif.on_expense_created(
        business_name = get_biz_name(business_id, db),
        vendor        = expense.vendor,
        category      = expense.category,
        amount        = expense.amount,
        business_id   = business_id,
    )
    return result

@app.delete("/businesses/{business_id}/expenses/{expense_id}", tags=["Expenses"])
def delete_expense(business_id: int, expense_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_business_manager(business_id, current_user, db)
    exp = db.query(models.Expense).filter(models.Expense.id == expense_id, models.Expense.business_id == business_id).first()
    if not crud.delete_expense(db, expense_id, business_id):
        raise HTTPException(status_code=404, detail="Expense not found")
    if exp:
        notif.on_expense_deleted(
            business_name = get_biz_name(business_id, db),
            description   = exp.description,
            amount        = exp.amount,
            deleted_by    = current_user.full_name,
        )
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

@app.patch("/businesses/{business_id}/inventory/{sku}/price", response_model=schemas.InventoryOut, tags=["Inventory"])
def update_inventory_price(business_id: int, sku: str, data: schemas.InventoryPriceUpdate, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_business_manager(business_id, current_user, db)
    item = db.query(models.InventoryItem).filter(
        models.InventoryItem.sku == sku.upper(),
        models.InventoryItem.business_id == business_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"SKU '{sku}' not found")
    item.unit_cost = data.unit_cost
    if data.reorder is not None: item.reorder = data.reorder
    if data.name    is not None: item.name    = data.name
    log_activity(db, "updated_price", f"{sku}: cost→{data.unit_cost}", user_id=current_user.id, business_id=business_id)
    db.commit()
    db.refresh(item)
    return item

@app.patch("/businesses/{business_id}/inventory/bulk-price", tags=["Inventory"])
def bulk_update_prices(business_id: int, data: schemas.BulkPriceUpdate, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_business_manager(business_id, current_user, db)
    updated = []
    skipped = []
    for entry in data.items:
        item = db.query(models.InventoryItem).filter(
            models.InventoryItem.sku == entry.sku.upper(),
            models.InventoryItem.business_id == business_id,
        ).first()
        if item:
            item.unit_cost = entry.unit_cost
            updated.append(entry.sku.upper())
        else:
            skipped.append(entry.sku.upper())
    log_activity(db, "bulk_price_update", f"Updated {len(updated)} SKUs: {', '.join(updated)}", user_id=current_user.id, business_id=business_id)
    db.commit()
    return {"updated": updated, "skipped": skipped, "count": len(updated)}

@app.patch("/businesses/{business_id}/inventory/{sku}/stock", response_model=schemas.InventoryOut, tags=["Inventory"])
def update_stock(business_id: int, sku: str, movement: schemas.StockMovement, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    get_business_or_403(business_id, current_user, db)
    item = crud.update_stock(db, sku, business_id, movement, created_by_id=current_user.id)
    if not item:
        raise HTTPException(status_code=404, detail=f"SKU '{sku}' not found")
    biz_name = get_biz_name(business_id, db)
    if movement.movement_type == "add":
        notif.on_stock_received(biz_name, item.sku, item.name, movement.qty, item.stock, business_id=business_id)
    if item.stock == 0:
        notif.on_out_of_stock(biz_name, item.sku, item.name, business_id=business_id)
    elif item.status == "low":
        notif.on_low_stock(biz_name, item.sku, item.name, item.stock, item.reorder, business_id=business_id)
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


# ── WhatsApp Test (admin only) ────────────────────────────────────────────────
@app.post("/admin/test-whatsapp", tags=["Admin"])
def test_whatsapp(
    current_user: models.User = Depends(require_admin),
):
    """
    Send a test WhatsApp message to verify Twilio configuration.
    Call this from the Render shell or any REST client while logged in as admin.
    GET /admin/test-whatsapp with your JWT token in the Authorization header.
    """
    import notifications as n
    from config import get_settings
    cfg = get_settings()

    if not cfg.TWILIO_ACCOUNT_SID:
        return {"status": "not_configured", "message": "Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM and WHATSAPP_NOTIFY_TO in Render environment variables."}

    n.notify(
        f"✅ *BizMonitor WhatsApp Test*\n"
        f"Configuration is working!\n"
        f"Sent by: {current_user.full_name}\n"
        f"Server: {cfg.APP_NAME}"
    )
    recipients = n._get_recipients()
    return {
        "status": "sent",
        "recipients": recipients,
        "from": cfg.TWILIO_WHATSAPP_FROM,
        "message": "Test message dispatched to all recipients (check your WhatsApp)"
    }


# ── WhatsApp Reports ──────────────────────────────────────────────────────────

class ReportRequest(BaseModel):
    report_type: str = "daily"   # "daily" | "weekly" | "inventory"
    report_date: Optional[str]   = None  # YYYY-MM-DD, defaults to today

@app.post("/businesses/{business_id}/send-report", tags=["Reports"])
def send_whatsapp_report(
    business_id: int,
    req: ReportRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not _scheduler_available or rpt is None:
        raise HTTPException(status_code=503, detail="Reports module not available. Ensure apscheduler and pytz are installed.")
    require_business_manager(business_id, current_user, db)
    biz = db.query(models.Business).filter(models.Business.id == business_id).first()
    if not biz:
        raise HTTPException(status_code=404, detail="Business not found")

    from config import get_settings
    cfg = get_settings()
    if not cfg.TWILIO_ACCOUNT_SID:
        raise HTTPException(status_code=503, detail="WhatsApp not configured. Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM and WHATSAPP_NOTIFY_TO in environment variables.")

    report_date = None
    if req.report_date:
        try:
            from datetime import date as dt
            report_date = dt.fromisoformat(req.report_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format, use YYYY-MM-DD")

    try:
        message = rpt.send_report_for_business(db, business_id, biz.name, req.report_type, report_date)
        notif_recipients = notif._get_recipients(business_id)
        return {
            "status":      "sent",
            "report_type": req.report_type,
            "business":    biz.name,
            "recipients":  notif_recipients,
            "preview":     message[:300] + "…" if len(message) > 300 else message,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Report failed: {e}")


@app.get("/admin/scheduler-status", tags=["Admin"])
def scheduler_status(_: models.User = Depends(require_admin)):
    if not _scheduler_available or sched is None:
        return {"status": "not_available", "reason": "apscheduler not installed"}
    return sched.get_next_runs()


@app.post("/admin/send-all-reports", tags=["Admin"])
def send_all_reports_now(
    report_type: str = "daily",
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not _scheduler_available or rpt is None:
        raise HTTPException(status_code=503, detail="Reports module not available")
    from config import get_settings
    cfg = get_settings()
    if not cfg.TWILIO_ACCOUNT_SID:
        raise HTTPException(status_code=503, detail="WhatsApp not configured")

    if report_type == "daily":
        count = rpt.send_daily_reports(db)
    elif report_type == "weekly":
        count = rpt.send_weekly_reports(db)
    else:
        raise HTTPException(status_code=400, detail="report_type must be 'daily' or 'weekly'")

    return {"status": "sent", "report_type": report_type, "businesses": count}
