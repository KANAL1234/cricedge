"""
Predictions API — intelligence layer endpoints.

All results cached in Redis for 5 minutes.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.metrics import ownership_prediction_duration
from app.intelligence.captain_picker import CaptainPicker
from app.intelligence.form_engine import PlayerFormEngine
from app.intelligence.ownership_model import OwnershipPredictor
from app.intelligence.points_simulator import MonteCarloSimulator

logger = logging.getLogger(__name__)
router = APIRouter()

CACHE_TTL = 300  # 5 minutes


# ---------------------------------------------------------------------------
# Redis helper (best-effort — endpoints still work without Redis)
# ---------------------------------------------------------------------------

async def _get_redis():
    try:
        import redis.asyncio as aioredis
        client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        return client
    except Exception:
        return None


async def _cache_get(key: str) -> dict | None:
    client = await _get_redis()
    if not client:
        return None
    try:
        raw = await client.get(key)
        await client.aclose()
        return json.loads(raw) if raw else None
    except Exception:
        return None


async def _cache_set(key: str, value: dict) -> None:
    client = await _get_redis()
    if not client:
        return
    try:
        await client.setex(key, CACHE_TTL, json.dumps(value, default=str))
        await client.aclose()
    except Exception:
        pass


def _freshness() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _require_match(match_id: UUID, db: AsyncSession):
    from app.models.match import Match
    row = await db.execute(select(Match).where(Match.id == match_id))
    match = row.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail=f"Match {match_id} not found")
    return match


def _xi_confirmed(match) -> bool:
    if match.status and match.status.value == "completed":
        return True
    return bool(
        (match.playing_xi_team1 and len(match.playing_xi_team1) > 0)
        or (match.playing_xi_team2 and len(match.playing_xi_team2) > 0)
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/match/{match_id}/form")
async def match_form_scores(match_id: UUID, db: AsyncSession = Depends(get_db)):
    """Form scores for all players in the match."""
    cache_key = f"form:{match_id}"
    cached = await _cache_get(cache_key)
    if cached:
        return cached

    match = await _require_match(match_id, db)
    if not _xi_confirmed(match):
        raise HTTPException(status_code=404, detail="Playing XI not yet confirmed for this match")

    from app.intelligence.ownership_model import _extract_playing_xi
    player_ids = _extract_playing_xi(match)

    engine = PlayerFormEngine(db)
    scores = []
    for pid in player_ids:
        try:
            fs = await engine.compute(pid, match_id)
            scores.append({
                "player_id": str(fs.player_id),
                "composite_score": fs.composite_score,
                "batting_score": fs.batting_score,
                "bowling_score": fs.bowling_score,
                "venue_multiplier": fs.venue_multiplier,
                "opponent_multiplier": fs.opponent_multiplier,
                "confidence": fs.confidence,
                "form_trend": fs.form_trend,
                "last_n_innings": fs.last_n_innings,
            })
        except Exception as exc:
            logger.warning("Form score failed for %s: %s", pid, exc)

    result = {
        "match_id": str(match_id),
        "scores": scores,
        "data_freshness": _freshness(),
    }
    await _cache_set(cache_key, result)
    return result


@router.get("/match/{match_id}/ownership")
async def predict_ownership(match_id: UUID, db: AsyncSession = Depends(get_db)):
    """Ownership predictions for all players in the match."""
    cache_key = f"ownership:{match_id}"
    cached = await _cache_get(cache_key)
    if cached:
        return cached

    match = await _require_match(match_id, db)
    if not _xi_confirmed(match):
        raise HTTPException(status_code=404, detail="Playing XI not yet confirmed for this match")

    predictor = OwnershipPredictor(db)
    with ownership_prediction_duration.time():
        preds = await predictor.predict_for_match(match_id)

    # Bulk-load player info to avoid N+1 fetches on the frontend
    from app.models.player import Player
    from uuid import UUID as _UUID
    player_ids = [p.player_id for p in preds]
    player_rows = await db.execute(select(Player).where(Player.id.in_(player_ids)))
    player_map = {p.id: p for p in player_rows.scalars().all()}

    predictions = [
        {
            "player_id": str(p.player_id),
            "name": player_map[p.player_id].name if p.player_id in player_map else None,
            "short_name": player_map[p.player_id].short_name if p.player_id in player_map else None,
            "role": player_map[p.player_id].role.value if p.player_id in player_map and player_map[p.player_id].role else None,
            "ipl_team": player_map[p.player_id].ipl_team if p.player_id in player_map else None,
            "dream11_price": player_map[p.player_id].dream11_price if p.player_id in player_map else None,
            "predicted_ownership_pct": p.predicted_ownership_pct,
            "ownership_tier": p.ownership_tier,
            "is_recommended_differential": p.is_recommended_differential,
            "reasoning": p.reasoning,
        }
        for p in preds
    ]

    result = {
        "match_id": str(match_id),
        "predictions": predictions,
        "xi_source": "xi" if match.xi_confirmed_at else "squad",
        "data_freshness": _freshness(),
    }
    await _cache_set(cache_key, result)
    return result


@router.get("/match/{match_id}/captain")
async def recommend_captain(
    match_id: UUID,
    contest_type: str = Query("mega", pattern="^(mega|small)$"),
    db: AsyncSession = Depends(get_db),
):
    """Captain / vice-captain recommendations."""
    cache_key = f"captain:{match_id}:{contest_type}"
    cached = await _cache_get(cache_key)
    if cached:
        return cached

    match = await _require_match(match_id, db)
    if not _xi_confirmed(match):
        raise HTTPException(status_code=404, detail="Playing XI not yet confirmed for this match")

    picker = CaptainPicker(db)
    recs = await picker.pick(match_id, contest_type=contest_type)

    result = {
        "match_id": str(match_id),
        **recs,
        "data_freshness": _freshness(),
    }
    await _cache_set(cache_key, result)
    return result


@router.get("/match/{match_id}/differential")
async def differential_picks(match_id: UUID, db: AsyncSession = Depends(get_db)):
    """Top 3 differential picks with reasoning (ownership < 20%, form score >= 55)."""
    cache_key = f"differential:{match_id}"
    cached = await _cache_get(cache_key)
    if cached:
        return cached

    match = await _require_match(match_id, db)
    if not _xi_confirmed(match):
        raise HTTPException(status_code=404, detail="Playing XI not yet confirmed for this match")

    predictor = OwnershipPredictor(db)
    preds = await predictor.predict_for_match(match_id)

    differentials = [p for p in preds if p.is_recommended_differential]
    differentials.sort(key=lambda p: p.predicted_ownership_pct)

    top3 = differentials[:3]

    from app.models.player import Player
    player_ids = [p.player_id for p in top3]
    player_rows = await db.execute(select(Player).where(Player.id.in_(player_ids)))
    player_map = {p.id: p for p in player_rows.scalars().all()}

    picks = [
        {
            "player_id": str(p.player_id),
            "name": player_map[p.player_id].name if p.player_id in player_map else None,
            "short_name": player_map[p.player_id].short_name if p.player_id in player_map else None,
            "role": player_map[p.player_id].role.value if p.player_id in player_map and player_map[p.player_id].role else None,
            "ipl_team": player_map[p.player_id].ipl_team if p.player_id in player_map else None,
            "predicted_ownership_pct": p.predicted_ownership_pct,
            "ownership_tier": p.ownership_tier,
            "reasoning": p.reasoning,
        }
        for p in top3
    ]

    result = {
        "match_id": str(match_id),
        "differentials": picks,
        "data_freshness": _freshness(),
    }
    await _cache_set(cache_key, result)
    return result


@router.get("/player/{player_id}/projection")
async def player_projection(
    player_id: UUID,
    match_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Monte Carlo points projection for a player in an upcoming match."""
    cache_key = f"projection:{player_id}:{match_id}"
    cached = await _cache_get(cache_key)
    if cached:
        return cached

    await _require_match(match_id, db)

    simulator = MonteCarloSimulator(db)
    proj = await simulator.project(player_id, match_id)

    result = {
        "player_id": str(proj.player_id),
        "match_id": str(match_id),
        "mean_points": proj.mean_points,
        "p25_points": proj.p25_points,
        "p75_points": proj.p75_points,
        "p90_points": proj.p90_points,
        "std_dev": proj.std_dev,
        "boom_probability": proj.boom_probability,
        "bust_probability": proj.bust_probability,
        "data_freshness": _freshness(),
    }
    await _cache_set(cache_key, result)
    return result


# ---------------------------------------------------------------------------
# Legacy endpoints (kept for backward compatibility)
# ---------------------------------------------------------------------------

@router.get("/player/{player_id}/ev")
async def player_expected_value(
    player_id: UUID,
    match_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Legacy EV endpoint — use /projection for full Monte Carlo output."""
    engine = PlayerFormEngine(db)
    ev = await engine.compute_ev(player_id, match_id)
    return {"player_id": player_id, "match_id": match_id, "ev": ev}
