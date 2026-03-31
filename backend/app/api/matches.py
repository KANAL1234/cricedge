from datetime import datetime, timedelta, timezone
from uuid import UUID, UUID as _UUID
from typing import Optional, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.match import Match, MatchStatus, MatchFormat
from app.models.player import Player
from app.models.venue import Venue

router = APIRouter()


async def _enrich_xi(xi: Any, db: AsyncSession) -> list:
    """Resolve a playing XI value (UUID string list, dict, or None) to enriched player objects."""
    if not isinstance(xi, list) or not xi:
        return []
    # Safely coerce string UUIDs to uuid.UUID objects for SQLAlchemy Uuid column
    uuid_objs = []
    for item in xi:
        try:
            uuid_objs.append(_UUID(str(item)))
        except (ValueError, AttributeError):
            pass
    if not uuid_objs:
        return []
    rows = await db.execute(select(Player).where(Player.id.in_(uuid_objs)))
    player_map = {str(p.id): p for p in rows.scalars().all()}
    return [
        {
            "id": str(item),
            "name": player_map.get(str(item), None) and player_map[str(item)].name,
            "short_name": player_map.get(str(item), None) and player_map[str(item)].short_name,
            "role": player_map[str(item)].role.value if str(item) in player_map else None,
        }
        for item in xi
    ]


@router.get("")
async def list_matches(
    status: Optional[MatchStatus] = None,
    format: Optional[MatchFormat] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List IPL 2026 matches: completed (last 7 days) + upcoming (next 30 days)."""
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    next_month = now + timedelta(days=30)

    query = (
        select(Match)
        .options(selectinload(Match.venue))
        .where(Match.cricbuzz_id.is_not(None))  # only synced IPL 2026 fixtures
        .where(Match.match_start_utc >= week_ago)
        .where(Match.match_start_utc <= next_month)
    )
    if status:
        query = query.where(Match.status == status)
    if format:
        query = query.where(Match.format == format)

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()

    query = query.order_by(Match.match_start_utc.asc()).offset((page - 1) * limit).limit(limit)
    result = await db.execute(query)
    matches = result.scalars().all()

    return {
        "data": [_serialize_match(m) for m in matches],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.get("/search")
async def search_matches(
    q: str = Query(..., min_length=2),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Search matches by team name or competition."""
    term = f"%{q}%"
    query = (
        select(Match)
        .options(selectinload(Match.venue))
        .where(
            or_(
                Match.team1.ilike(term),
                Match.team2.ilike(term),
                Match.competition.ilike(term),
            )
        )
        .order_by(Match.match_start_utc.desc().nullslast())
    )
    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()

    query = query.offset((page - 1) * limit).limit(limit)
    result = await db.execute(query)
    matches = result.scalars().all()

    return {
        "data": [_serialize_match(m) for m in matches],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.get("/{match_id}")
async def get_match(match_id: UUID, db: AsyncSession = Depends(get_db)):
    """Full match detail with playing XI (if confirmed), venue stats, weather placeholder."""
    result = await db.execute(
        select(Match).options(selectinload(Match.venue)).where(Match.id == match_id)
    )
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    data = _serialize_match(match, full=True)

    # Resolve playing XI: UUID string list → enriched player objects
    data["playing_xi_team1"] = await _enrich_xi(match.playing_xi_team1, db)
    data["playing_xi_team2"] = await _enrich_xi(match.playing_xi_team2, db)

    # Venue stats inline
    if match.venue:
        data["venue_stats"] = _serialize_venue_stats(match.venue)

    data["weather"] = match.weather or {}
    return data


@router.get("/{match_id}/playing-xi")
async def get_playing_xi(match_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Match).where(Match.id == match_id))
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    team1_data = match.playing_xi_team1 or {}
    team2_data = match.playing_xi_team2 or {}

    return {
        "match_id": str(match_id),
        "xi_confirmed": match.xi_confirmed_at is not None,
        "xi_confirmed_at": match.xi_confirmed_at,
        "playing_xi_team1": await _enrich_xi(team1_data, db),
        "playing_xi_team2": await _enrich_xi(team2_data, db),
    }


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _serialize_match(m: Match, full: bool = False) -> dict:
    d = {
        "id": str(m.id),
        "match_code": m.match_code,
        "date": m.date.isoformat() if m.date else None,
        "team1": m.team1,
        "team2": m.team2,
        "team1_short": m.team1_short,
        "team2_short": m.team2_short,
        "format": m.format.value if m.format else None,
        "status": m.status.value if m.status else None,
        "competition": m.competition,
        "match_start_utc": m.match_start_utc.isoformat() if m.match_start_utc else None,
        "lock_time_utc": m.lock_time_utc.isoformat() if m.lock_time_utc else None,
        "toss_winner": m.toss_winner,
        "toss_decision": m.toss_decision,
        "result": m.result,
        "winner": m.winner,
        "margin": m.margin,
        "venue": {
            "id": str(m.venue.id),
            "name": m.venue.name,
            "city": m.venue.city,
        } if m.venue else None,
    }
    if full:
        d["playing_xi_team1"] = m.playing_xi_team1
        d["playing_xi_team2"] = m.playing_xi_team2
        d["xi_confirmed_at"] = m.xi_confirmed_at.isoformat() if m.xi_confirmed_at else None
    return d


@router.get("/{match_id}/freshness")
async def get_match_freshness(match_id: UUID, db: AsyncSession = Depends(get_db)):
    """Return data freshness status for a match."""
    result = await db.execute(
        select(Match).options(selectinload(Match.venue)).where(Match.id == match_id)
    )
    match = result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    xi_confirmed = match.xi_confirmed_at is not None
    weather_updated = bool(match.weather)
    has_venue = match.venue is not None
    data_complete = xi_confirmed and weather_updated and has_venue

    return {
        "match_id": str(match_id),
        "last_scraped_at": match.updated_at.isoformat() if match.updated_at else None,
        "xi_confirmed": xi_confirmed,
        "xi_confirmed_at": match.xi_confirmed_at.isoformat() if match.xi_confirmed_at else None,
        "weather_updated_at": match.weather.get("updated_at") if match.weather else None,
        "data_complete": data_complete,
    }


def _serialize_venue_stats(v: Venue) -> dict:
    return {
        "pitch_type": v.pitch_type.value if v.pitch_type else None,
        "avg_first_innings_score_t20": v.avg_first_innings_score_t20,
        "avg_second_innings_score_t20": v.avg_second_innings_score_t20,
        "pace_wickets_pct": v.pace_wickets_pct,
        "spin_wickets_pct": v.spin_wickets_pct,
        "dew_factor": v.dew_factor,
    }
