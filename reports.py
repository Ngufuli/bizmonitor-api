"""
reports.py — Report generation for BizMonitor WhatsApp reports.

Generates daily, weekly, and on-demand reports for each active business.
Pulls data directly from the database, formats clean WhatsApp messages,
and dispatches via notifications.py.

Called by:
  - scheduler.py   (automated daily/weekly at set times)
  - main.py        (on-demand from admin/manager via API)
"""

import logging
from datetime import date, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func

import models
import notifications as notif

logger = logging.getLogger(__name__)


# ── Formatting helpers ────────────────────────────────────────────────────────

def _fmt(n: float) -> str:
    return f"{n:,.2f}"

def _pct(part: float, total: float) -> str:
    if not total: return "0.0%"
    return f"{part/total*100:.1f}%"

def _bar(value: float, total: float, width: int = 8) -> str:
    """Simple text progress bar: ████░░░░"""
    if not total: return "░" * width
    filled = round(value / total * width)
    return "█" * filled + "░" * (width - filled)


# ── Data fetchers ─────────────────────────────────────────────────────────────

def _get_sales_for_range(db: Session, business_id: int, from_date: date, to_date: date):
    return db.query(models.Sale).filter(
        models.Sale.business_id == business_id,
        models.Sale.date >= from_date,
        models.Sale.date <= to_date,
    ).all()

def _get_expenses_for_range(db: Session, business_id: int, from_date: date, to_date: date):
    return db.query(models.Expense).filter(
        models.Expense.business_id == business_id,
        models.Expense.date >= from_date,
        models.Expense.date <= to_date,
    ).all()

def _get_low_stock(db: Session, business_id: int):
    return db.query(models.InventoryItem).filter(
        models.InventoryItem.business_id == business_id,
        models.InventoryItem.status.in_(["low", "out"]),
    ).order_by(models.InventoryItem.stock.asc()).all()

def _get_active_businesses(db: Session):
    return db.query(models.Business).filter(
        models.Business.is_active == True
    ).all()

def _get_latest_cash(db: Session, business_id: int):
    return db.query(models.CashBalance).filter(
        models.CashBalance.business_id == business_id,
    ).order_by(models.CashBalance.date.desc()).first()


# ── Report builders ───────────────────────────────────────────────────────────

def build_daily_report(db: Session, business_id: int, business_name: str, report_date: date = None) -> str:
    """Build a daily WhatsApp report for one business."""
    d = report_date or date.today()

    sales    = _get_sales_for_range(db, business_id, d, d)
    expenses = _get_expenses_for_range(db, business_id, d, d)
    alerts   = _get_low_stock(db, business_id)
    cash     = _get_latest_cash(db, business_id)

    revenue       = sum(s.amount for s in sales)
    cogs          = sum((getattr(s, "unit_cost", 0) or 0) * s.units for s in sales)
    gross_profit  = revenue - cogs
    total_exp     = sum(e.amount for e in expenses)
    net_profit    = gross_profit - total_exp
    units_sold    = sum(s.units for s in sales)

    # Expense by category
    cat_totals: dict[str, float] = {}
    for e in expenses:
        cat_totals[e.category] = cat_totals.get(e.category, 0) + e.amount

    # Top 3 products by revenue
    product_rev: dict[str, float] = {}
    for s in sales:
        product_rev[s.product] = product_rev.get(s.product, 0) + s.amount
    top_products = sorted(product_rev.items(), key=lambda x: x[1], reverse=True)[:3]

    lines = [
        f"📊 *Daily Report — {business_name}*",
        f"📅 {d.strftime('%A, %d %B %Y')}",
        f"{'─' * 28}",
        f"",
        f"💰 *SALES*",
        f"   Revenue:    {_fmt(revenue)}",
        f"   Gross Profit: {_fmt(gross_profit)} ({_pct(gross_profit, revenue)})" if cogs else f"   Transactions: {len(sales)}",
        f"   Units sold:  {units_sold}",
        f"   Transactions: {len(sales)}",
    ]

    if top_products:
        lines.append(f"")
        lines.append(f"   🏆 Top sellers:")
        for i, (prod, rev) in enumerate(top_products, 1):
            lines.append(f"   {i}. {prod[:20]} — {_fmt(rev)}")

    lines += [
        f"",
        f"💸 *EXPENSES*",
        f"   Total: {_fmt(total_exp)} ({len(expenses)} entries)",
    ]

    if cat_totals:
        for cat, amt in sorted(cat_totals.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"   • {cat}: {_fmt(amt)}")

    lines += [
        f"",
        f"{'─' * 28}",
        f"{'📈' if net_profit >= 0 else '📉'} *NET: {_fmt(net_profit)}*",
        f"   Margin: {_pct(net_profit, revenue)}",
    ]

    if cash:
        bank = getattr(cash, "bank_balance", 0) or 0
        total_balance = cash.closing_balance + bank
        lines += [
            f"",
            f"💵 *BALANCE*",
            f"   Cash:  {_fmt(cash.closing_balance)}",
        ]
        if bank:
            lines.append(f"   Bank:  {_fmt(bank)}")
            lines.append(f"   Total: {_fmt(total_balance)}")

    if alerts:
        out = [a for a in alerts if a.status == "out"]
        low = [a for a in alerts if a.status == "low"]
        lines.append(f"")
        lines.append(f"⚠️ *STOCK ALERTS*")
        for a in out:
            lines.append(f"   🔴 {a.name} ({a.sku}) — OUT OF STOCK")
        for a in low[:5]:  # max 5 low alerts
            lines.append(f"   🟡 {a.name} ({a.sku}) — {a.stock} left")

    lines += [
        f"",
        f"_BizMonitor · {d.strftime('%d/%m/%Y')}_",
    ]

    return "\n".join(lines)


def build_weekly_report(db: Session, business_id: int, business_name: str) -> str:
    """Build a weekly summary report (last 7 days)."""
    today    = date.today()
    week_ago = today - timedelta(days=6)

    sales    = _get_sales_for_range(db, business_id, week_ago, today)
    expenses = _get_expenses_for_range(db, business_id, week_ago, today)
    alerts   = _get_low_stock(db, business_id)

    revenue      = sum(s.amount for s in sales)
    cogs         = sum((getattr(s, "unit_cost", 0) or 0) * s.units for s in sales)
    gross_profit = revenue - cogs
    total_exp    = sum(e.amount for e in expenses)
    net_profit   = gross_profit - total_exp
    units_sold   = sum(s.units for s in sales)
    avg_daily    = revenue / 7

    # Daily revenue breakdown
    daily: dict[str, float] = {}
    for s in sales:
        day = str(s.date)
        daily[day] = daily.get(day, 0) + s.amount
    best_day = max(daily.items(), key=lambda x: x[1]) if daily else None

    # Expense by category
    cat_totals: dict[str, float] = {}
    for e in expenses:
        cat_totals[e.category] = cat_totals.get(e.category, 0) + e.amount

    # Top 5 products
    product_rev: dict[str, float] = {}
    for s in sales:
        product_rev[s.product] = product_rev.get(s.product, 0) + s.amount
    top_products = sorted(product_rev.items(), key=lambda x: x[1], reverse=True)[:5]

    lines = [
        f"📊 *Weekly Report — {business_name}*",
        f"📅 {week_ago.strftime('%d %b')} – {today.strftime('%d %b %Y')}",
        f"{'─' * 28}",
        f"",
        f"💰 *SALES SUMMARY*",
        f"   Revenue:      {_fmt(revenue)}",
        f"   Gross Profit: {_fmt(gross_profit)} ({_pct(gross_profit, revenue)})",
        f"   Units sold:   {units_sold}",
        f"   Transactions: {len(sales)}",
        f"   Daily avg:    {_fmt(avg_daily)}",
    ]

    if best_day:
        lines.append(f"   Best day:     {best_day[0]} ({_fmt(best_day[1])})")

    if top_products:
        lines.append(f"")
        lines.append(f"   🏆 *Top Products:*")
        for i, (prod, rev) in enumerate(top_products, 1):
            bar = _bar(rev, revenue, 6)
            lines.append(f"   {i}. {prod[:18]}")
            lines.append(f"      {bar} {_fmt(rev)} ({_pct(rev, revenue)})")

    lines += [
        f"",
        f"💸 *EXPENSES*",
        f"   Total: {_fmt(total_exp)} ({len(expenses)} entries)",
    ]

    if cat_totals:
        for cat, amt in sorted(cat_totals.items(), key=lambda x: x[1], reverse=True):
            bar = _bar(amt, total_exp, 6)
            lines.append(f"   {bar} {cat}: {_fmt(amt)}")

    lines += [
        f"",
        f"{'─' * 28}",
        f"{'📈' if net_profit >= 0 else '📉'} *WEEKLY NET: {_fmt(net_profit)}*",
        f"   Net margin: {_pct(net_profit, revenue)}",
    ]

    if alerts:
        out  = [a for a in alerts if a.status == "out"]
        low  = [a for a in alerts if a.status == "low"]
        lines.append(f"")
        lines.append(f"⚠️ *STOCK ALERTS ({len(alerts)} items)*")
        for a in out:
            lines.append(f"   🔴 {a.name} ({a.sku}) — OUT OF STOCK")
        for a in low[:8]:
            lines.append(f"   🟡 {a.name} ({a.sku}) — {a.stock} left (reorder: {a.reorder})")

    lines += [
        f"",
        f"_BizMonitor Weekly · {today.strftime('%d/%m/%Y')}_",
    ]

    return "\n".join(lines)


def build_inventory_report(db: Session, business_id: int, business_name: str) -> str:
    """Build a standalone inventory status report."""
    inventory = db.query(models.InventoryItem).filter(
        models.InventoryItem.business_id == business_id
    ).order_by(models.InventoryItem.status.asc(), models.InventoryItem.stock.asc()).all()

    out_of_stock = [i for i in inventory if i.status == "out"]
    low_stock    = [i for i in inventory if i.status == "low"]
    ok_stock     = [i for i in inventory if i.status == "ok"]
    total_value  = sum(i.stock * i.unit_cost for i in inventory)

    lines = [
        f"📦 *Inventory Report — {business_name}*",
        f"📅 {date.today().strftime('%d %B %Y')}",
        f"{'─' * 28}",
        f"",
        f"📊 *SUMMARY*",
        f"   Total SKUs:    {len(inventory)}",
        f"   OK:            {len(ok_stock)}",
        f"   Low stock:     {len(low_stock)}",
        f"   Out of stock:  {len(out_of_stock)}",
        f"   Total value:   {_fmt(total_value)}",
    ]

    if out_of_stock:
        lines.append(f"")
        lines.append(f"🔴 *OUT OF STOCK ({len(out_of_stock)})*")
        for item in out_of_stock:
            lines.append(f"   • {item.name} ({item.sku})")

    if low_stock:
        lines.append(f"")
        lines.append(f"🟡 *LOW STOCK ({len(low_stock)})*")
        for item in low_stock:
            lines.append(f"   • {item.name} ({item.sku})")
            lines.append(f"     Stock: {item.stock} | Reorder: {item.reorder}")

    lines += [
        f"",
        f"_BizMonitor Inventory · {date.today().strftime('%d/%m/%Y')}_",
    ]

    return "\n".join(lines)


# ── Dispatch helpers ──────────────────────────────────────────────────────────

def send_daily_reports(db: Session, report_date: date = None):
    """Send daily report for ALL active businesses. Called by scheduler."""
    businesses = _get_active_businesses(db)
    sent = 0
    for biz in businesses:
        try:
            message = build_daily_report(db, biz.id, biz.name, report_date)
            notif.notify(message, business_id=biz.id)
            logger.info(f"Daily report sent for {biz.name}")
            sent += 1
        except Exception as e:
            logger.error(f"Failed daily report for {biz.name}: {e}")
    return sent


def send_weekly_reports(db: Session):
    """Send weekly report for ALL active businesses. Called by scheduler."""
    businesses = _get_active_businesses(db)
    sent = 0
    for biz in businesses:
        try:
            message = build_weekly_report(db, biz.id, biz.name)
            notif.notify(message, business_id=biz.id)
            logger.info(f"Weekly report sent for {biz.name}")
            sent += 1
        except Exception as e:
            logger.error(f"Failed weekly report for {biz.name}: {e}")
    return sent


def send_report_for_business(db: Session, business_id: int, business_name: str, report_type: str, report_date: date = None) -> str:
    """Send a single report for one business. Called on-demand from API."""
    if report_type == "daily":
        message = build_daily_report(db, business_id, business_name, report_date)
    elif report_type == "weekly":
        message = build_weekly_report(db, business_id, business_name)
    elif report_type == "inventory":
        message = build_inventory_report(db, business_id, business_name)
    else:
        raise ValueError(f"Unknown report type: {report_type}")

    notif.notify(message, business_id=business_id)
    return message
