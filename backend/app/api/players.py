from uuid import UUID
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.player import Player, PlayerRole
from app.models.innings import PlayerMatchStats
from app.models.match import Match, MatchFormat

router = APIRouter()


@router.get("/search")
async def search_players(
    q: str = Query(..., min_length=2),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Search players by name (partial, case-insensitive)."""
    term = f"%{q}%"
    query = (
        select(Player)
        .where(
            Player.is_active == True,
            or_(Player.name.ilike(term), Player.full_name.ilike(term)),
        )
        .order_by(Player.name)
    )
    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()

    query = query.offset((page - 1) * limit).limit(limit)
    result = await db.execute(query)
    players = result.scalars().all()

    return {
        "data": [_serialize_player(p) for p in players],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.get("")
async def list_players(
    role: Optional[PlayerRole] = None,
    country: Optional[str] = None,
    ipl_team: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    query = select(Player).where(Player.is_active == True)
    if role:
        query = query.where(Player.role == role)
    if country:
        query = query.where(Player.country.ilike(f"%{country}%"))
    if ipl_team:
        query = query.where(Player.ipl_team.ilike(f"%{ipl_team}%"))

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()

    query = query.order_by(Player.name).offset((page - 1) * limit).limit(limit)
    result = await db.execute(query)
    players = result.scalars().all()

    return {
        "data": [_serialize_player(p) for p in players],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.get("/{player_id}")
async def get_player(player_id: UUID, db: AsyncSession = Depends(get_db)):
    """Player profile with career stats summary."""
    result = await db.execute(select(Player).where(Player.id == player_id))
    player = result.scalar_one_or_none()
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    # Aggregate career stats from PlayerMatchStats
    stats_result = await db.execute(
        select(
            func.count(PlayerMatchStats.id).label("matches"),
            func.sum(PlayerMatchStats.runs).label("total_runs"),
            func.sum(PlayerMatchStats.wickets).label("total_wickets"),
            func.sum(PlayerMatchStats.catches).label("total_catches"),
            func.avg(PlayerMatchStats.dream11_points).label("avg_dream11_pts"),
        ).where(PlayerMatchStats.player_id == player_id)
    )
    row = stats_result.one()

    return {
        **_serialize_player(player),
        "career_stats": {
            "matches": row.matches or 0,
            "total_runs": int(row.total_runs or 0),
            "total_wickets": int(row.total_wickets or 0),
            "total_catches": int(row.total_catches or 0),
            "avg_dream11_pts": round(float(row.avg_dream11_pts or 0), 2),
        },
    }


@router.get("/{player_id}/form")
async def get_player_form(
    player_id: UUID,
    n: int = Query(10, ge=1, le=50, description="Last N innings"),
    format: Optional[str] = Query(None, description="Filter by match format: T20/ODI/TEST"),
    venue_id: Optional[UUID] = Query(None, description="Filter by venue"),
    vs_team: Optional[str] = Query(None, description="Filter by opponent team"),
    db: AsyncSession = Depends(get_db),
):
    """Return last N innings with per-inning stats and Dream11 points."""
    player = (await db.execute(select(Player).where(Player.id == player_id))).scalar_one_or_none()
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    query = (
        select(PlayerMatchStats, Match)
        .join(Match, PlayerMatchStats.match_id == Match.id)
        .where(PlayerMatchStats.player_id == player_id)
    )

    if format:
        try:
            fmt_enum = MatchFormat(format.upper())
            query = query.where(Match.format == fmt_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid format: {format}")

    if venue_id:
        query = query.where(Match.venue_id == venue_id)

    if vs_team:
        term = f"%{vs_team}%"
        query = query.where(
            or_(Match.team1.ilike(term), Match.team2.ilike(term))
        )

    query = query.order_by(Match.match_start_utc.desc().nullslast()).limit(n)
    result = await db.execute(query)
    rows = result.all()

    innings_list = []
    for pms, match in rows:
        innings_list.append({
            "match_id": str(match.id),
            "match_code": match.match_code,
            "date": match.date.isoformat() if match.date else None,
            "team1": match.team1,
            "team2": match.team2,
            "format": match.format.value if match.format else None,
            "innings_number": pms.innings_number,
            "runs": pms.runs,
            "balls_faced": pms.balls_faced,
            "fours": pms.fours,
            "sixes": pms.sixes,
            "strike_rate": pms.strike_rate,
            "is_out": pms.is_out,
            "wickets": pms.wickets,
            "overs_bowled": pms.overs_bowled,
            "economy": pms.economy,
            "catches": pms.catches,
            "stumpings": pms.stumpings,
            "dream11_points": pms.dream11_points,
        })

    return {
        "player_id": str(player_id),
        "player_name": player.name,
        "games": len(innings_list),
        "innings": innings_list,
    }


# ---------------------------------------------------------------------------
# Serializer
# ---------------------------------------------------------------------------

def _serialize_player(p: Player) -> dict:
    return {
        "id": str(p.id),
        "name": p.name,
        "full_name": p.full_name,
        "country": p.country,
        "role": p.role.value if p.role else None,
        "batting_style": p.batting_style,
        "bowling_style": p.bowling_style,
        "ipl_team": p.ipl_team,
        "dream11_price": p.dream11_price,
        "is_active": p.is_active,
    }
