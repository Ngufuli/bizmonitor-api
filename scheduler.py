"""
scheduler.py — Automated report scheduling for BizMonitor.

Uses APScheduler to send WhatsApp reports on a schedule.
Runs inside the FastAPI process (no separate worker needed).

Schedule (all times in Africa/Dar_es_Salaam timezone, UTC+3):
  Daily report  — every day at 20:00 (8 PM)
  Weekly report — every Sunday at 19:00 (7 PM)

To change times, edit DAILY_HOUR / WEEKLY_DAY_OF_WEEK below.

Requirements (add to your Render requirements.txt or pip install):
  apscheduler>=3.10.0
  pytz

"""

import logging
from datetime import date
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from database import SessionLocal
import reports

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
TIMEZONE        = "Africa/Dar_es_Salaam"   # UTC+3 — change to your timezone
DAILY_HOUR      = 20   # 8 PM — time to send daily reports
DAILY_MINUTE    = 0
WEEKLY_DAY      = "sun"  # Sunday
WEEKLY_HOUR     = 19   # 7 PM — weekly report a bit earlier than daily
WEEKLY_MINUTE   = 0
# ─────────────────────────────────────────────────────────────────────────────

tz = pytz.timezone(TIMEZONE)
_scheduler = None


def _run_daily():
    """Job: send daily reports for all businesses."""
    logger.info("⏰ Scheduled: sending daily WhatsApp reports…")
    db = SessionLocal()
    try:
        count = reports.send_daily_reports(db)
        logger.info(f"✅ Daily reports sent for {count} businesses")
    except Exception as e:
        logger.error(f"❌ Daily report job failed: {e}")
    finally:
        db.close()


def _run_weekly():
    """Job: send weekly reports for all businesses."""
    logger.info("⏰ Scheduled: sending weekly WhatsApp reports…")
    db = SessionLocal()
    try:
        count = reports.send_weekly_reports(db)
        logger.info(f"✅ Weekly reports sent for {count} businesses")
    except Exception as e:
        logger.error(f"❌ Weekly report job failed: {e}")
    finally:
        db.close()


def start_scheduler():
    """Start the background scheduler. Call once on FastAPI startup."""
    global _scheduler
    if _scheduler and _scheduler.running:
        return  # already started

    _scheduler = BackgroundScheduler(timezone=tz)

    # Daily report — every day at DAILY_HOUR:DAILY_MINUTE
    _scheduler.add_job(
        _run_daily,
        CronTrigger(hour=DAILY_HOUR, minute=DAILY_MINUTE, timezone=tz),
        id="daily_report",
        name="Daily WhatsApp Report",
        replace_existing=True,
    )

    # Weekly report — every WEEKLY_DAY at WEEKLY_HOUR:WEEKLY_MINUTE
    _scheduler.add_job(
        _run_weekly,
        CronTrigger(day_of_week=WEEKLY_DAY, hour=WEEKLY_HOUR, minute=WEEKLY_MINUTE, timezone=tz),
        id="weekly_report",
        name="Weekly WhatsApp Report",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info(
        f"📅 Scheduler started — "
        f"Daily reports at {DAILY_HOUR:02d}:{DAILY_MINUTE:02d} {TIMEZONE}, "
        f"Weekly on {WEEKLY_DAY.capitalize()} at {WEEKLY_HOUR:02d}:{WEEKLY_MINUTE:02d}"
    )


def stop_scheduler():
    """Stop the scheduler on FastAPI shutdown."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


def get_next_runs() -> dict:
    """Return next scheduled run times. Used in the test endpoint."""
    if not _scheduler or not _scheduler.running:
        return {"status": "not_running"}
    jobs = {}
    for job in _scheduler.get_jobs():
        next_run = job.next_run_time
        jobs[job.id] = {
            "name": job.name,
            "next_run": next_run.strftime("%Y-%m-%d %H:%M %Z") if next_run else "paused",
        }
    return {"status": "running", "timezone": TIMEZONE, "jobs": jobs}
