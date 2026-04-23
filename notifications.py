"""
notifications.py — WhatsApp notification integration for BizMonitor via Twilio.

All notification logic lives here. main.py calls these trigger functions
after each mutation (sale, expense, low stock, etc.).

Notifications are fire-and-forget — they run in a background thread
so they never delay the API response.

─── SETUP ───────────────────────────────────────────────────────────────────

1. Sign up at https://www.twilio.com (free trial gives you credit)
2. Go to Messaging → Try it out → Send a WhatsApp message
3. Follow Twilio sandbox instructions — each recipient must send the
   join code ("join <word>-<word>") to the sandbox number once
4. Set these in your Render environment variables:
     TWILIO_ACCOUNT_SID   = ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
     TWILIO_AUTH_TOKEN    = your_auth_token
     TWILIO_WHATSAPP_FROM = whatsapp:+14155238886
     WHATSAPP_NOTIFY_TO   = whatsapp:+255XXXXXXXXX,whatsapp:+255XXXXXXXXX

5. For production (beyond sandbox), apply for a WhatsApp Business number
   at twilio.com/whatsapp — approval takes 1-3 days.

─── NOTES ───────────────────────────────────────────────────────────────────

• WHATSAPP_NOTIFY_TO supports multiple numbers (comma-separated).
  Use this to notify a manager group: add all manager numbers.
• Each business can optionally override the notify-to numbers
  via the WHATSAPP_BIZ_{ID}_NOTIFY_TO env var (e.g. WHATSAPP_BIZ_1_NOTIFY_TO)
  so Congo shop notifies a different group than Pius Shop.
• All sends are non-blocking — a Twilio failure never affects API responses.
"""

import httpx
import logging
import threading
from typing import Optional, List
from config import get_settings

logger   = logging.getLogger(__name__)
settings = get_settings()


# ── Core sender ───────────────────────────────────────────────────────────────

def _send_whatsapp(to: str, body: str):
    """Send a single WhatsApp message via Twilio REST API. Runs in a thread."""
    if not all([settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN,
                settings.TWILIO_WHATSAPP_FROM, to]):
        return

    url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.TWILIO_ACCOUNT_SID}/Messages.json"

    try:
        resp = httpx.post(
            url,
            data={"From": settings.TWILIO_WHATSAPP_FROM, "To": to, "Body": body},
            auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
            timeout=10,
        )
        if resp.status_code not in (200, 201):
            logger.warning(f"Twilio WhatsApp error {resp.status_code}: {resp.text[:200]}")
        else:
            logger.info(f"WhatsApp sent to {to}: {body[:60]}…")
    except Exception as e:
        logger.warning(f"WhatsApp send failed (non-fatal): {e}")


def _get_recipients(business_id: Optional[int] = None) -> List[str]:
    """
    Return list of WhatsApp numbers to notify.
    Per-business override: set env var WHATSAPP_BIZ_3_NOTIFY_TO=whatsapp:+255...
    Falls back to global WHATSAPP_NOTIFY_TO.
    """
    if not settings.WHATSAPP_NOTIFY_TO:
        return []

    # Check for per-business override
    if business_id:
        import os
        biz_override = os.environ.get(f"WHATSAPP_BIZ_{business_id}_NOTIFY_TO", "")
        if biz_override.strip():
            return [n.strip() for n in biz_override.split(",") if n.strip()]

    return [n.strip() for n in settings.WHATSAPP_NOTIFY_TO.split(",") if n.strip()]


def notify(message: str, business_id: Optional[int] = None):
    """
    Send a WhatsApp message to all configured recipients.
    Fire-and-forget — runs in background threads, never blocks the API.
    """
    recipients = _get_recipients(business_id)
    if not recipients:
        return  # silently skip if not configured

    for to in recipients:
        thread = threading.Thread(
            target=_send_whatsapp,
            args=(to, message),
            daemon=True,
        )
        thread.start()


def _fmt(amount: float) -> str:
    """Format a number with commas and 2 decimal places."""
    return f"{amount:,.2f}"


# ── Notification triggers ─────────────────────────────────────────────────────
# These are called from main.py after each mutation.
# Signature is kept identical to the old OneSignal version.

def on_sale_created(
    business_name: str,
    product: str,
    units: int,
    amount: float,
    rep: str = None,
    business_id: int = None,
):
    rep_str = f"\nRep: {rep}" if rep else ""
    notify(
        f"💰 *New Sale — {business_name}*\n"
        f"Product: {product}\n"
        f"Units: {units} × → Total: {_fmt(amount)}"
        f"{rep_str}",
        business_id=business_id,
    )


def on_expense_created(
    business_name: str,
    vendor: str,
    category: str,
    amount: float,
    business_id: int = None,
):
    notify(
        f"💸 *Expense Recorded — {business_name}*\n"
        f"Vendor: {vendor}\n"
        f"Category: {category}\n"
        f"Amount: {_fmt(amount)}",
        business_id=business_id,
    )


def on_low_stock(
    business_name: str,
    sku: str,
    product_name: str,
    stock: int,
    reorder: int,
    business_id: int = None,
):
    notify(
        f"⚠️ *Low Stock Alert — {business_name}*\n"
        f"Product: {product_name} ({sku})\n"
        f"Remaining: {stock} units\n"
        f"Reorder point: {reorder}",
        business_id=business_id,
    )


def on_out_of_stock(
    business_name: str,
    sku: str,
    product_name: str,
    business_id: int = None,
):
    notify(
        f"🔴 *OUT OF STOCK — {business_name}*\n"
        f"Product: {product_name} ({sku})\n"
        f"Action required — restock immediately!",
        business_id=business_id,
    )


def on_sale_deleted(
    business_name: str,
    product: str,
    amount: float,
    deleted_by: str,
    business_id: int = None,
):
    notify(
        f"🗑️ *Sale Deleted — {business_name}*\n"
        f"Product: {product} — {_fmt(amount)}\n"
        f"Deleted by: {deleted_by}",
        business_id=business_id,
    )


def on_expense_deleted(
    business_name: str,
    description: str,
    amount: float,
    deleted_by: str,
    business_id: int = None,
):
    notify(
        f"🗑️ *Expense Deleted — {business_name}*\n"
        f"Description: {description} — {_fmt(amount)}\n"
        f"Deleted by: {deleted_by}",
        business_id=business_id,
    )


def on_stock_received(
    business_name: str,
    sku: str,
    product_name: str,
    qty: int,
    new_stock: int,
    business_id: int = None,
):
    notify(
        f"📦 *Stock Received — {business_name}*\n"
        f"Product: {product_name} ({sku})\n"
        f"+{qty} units received → {new_stock} total now",
        business_id=business_id,
    )


def on_new_user(full_name: str, role: str, created_by: str):
    notify(
        f"👤 *New User Added — BizMonitor*\n"
        f"Name: {full_name}\n"
        f"Role: {role}\n"
        f"Added by: {created_by}",
    )


def on_cash_recorded(
    business_name: str,
    date: str,
    closing: float,
    bank: float = None,
    business_id: int = None,
):
    bank_str = f"\nBank: {_fmt(bank)}\nTotal: {_fmt(closing + bank)}" if bank else ""
    notify(
        f"💵 *Cash Balance — {business_name}*\n"
        f"Date: {date}\n"
        f"Closing cash: {_fmt(closing)}"
        f"{bank_str}",
        business_id=business_id,
    )


def on_daily_summary(
    business_name: str,
    sales_count: int,
    revenue: float,
    expenses_total: float,
    net: float,
    business_id: int = None,
):
    """Optional: call this from a scheduled job for daily summaries."""
    notify(
        f"📊 *Daily Summary — {business_name}*\n"
        f"Sales: {sales_count} transactions\n"
        f"Revenue: {_fmt(revenue)}\n"
        f"Expenses: {_fmt(expenses_total)}\n"
        f"Net: {_fmt(net)}",
        business_id=business_id,
    )
