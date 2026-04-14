"""
notifications.py — OneSignal push notification integration for BizMonitor.

All notification logic lives here. main.py calls these functions
after each mutation (create sale, expense, low stock, etc.).

Notifications are fire-and-forget — they run in a background thread
so they never delay the API response if OneSignal is slow.
"""

import httpx
import logging
import threading
from typing import Optional
from config import get_settings

logger   = logging.getLogger(__name__)
settings = get_settings()

ONESIGNAL_API = "https://onesignal.com/api/v1/notifications"


# ── Core sender ───────────────────────────────────────────────────────────────

def _send(payload: dict):
    """Internal — POST to OneSignal synchronously. Called in a thread."""
    if not settings.ONESIGNAL_APP_ID or not settings.ONESIGNAL_API_KEY:
        return  # silently skip if not configured

    try:
        resp = httpx.post(
            ONESIGNAL_API,
            json=payload,
            headers={
                "Authorization": f"Basic {settings.ONESIGNAL_API_KEY}",
                "Content-Type":  "application/json",
            },
            timeout=8,
        )
        if resp.status_code not in (200, 202):
            logger.warning(f"OneSignal returned {resp.status_code}: {resp.text}")
        else:
            logger.info(f"Notification sent: {payload.get('headings',{}).get('en','')}")
    except Exception as e:
        logger.warning(f"Notification failed (non-fatal): {e}")


def notify(
    title:    str,
    message:  str,
    segment:  str  = "All",         # "All" | "Admins" | "Managers"
    url:      str  = "/",
    icon:     str  = "notification-icon",
    data:     Optional[dict] = None,
):
    """
    Send a push notification via OneSignal in a background thread.
    Fire-and-forget — never blocks the API response.
    """
    if not settings.ONESIGNAL_APP_ID:
        return

    payload = {
        "app_id":           settings.ONESIGNAL_APP_ID,
        "headings":         {"en": title},
        "contents":         {"en": message},
        "included_segments": [segment],
        "url":              f"{settings.FRONTEND_URL}{url}",
        "chrome_web_icon":  f"{settings.FRONTEND_URL}/icon-192.png",
        "firefox_icon":     f"{settings.FRONTEND_URL}/icon-192.png",
        "data":             data or {},
    }

    thread = threading.Thread(target=_send, args=(payload,), daemon=True)
    thread.start()


# ── Business-specific helper ──────────────────────────────────────────────────

def notify_biz(title: str, message: str, business_name: str, url: str = "/", data: dict = None):
    """Prefix notification title with business name for multi-business clarity."""
    notify(
        title   = f"[{business_name}] {title}",
        message = message,
        url     = url,
        data    = data,
    )


# ── Notification triggers ─────────────────────────────────────────────────────

def on_sale_created(business_name: str, product: str, units: int, amount: float, rep: str = None):
    rep_str = f" by {rep}" if rep else ""
    notify_biz(
        title         = "💰 New Sale",
        message       = f"{units}× {product} — {amount:,.2f}{rep_str}",
        business_name = business_name,
        url           = "/",
        data          = {"type": "sale", "product": product},
    )


def on_expense_created(business_name: str, vendor: str, category: str, amount: float):
    notify_biz(
        title         = "💸 Expense Recorded",
        message       = f"{vendor} · {category} — {amount:,.2f}",
        business_name = business_name,
        url           = "/",
        data          = {"type": "expense", "category": category},
    )


def on_low_stock(business_name: str, sku: str, product_name: str, stock: int, reorder: int):
    notify_biz(
        title         = "⚠️ Low Stock Alert",
        message       = f"{product_name} ({sku}) — only {stock} left (reorder: {reorder})",
        business_name = business_name,
        url           = "/",
        data          = {"type": "low_stock", "sku": sku},
    )


def on_out_of_stock(business_name: str, sku: str, product_name: str):
    notify_biz(
        title         = "🔴 Out of Stock",
        message       = f"{product_name} ({sku}) has reached zero units",
        business_name = business_name,
        url           = "/",
        data          = {"type": "out_of_stock", "sku": sku},
    )


def on_sale_deleted(business_name: str, product: str, amount: float, deleted_by: str):
    notify_biz(
        title         = "🗑️ Sale Deleted",
        message       = f"{product} — {amount:,.2f} (deleted by {deleted_by})",
        business_name = business_name,
        url           = "/",
        data          = {"type": "sale_deleted"},
    )


def on_expense_deleted(business_name: str, description: str, amount: float, deleted_by: str):
    notify_biz(
        title         = "🗑️ Expense Deleted",
        message       = f"{description} — {amount:,.2f} (deleted by {deleted_by})",
        business_name = business_name,
        url           = "/",
        data          = {"type": "expense_deleted"},
    )


def on_new_user(full_name: str, role: str, created_by: str):
    notify(
        title   = "👤 New User Added",
        message = f"{full_name} ({role}) added by {created_by}",
        url     = "/",
        data    = {"type": "new_user"},
    )


def on_stock_received(business_name: str, sku: str, product_name: str, qty: int, new_stock: int):
    notify_biz(
        title         = "📦 Stock Received",
        message       = f"{product_name} ({sku}) +{qty} units → {new_stock} total",
        business_name = business_name,
        url           = "/",
        data          = {"type": "stock_received", "sku": sku},
    )
