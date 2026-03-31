from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "cricedge",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.tasks.scrape_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

celery_app.conf.beat_schedule = {
    # --- Cricbuzz API-based tasks ---

    # IPL schedule: every 6 hours (1 API call, cached)
    "sync-ipl-schedule": {
        "task": "app.tasks.scrape_tasks.sync_ipl_schedule_task",
        "schedule": crontab(minute=0, hour="*/6"),
    },

    # IPL player rosters: daily at 6 AM IST (00:30 UTC) — 10 API calls max
    "sync-ipl-players": {
        "task": "app.tasks.scrape_tasks.sync_ipl_players_task",
        "schedule": crontab(hour="0", minute="30"),
    },

    # Playing XI check: every 5 minutes between 8:30 AM–5:30 PM UTC
    # (2:00 PM–11:00 PM IST — covers both afternoon & evening IPL matches)
    # Burns 0 calls if XI already confirmed for the day's match
    "sync-match-xi": {
        "task": "app.tasks.scrape_tasks.sync_match_xi_task",
        "schedule": crontab(minute="*/5", hour="8-17"),
    },

    # Match results: every 5 min during match hours (cached 10 min — ~1 real call/10 min)
    # Extended window: 8 AM–7 PM UTC = 1:30 PM–12:30 AM IST, covers late finishes
    "sync-match-results": {
        "task": "app.tasks.scrape_tasks.sync_match_results_task",
        "schedule": crontab(minute="*/5", hour="8-19"),
    },

    # Player stats batch: daily at 7 AM IST (1:30 UTC) — up to 20 API calls
    "sync-player-stats-batch": {
        "task": "app.tasks.scrape_tasks.sync_player_stats_batch_task",
        "schedule": crontab(hour="1", minute="30"),
    },

    # Budget check: every hour — sets emergency_mode if calls > 160/month
    "budget-check": {
        "task": "app.tasks.scrape_tasks.budget_check_task",
        "schedule": crontab(minute="0"),
    },

    # --- Preserved tasks ---

    # Update weather forecasts every 3 hours
    "update-weather": {
        "task": "app.tasks.scrape_tasks.update_weather_task",
        "schedule": crontab(minute=0, hour="*/3"),
    },

    # Sync active subscriber Prometheus gauge daily at midnight UTC
    "sync-active-subscribers": {
        "task": "app.tasks.scrape_tasks.sync_active_subscribers",
        "schedule": crontab(hour="0", minute="5"),
    },
}
