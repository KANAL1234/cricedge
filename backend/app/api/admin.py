"""
Admin API — budget monitoring, manual sync triggers, ingest tasks.
"""
import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class CricsheetIngestRequest(BaseModel):
    file_path: str


# ---------------------------------------------------------------------------
# Existing endpoints (preserved)
# ---------------------------------------------------------------------------

@router.post("/scrape/match/{match_id}")
async def trigger_scrape_match(match_id: str):
    """Queue a full re-scrape / refresh for a specific match."""
    from app.tasks.scrape_tasks import refresh_match_data
    task = refresh_match_data.delay(match_id)
    return {"task_id": task.id, "match_id": match_id, "status": "queued"}


@router.post("/ingest/cricsheet")
async def trigger_cricsheet_ingest(request: CricsheetIngestRequest):
    """Queue Cricsheet file ingestion for a completed match."""
    if not os.path.exists(request.file_path):
        raise HTTPException(
            status_code=400,
            detail=f"File not found: {request.file_path}",
        )
    from app.tasks.scrape_tasks import ingest_completed_match
    task = ingest_completed_match.delay(request.file_path)
    return {"task_id": task.id, "file_path": request.file_path, "status": "queued"}


# ---------------------------------------------------------------------------
# Task 7 — API budget dashboard
# ---------------------------------------------------------------------------

@router.get("/api-budget")
async def get_api_budget():
    """
    Returns Cricbuzz API usage, budget health, and cache stats.

    GET /api/v1/admin/api-budget
    """
    from app.services.cricbuzz_client import CricbuzzClient
    from app.core.config import settings
    import redis.asyncio as aioredis

    client = CricbuzzClient()
    budget = await client.get_api_budget_status()
    await client.close()

    # Check emergency mode
    emergency_mode = False
    last_call_at = None
    top_endpoints: list[dict] = []
    total_cache_hits = 0
    total_api_calls = budget["calls_today"]

    try:
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

        emergency_raw = await r.get("cricbuzz:budget:emergency_mode")
        emergency_mode = bool(emergency_raw)

        # Scan for per-endpoint daily counters
        endpoint_keys = []
        async for key in r.scan_iter("cricbuzz:usage:endpoint:*"):
            endpoint_keys.append(key)

        for key in endpoint_keys[:20]:  # cap scan
            count = int(await r.get(key) or 0)
            if count > 0:
                # cricbuzz:usage:endpoint:series:get-matches -> series/get-matches
                ep = key.replace("cricbuzz:usage:endpoint:", "").replace(":", "/")
                top_endpoints.append({"endpoint": ep, "calls": count})

        top_endpoints.sort(key=lambda x: x["calls"], reverse=True)
        top_endpoints = top_endpoints[:5]

        # Cache hit stats — read from api_call_log table
        await r.aclose()
    except Exception:
        pass

    # Pull last call time + cache stats from DB
    try:
        from app.core.database import AsyncSessionLocal
        from app.models.api_call_log import ApiCallLog
        from sqlalchemy import select, func as sqlfunc

        async with AsyncSessionLocal() as db:
            today_str = datetime.now(timezone.utc).strftime("%Y-%m")

            # Last call time
            last_row = await db.execute(
                select(ApiCallLog.called_at)
                .where(ApiCallLog.month_year == today_str)
                .order_by(ApiCallLog.called_at.desc())
                .limit(1)
            )
            row = last_row.scalar_one_or_none()
            if row:
                last_call_at = row.isoformat()

            # Cache hit/miss counts today
            today_date = datetime.now(timezone.utc).date().isoformat()
            cache_result = await db.execute(
                select(ApiCallLog.cache_hit, sqlfunc.count().label("cnt"))
                .where(sqlfunc.cast(ApiCallLog.called_at, sqlfunc.Date()) == today_date)
                .group_by(ApiCallLog.cache_hit)
            )
            for is_hit, cnt in cache_result.all():
                if is_hit:
                    total_cache_hits = cnt
                else:
                    total_api_calls = cnt
    except Exception:
        pass

    hit_rate = 0
    total_requests = total_cache_hits + total_api_calls
    if total_requests > 0:
        hit_rate = round(total_cache_hits / total_requests * 100)

    return {
        "cricbuzz": {
            "calls_today": budget["calls_today"],
            "calls_this_month": budget["calls_this_month"],
            "monthly_limit": budget["monthly_limit"],
            "remaining": budget["remaining"],
            "budget_health": budget["budget_health"],
            "emergency_mode": emergency_mode,
            "last_call_at": last_call_at,
            "top_endpoints_today": top_endpoints,
        },
        "cache_stats": {
            "hit_rate_today": f"{hit_rate}%",
            "total_cache_hits": total_cache_hits,
            "total_api_calls": total_api_calls,
        },
    }


# ---------------------------------------------------------------------------
# Manual sync triggers
# ---------------------------------------------------------------------------

@router.post("/sync/schedule")
async def trigger_sync_schedule():
    """Manually trigger IPL schedule sync from Cricbuzz."""
    from app.tasks.scrape_tasks import sync_ipl_schedule_task
    task = sync_ipl_schedule_task.delay()
    return {"task_id": task.id, "task": "sync_ipl_schedule", "status": "queued"}


@router.post("/sync/players")
async def trigger_sync_players():
    """Manually trigger IPL player roster sync from Cricbuzz."""
    from app.tasks.scrape_tasks import sync_ipl_players_task
    task = sync_ipl_players_task.delay()
    return {"task_id": task.id, "task": "sync_ipl_players", "status": "queued"}


@router.post("/sync/xi/{match_id}")
async def trigger_sync_xi(match_id: str):
    """Manually trigger playing XI check for a specific match."""
    from app.core.database import AsyncSessionLocal
    from app.services.data_sync import DataSyncService

    try:
        match_id_int = int(match_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="match_id must be an integer Cricbuzz match ID")

    async with AsyncSessionLocal() as db:
        svc = DataSyncService(db)
        result = await svc.sync_match_playing_xi(match_id_int)

    return {"match_id": match_id, "result": result}


@router.post("/sync/results")
async def trigger_sync_results():
    """Manually trigger match results sync (updates completed match statuses + winners)."""
    from app.core.database import AsyncSessionLocal
    from app.services.data_sync import DataSyncService

    async with AsyncSessionLocal() as db:
        svc = DataSyncService(db)
        result = await svc.sync_match_results()

    return {"result": result}
