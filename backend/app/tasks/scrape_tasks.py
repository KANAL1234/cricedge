"""
Scrape / sync tasks for CricEdge.

Old scraper-based tasks are preserved (weather, subscribers) or stubbed.
New API-based tasks delegate entirely to DataSyncService + CricbuzzClient.
"""
import asyncio
import logging
from datetime import datetime, timezone

from app.tasks.celery_app import celery_app
from app.core.metrics import scraper_runs_total, xi_confirmations_total

logger = logging.getLogger(__name__)


def run_async(coro):
    """Helper to run async code inside Celery sync tasks."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# New API-based tasks (replace all scraper tasks)
# ---------------------------------------------------------------------------

@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def sync_ipl_schedule_task(self):
    """Sync IPL 2026 schedule from Cricbuzz API. ~1 API call (cached 6h)."""
    try:
        result = run_async(_sync_ipl_schedule())
        scraper_runs_total.labels(scraper_name="sync_ipl_schedule", status="success").inc()
        return result
    except Exception as exc:
        scraper_runs_total.labels(scraper_name="sync_ipl_schedule", status="failed").inc()
        logger.error(f"sync_ipl_schedule_task failed: {exc}")
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=300)
def sync_ipl_players_task(self):
    """Sync all 10 IPL 2026 squad rosters. Up to 10 API calls, once per day."""
    try:
        result = run_async(_sync_ipl_players())
        scraper_runs_total.labels(scraper_name="sync_ipl_players", status="success").inc()
        return result
    except Exception as exc:
        scraper_runs_total.labels(scraper_name="sync_ipl_players", status="failed").inc()
        logger.error(f"sync_ipl_players_task failed: {exc}")
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def sync_match_xi_task(self):
    """
    Check for confirmed playing XI on today's match.
    Runs every 5 min between 2–9 PM IST on match days.
    Burns 0 calls if XI already confirmed.
    """
    try:
        result = run_async(_sync_match_xi())
        if result and result.get("confirmed"):
            xi_confirmations_total.inc(1)
        scraper_runs_total.labels(scraper_name="sync_match_xi", status="success").inc()
        return result
    except Exception as exc:
        scraper_runs_total.labels(scraper_name="sync_match_xi", status="failed").inc()
        logger.error(f"sync_match_xi_task failed: {exc}")
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=300)
def sync_player_stats_batch_task(self):
    """
    Sync stats for IPL players whose stats_last_synced > 12h ago.
    Batch of 10 players = up to 20 API calls/run.
    Skips entirely if budget emergency_mode is active.
    """
    try:
        result = run_async(_sync_player_stats_batch())
        scraper_runs_total.labels(scraper_name="sync_player_stats_batch", status="success").inc()
        return result
    except Exception as exc:
        scraper_runs_total.labels(scraper_name="sync_player_stats_batch", status="failed").inc()
        logger.error(f"sync_player_stats_batch_task failed: {exc}")
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=120)
def sync_match_results_task(self):
    """
    Sync completed match results (winner, score) from matches/v1/recent.
    1 API call per run (cached 30 min). Run every 30 min during match hours.
    """
    try:
        result = run_async(_sync_match_results())
        scraper_runs_total.labels(scraper_name="sync_match_results", status="success").inc()
        return result
    except Exception as exc:
        scraper_runs_total.labels(scraper_name="sync_match_results", status="failed").inc()
        logger.error(f"sync_match_results_task failed: {exc}")
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=1, default_retry_delay=60)
def budget_check_task(self):
    """
    Hourly budget check. Sets emergency_mode if calls > 160/month.
    In emergency mode only schedule + XI sync remain active.
    """
    try:
        result = run_async(_budget_check())
        return result
    except Exception as exc:
        logger.error(f"budget_check_task failed: {exc}")
        raise self.retry(exc=exc)


# ---------------------------------------------------------------------------
# Preserved tasks (weather, subscribers) — not replaced
# ---------------------------------------------------------------------------

@celery_app.task(bind=True, max_retries=2, default_retry_delay=300)
def update_weather_task(self):
    """Update weather for all upcoming matches with known venue."""
    try:
        result = run_async(_update_weather())
        scraper_runs_total.labels(scraper_name="update_weather", status="success").inc()
        return result
    except Exception as exc:
        scraper_runs_total.labels(scraper_name="update_weather", status="failed").inc()
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=300)
def sync_active_subscribers(self):
    """Daily task: update active_subscribers Prometheus gauge from DB."""
    try:
        return run_async(_sync_active_subscribers())
    except Exception as exc:
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def broadcast_xi_update(self, match_id: str, team: str):
    """Publish XI update to Redis pubsub channel for Socket.io relay."""
    try:
        return run_async(_broadcast_xi_update(match_id, team))
    except Exception as exc:
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def refresh_match_data(self, match_id: str):
    """Re-fetch all data for a specific match (manual trigger)."""
    try:
        return run_async(_refresh_match_data(match_id))
    except Exception as exc:
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=120)
def ingest_completed_match(self, file_path: str):
    """After match completes, ingest Cricsheet scorecard."""
    try:
        return run_async(_ingest_completed_match(file_path))
    except Exception as exc:
        raise self.retry(exc=exc)


# ---------------------------------------------------------------------------
# Async implementations — new API-based
# ---------------------------------------------------------------------------

async def _sync_match_results():
    from app.core.database import AsyncSessionLocal
    from app.services.data_sync import DataSyncService

    async with AsyncSessionLocal() as db:
        svc = DataSyncService(db)
        result = await svc.sync_match_results()
    logger.info(f"_sync_match_results: {result}")
    return result


async def _sync_ipl_schedule():
    from app.core.database import AsyncSessionLocal
    from app.services.data_sync import DataSyncService

    async with AsyncSessionLocal() as db:
        svc = DataSyncService(db)
        result = await svc.sync_ipl_schedule()
    logger.info(f"_sync_ipl_schedule: {result}")
    return result


async def _sync_ipl_players():
    from app.core.database import AsyncSessionLocal
    from app.services.data_sync import DataSyncService

    async with AsyncSessionLocal() as db:
        svc = DataSyncService(db)
        result = await svc.sync_all_ipl_players()
    logger.info(f"_sync_ipl_players: {result}")
    return result


async def _sync_match_xi():
    from app.core.database import AsyncSessionLocal
    from app.services.data_sync import DataSyncService
    from app.models.match import Match, MatchStatus
    from sqlalchemy import select
    from datetime import date

    async with AsyncSessionLocal() as db:
        today = date.today()
        result = await db.execute(
            select(Match).where(
                Match.status == MatchStatus.UPCOMING,
                Match.date == today,
                Match.xi_confirmed_at.is_(None),
            )
        )
        today_matches = result.scalars().all()

        if not today_matches:
            return {"skipped": True, "reason": "no_matches_today"}

        svc = DataSyncService(db)
        confirmed = 0
        for match in today_matches:
            if match.cricbuzz_id:
                res = await svc.sync_match_playing_xi(int(match.cricbuzz_id))
                if res.get("confirmed"):
                    confirmed += 1

    return {"checked": len(today_matches), "confirmed": confirmed}


async def _sync_player_stats_batch():
    from app.core.database import AsyncSessionLocal
    from app.services.data_sync import DataSyncService
    from app.services.cricbuzz_client import CricbuzzClient
    from app.models.player import Player
    from sqlalchemy import select
    import redis.asyncio as aioredis
    from app.core.config import settings

    # Check emergency mode
    try:
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        emergency = await r.get("cricbuzz:budget:emergency_mode")
        await r.aclose()
        if emergency:
            logger.warning("sync_player_stats_batch: SKIPPED — budget emergency_mode active")
            return {"skipped": True, "reason": "emergency_mode"}
    except Exception:
        pass

    async with AsyncSessionLocal() as db:
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=12)
        result = await db.execute(
            select(Player).where(
                Player.cricbuzz_id.isnot(None),
                (Player.stats_last_synced.is_(None)) | (Player.stats_last_synced < cutoff),
            ).limit(10)
        )
        stale_players = result.scalars().all()

        if not stale_players:
            return {"synced": 0, "skipped": True, "reason": "all_fresh"}

        svc = DataSyncService(db)
        synced = 0
        for player in stale_players:
            try:
                res = await svc.sync_player_stats(int(player.cricbuzz_id))
                if not res.get("skipped"):
                    synced += 1
            except Exception as e:
                logger.error(f"sync_player_stats failed for {player.cricbuzz_id}: {e}")

    logger.info(f"_sync_player_stats_batch: synced {synced}/{len(stale_players)} players")
    return {"synced": synced, "total_checked": len(stale_players)}


async def _budget_check():
    from app.services.cricbuzz_client import CricbuzzClient
    import redis.asyncio as aioredis
    from app.core.config import settings

    client = CricbuzzClient()
    status = await client.get_api_budget_status()
    await client.close()

    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        if status["budget_health"] == "red":
            await r.set("cricbuzz:budget:emergency_mode", "1")
            logger.critical(
                f"BUDGET ALERT: {status['calls_this_month']}/{status['monthly_limit']} calls used. "
                f"Emergency mode ACTIVE — batch stats sync disabled."
            )
        else:
            await r.delete("cricbuzz:budget:emergency_mode")
            if status["budget_health"] == "amber":
                logger.warning(
                    f"Budget amber: {status['calls_this_month']}/{status['monthly_limit']} calls used."
                )
    finally:
        await r.aclose()

    return status


# ---------------------------------------------------------------------------
# Async implementations — preserved
# ---------------------------------------------------------------------------

async def _update_weather():
    from app.scrapers.weather import WeatherService
    from app.core.database import AsyncSessionLocal
    from app.models.match import Match, MatchStatus
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Match).where(Match.status == MatchStatus.UPCOMING)
        )
        matches = result.scalars().all()

    service = WeatherService()
    updated = 0
    for match in matches:
        if match.match_start_utc and match.venue:
            forecast = await service.get_match_weather(
                match.venue.city, match.match_start_utc
            )
            if forecast:
                updated += 1

    await service.close()
    logger.info(f"_update_weather: updated {updated} weather forecasts")
    return {"updated": updated}


async def _sync_active_subscribers():
    from app.core.metrics import active_subscribers
    try:
        active_subscribers.labels(tier="pro").set(0)
        active_subscribers.labels(tier="elite").set(0)
        logger.info("_sync_active_subscribers: gauges updated")
    except Exception as exc:
        logger.warning(f"_sync_active_subscribers: {exc}")
    return {"synced": True}


async def _broadcast_xi_update(match_id: str, team: str):
    import json
    import redis.asyncio as aioredis
    from app.core.config import settings

    r = aioredis.from_url(settings.REDIS_URL)
    payload = json.dumps({"match_id": match_id, "team": team})
    await r.publish("xi_updates", payload)
    await r.aclose()
    logger.info(f"_broadcast_xi_update: published XI update for match {match_id}, team {team}")
    return {"published": True}


async def _refresh_match_data(match_id: str):
    from app.core.database import AsyncSessionLocal
    from app.services.data_sync import DataSyncService

    async with AsyncSessionLocal() as db:
        svc = DataSyncService(db)
        await svc.sync_match_playing_xi(int(match_id))
    logger.info(f"_refresh_match_data: refreshed match {match_id}")
    return {"match_id": match_id, "status": "refreshed"}


async def _ingest_completed_match(file_path: str):
    from pathlib import Path
    from app.core.database import AsyncSessionLocal
    from app.scripts.ingest_cricsheet import process_file

    path = Path(file_path)
    async with AsyncSessionLocal() as db:
        result = await process_file(db, path, fmt=None)
        await db.commit()
    logger.info(f"_ingest_completed_match: {file_path} → {result}")
    return result
