"""
Captain Picker — recommends captain / vice-captain for a given match.

Scoring
-------
captain_score = mean_points × 2 × (1 - bust_probability) × venue_multiplier

Contest adjustments
-------------------
small_league : prioritise high mean, low variance (safe picks)
mega_contest : penalise chalk players (>50% ownership), boost differentials
"""
from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.intelligence.form_engine import PlayerFormEngine
from app.intelligence.ownership_model import OwnershipPredictor, _extract_playing_xi
from app.intelligence.points_simulator import MonteCarloSimulator

logger = logging.getLogger(__name__)


class CaptainPicker:
    def __init__(self, db: AsyncSession):
        self.db = db
        self._form = PlayerFormEngine(db)
        self._ownership = OwnershipPredictor(db)
        self._simulator = MonteCarloSimulator(db)

    async def pick(self, match_id: UUID, contest_type: str = "mega") -> dict:
        from app.models.match import Match

        match_row = await self.db.execute(select(Match).where(Match.id == match_id))
        match = match_row.scalar_one_or_none()
        if not match:
            return {"captain": [], "vice_captain": [], "contest_type": contest_type}

        player_ids = _extract_playing_xi(match)
        if not player_ids:
            from app.models.player import Player
            players_result = await self.db.execute(
                select(Player).where(
                    Player.ipl_team.in_([match.team1, match.team2])
                )
            )
            player_ids = [p.id for p in players_result.scalars().all()]
        if not player_ids:
            return {"captain": [], "vice_captain": [], "contest_type": contest_type}

        ownership_map: dict[UUID, float] = {}
        ownership_preds = await self._ownership.predict_for_match(match_id)
        for pred in ownership_preds:
            ownership_map[pred.player_id] = pred.predicted_ownership_pct

        scored = []
        for pid in player_ids:
            try:
                proj = await self._simulator.project(pid, match_id)
                form = await self._form.compute(pid, match_id)
                ownership_pct = ownership_map.get(pid, 30.0)

                captain_score = (
                    proj.mean_points * 2.0
                    * (1.0 - proj.bust_probability)
                    * form.venue_multiplier
                )

                if contest_type == "mega":
                    # penalise chalk picks (>50% ownership), boost differentials
                    if ownership_pct > 50:
                        captain_score *= 0.75
                    elif ownership_pct < 15:
                        captain_score *= 1.20

                scored.append({
                    "player_id": str(pid),
                    "captain_score": round(captain_score, 2),
                    "mean_points": proj.mean_points,
                    "p75_points": proj.p75_points,
                    "p90_points": proj.p90_points,
                    "bust_probability": proj.bust_probability,
                    "boom_probability": proj.boom_probability,
                    "predicted_ownership_pct": round(ownership_pct, 1),
                    "venue_multiplier": form.venue_multiplier,
                    "form_trend": form.form_trend,
                    "confidence": form.confidence,
                    "rationale": _rationale(proj.mean_points, ownership_pct, contest_type,
                                            form.form_trend, proj.boom_probability),
                })
            except Exception as exc:
                logger.warning("Captain scoring failed for %s: %s", pid, exc)

        scored.sort(key=lambda x: x["captain_score"], reverse=True)

        return {
            "captain": scored[:3],
            "vice_captain": scored[1:4],
            "contest_type": contest_type,
        }

    def _build_rationale(self, ev: float, ownership: float, contest_type: str) -> str:
        """Legacy shim for existing tests."""
        parts = []
        if ev >= 70:
            parts.append("elite form")
        elif ev >= 50:
            parts.append("good form")
        else:
            parts.append("moderate form")
        if contest_type == "mega":
            if ownership < 20:
                parts.append("low ownership differential")
            elif ownership > 40:
                parts.append("high ownership — risky for mega")
        return ", ".join(parts)


def _rationale(
    mean_pts: float,
    ownership_pct: float,
    contest_type: str,
    form_trend: str,
    boom_prob: float,
) -> str:
    parts = []
    if mean_pts >= 60:
        parts.append("elite expected points")
    elif mean_pts >= 40:
        parts.append("good expected points")
    else:
        parts.append("moderate expected points")

    if form_trend == "improving":
        parts.append("form improving")
    elif form_trend == "declining":
        parts.append("form declining — caution")

    if boom_prob >= 0.30:
        parts.append(f"{boom_prob:.0%} boom probability")

    if contest_type == "mega":
        if ownership_pct < 15:
            parts.append("low-owned differential — high leverage")
        elif ownership_pct > 50:
            parts.append("high-owned chalk — avoid as C in mega")

    return "; ".join(parts)
