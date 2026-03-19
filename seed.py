"""
seed.py — Populate database with initial data.
Run once after deploying: python seed.py

Creates:
  - 1 admin user
  - 1 manager user  
  - 1 employee user
  - 6 inventory items
  - 12 months of sales + expense history
"""

import os, math, sys
from database import SessionLocal, engine
import models, crud, schemas
from datetime import date

models.Base.metadata.create_all(bind=engine)
db = SessionLocal()

# ── Users ──────────────────────────────────────────────────────────────────────
print("Creating users...")
users_to_create = [
    {"email": "admin@bizmonitor.com",   "full_name": "Admin User",    "password": "Admin@1234",    "role": "admin",    "department": "Management"},
    {"email": "manager@bizmonitor.com", "full_name": "Sarah Mitchell", "password": "Manager@1234",  "role": "manager",  "department": "Finance"},
    {"email": "staff@bizmonitor.com",   "full_name": "James Okonkwo",  "password": "Staff@1234",    "role": "employee", "department": "Sales"},
]
created_users = {}
for u in users_to_create:
    from auth import get_user_by_email
    existing = get_user_by_email(db, u["email"])
    if not existing:
        created = crud.create_user(db, schemas.UserCreate(**u))
        print(f"  + [{u['role']}] {u['email']}")
        created_users[u["role"]] = created
    else:
        print(f"  ~ already exists: {u['email']}")
        created_users[u["role"]] = existing

admin_id = created_users.get("admin", {}).id if created_users.get("admin") else None

# ── Inventory ──────────────────────────────────────────────────────────────────
print("Seeding inventory...")
products = [
    {"sku":"PRD-001","name":"Premium Widget A",   "stock":1240,"reorder":200,"unit_cost":50.0},
    {"sku":"PRD-002","name":"Standard Widget B",  "stock":87,  "reorder":150,"unit_cost":40.0},
    {"sku":"PRD-003","name":"Deluxe Component C", "stock":0,   "reorder":100,"unit_cost":120.0},
    {"sku":"PRD-004","name":"Basic Unit D",        "stock":560, "reorder":100,"unit_cost":20.0},
    {"sku":"PRD-005","name":"Module E",            "stock":320, "reorder":80, "unit_cost":80.0},
    {"sku":"PRD-006","name":"Assembly F",          "stock":42,  "reorder":60, "unit_cost":200.0},
]
for p in products:
    existing = db.query(models.InventoryItem).filter(models.InventoryItem.sku == p["sku"]).first()
    if not existing:
        crud.create_product(db, schemas.InventoryCreate(**p))
        print(f"  + {p['sku']} {p['name']}")

# ── Sales ──────────────────────────────────────────────────────────────────────
MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
print("Seeding sales...")
for i, m in enumerate(MONTHS):
    amount = round(120000 + math.sin(i * 0.7) * 40000 + i * 8000, 2)
    units  = round(800 + math.sin(i * 0.5) * 200 + i * 30)
    d = date(2024, i + 1, 1)
    existing = db.query(models.Sale).filter(models.Sale.date == d, models.Sale.product == "General Sales").first()
    if not existing:
        crud.create_sale(db, schemas.SaleCreate(date=d, product="General Sales", amount=amount, units=units, rep="System"), created_by_id=admin_id)
        print(f"  + {m}: ${amount:,.0f}")

# ── Expenses ───────────────────────────────────────────────────────────────────
print("Seeding expenses...")
cats = ["Operations","Marketing","Payroll","Other"]
for i, m in enumerate(MONTHS):
    amount = round(30000 + i * 2000 + math.sin(i) * 5000, 2)
    d   = date(2024, i + 1, 1)
    cat = cats[i % 4]
    existing = db.query(models.Expense).filter(models.Expense.date == d, models.Expense.category == cat).first()
    if not existing:
        crud.create_expense(db, schemas.ExpenseCreate(date=d, category=cat, amount=amount, vendor="System", description="Monthly operating expense"), created_by_id=admin_id)
        print(f"  + {m} [{cat}]: ${amount:,.0f}")

db.close()

print("""
✅ Seed complete.

Login credentials:
  Admin:    admin@bizmonitor.com    / Admin@1234
  Manager:  manager@bizmonitor.com  / Manager@1234
  Employee: staff@bizmonitor.com    / Staff@1234

⚠️  Change all passwords after first login!
""")
