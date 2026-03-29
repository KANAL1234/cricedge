from uuid import UUID
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.venue import Venue, PitchType
from app.models.innings import PlayerMatchStats, BallByBall
from app.models.match import Match, MatchFormat

router = APIRouter()


@router.get("")
async def list_venues(
    country: Optional[str] = None,
    pitch_type: Optional[PitchType] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    query = select(Venue)
    if country:
        query = query.where(Venue.country.ilike(f"%{country}%"))
    if pitch_type:
        query = query.where(Venue.pitch_type == pitch_type)

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()

    query = query.order_by(Venue.name).offset((page - 1) * limit).limit(limit)
    result = await db.execute(query)
    venues = result.scalars().all()

    return {
        "data": [_serialize_venue(v) for v in venues],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.get("/{venue_id}")
async def get_venue(venue_id: UUID, db: AsyncSession = Depends(get_db)):
    """Venue profile with all historical averages."""
    result = await db.execute(select(Venue).where(Venue.id == venue_id))
    venue = result.scalar_one_or_none()
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")

    # Count total matches at venue
    matches_count = await db.execute(
        select(func.count(Match.id)).where(Match.venue_id == venue_id)
    )

    return {
        **_serialize_venue(venue),
        "total_matches": matches_count.scalar() or 0,
    }


@router.get("/{venue_id}/stats")
async def get_venue_stats(
    venue_id: UUID,
    format: Optional[str] = Query(None, description="T20/ODI/TEST"),
    db: AsyncSession = Depends(get_db),
):
    """Pace vs spin breakdown, scoring patterns, and innings-by-innings averages."""
    result = await db.execute(select(Venue).where(Venue.id == venue_id))
    venue = result.scalar_one_or_none()
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")

    # --- Match-level stats from DB ---
    matches_q = select(Match.id).where(Match.venue_id == venue_id)
    if format:
        try:
            fmt_enum = MatchFormat(format.upper())
            matches_q = matches_q.where(Match.format == fmt_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid format: {format}")

    matches_result = await db.execute(matches_q)
    match_ids = [r[0] for r in matches_result.all()]

    # Pace vs spin breakdown from BallByBall
    pace_wickets = 0
    spin_wickets = 0
    total_first_innings_runs: list[int] = []
    total_second_innings_runs: list[int] = []

    if match_ids:
        # Pace/spin breakdown: join BallByBall with bowler Player, check bowling_style
        from sqlalchemy import case, Integer
        from app.models.player import Player

        pace_styles = ["Right-arm fast", "Left-arm fast", "Right-arm medium", "Left-arm medium",
                       "Right-arm medium-fast", "Left-arm medium-fast"]

        bbb_q = (
            select(
                func.sum(
                    case((Player.bowling_style.in_(pace_styles), 1), else_=0)
                ).label("pace"),
                func.sum(
                    case((Player.bowling_style.not_in(pace_styles), 1), else_=0)
                ).label("spin"),
            )
            .select_from(BallByBall)
            .join(Player, BallByBall.bowler_id == Player.id)
            .where(
                BallByBall.match_id.in_(match_ids),
                BallByBall.wicket_type.isnot(None),
                BallByBall.wicket_type.not_in(["run out", "retired hurt"]),
            )
        )
        pace_spin_result = await db.execute(bbb_q)
        row = pace_spin_result.one()
        pace_wickets = int(row.pace or 0)
        spin_wickets = int(row.spin or 0)

        # Scoring patterns: sum runs per innings per match
        scoring_q = (
            select(
                BallByBall.match_id,
                BallByBall.innings_number,
                func.sum(BallByBall.runs_total).label("total_runs"),
            )
            .where(BallByBall.match_id.in_(match_ids))
            .group_by(BallByBall.match_id, BallByBall.innings_number)
        )
        scoring_result = await db.execute(scoring_q)
        for row in scoring_result.all():
            if row.innings_number == 1:
                total_first_innings_runs.append(int(row.total_runs or 0))
            elif row.innings_number == 2:
                total_second_innings_runs.append(int(row.total_runs or 0))

    total_wickets = pace_wickets + spin_wickets

    return {
        "venue_id": str(venue_id),
        "venue_name": venue.name,
        "format": format,
        "pitch_type": venue.pitch_type.value if venue.pitch_type else None,
        "dew_factor": venue.dew_factor,
        "pace_vs_spin": {
            "pace_wickets": pace_wickets,
            "spin_wickets": spin_wickets,
            "pace_pct": round(pace_wickets / total_wickets * 100, 1) if total_wickets else None,
            "spin_pct": round(spin_wickets / total_wickets * 100, 1) if total_wickets else None,
        },
        "scoring_patterns": {
            "avg_first_innings": round(sum(total_first_innings_runs) / len(total_first_innings_runs), 1) if total_first_innings_runs else venue.avg_first_innings_score_t20,
            "avg_second_innings": round(sum(total_second_innings_runs) / len(total_second_innings_runs), 1) if total_second_innings_runs else venue.avg_second_innings_score_t20,
            "matches_sampled": len(match_ids),
        },
    }


# ---------------------------------------------------------------------------
# Serializer
# ---------------------------------------------------------------------------

def _serialize_venue(v: Venue) -> dict:
    return {
        "id": str(v.id),
        "name": v.name,
        "city": v.city,
        "country": v.country,
        "pitch_type": v.pitch_type.value if v.pitch_type else None,
        "avg_first_innings_score_t20": v.avg_first_innings_score_t20,
        "avg_second_innings_score_t20": v.avg_second_innings_score_t20,
        "pace_wickets_pct": v.pace_wickets_pct,
        "spin_wickets_pct": v.spin_wickets_pct,
        "dew_factor": v.dew_factor,
        "capacity": v.capacity,
    }
