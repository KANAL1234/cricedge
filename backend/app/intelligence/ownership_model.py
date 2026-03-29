"""
Ownership Prediction Model — rule-based heuristics for MVP.

Predicts what % of Dream11 users will select each player.
Total ownership across 22-player squad normalises to ~1100%
(each user picks 11 players).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Popular IPL franchises: over-picked by casual users
HIGH_OWNERSHIP_TEAMS = {"csk", "mi", "rcb", "chennai super kings", "mumbai indians",
                         "royal challengers bangalore", "royal challengers bengaluru"}

OWNERSHIP_CAP = 85.0          # no player exceeds this
TARGET_SQUAD_SUM = 1100.0     # sum across 22 players


@dataclass
class OwnershipPrediction:
    player_id: UUID
    predicted_ownership_pct: float
    ownership_tier: str           # "chalk" / "medium" / "differential" / "deep-differential"
    is_recommended_differential: bool
    reasoning: str


class OwnershipPredictor:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def predict_for_match(self, match_id: UUID) -> list[OwnershipPrediction]:
        from app.models.match import Match
        from app.models.player import Player
        from app.intelligence.form_engine import PlayerFormEngine

        match_row = await self.db.execute(select(Match).where(Match.id == match_id))
        match = match_row.scalar_one_or_none()
        if not match:
            return []

        player_ids = _extract_playing_xi(match)
        if not player_ids:
            # Fallback for completed matches without XI: use squad players for both teams
            from app.models.player import Player
            players_result = await self.db.execute(
                select(Player).where(
                    Player.ipl_team.in_([match.team1, match.team2])
                )
            )
            squad_players = players_result.scalars().all()
            player_ids = [p.id for p in squad_players]
            if not player_ids:
                return []

        form_engine = PlayerFormEngine(self.db)
        raw: list[tuple[UUID, float, float]] = []  # (player_id, base_ownership, form_score)

        for pid in player_ids:
            player_row = await self.db.execute(select(Player).where(Player.id == pid))
            player = player_row.scalar_one_or_none()
            if not player:
                continue

            form_score = await form_engine.compute_ev(pid, match_id)

            base = _price_to_base_ownership(player.dream11_price)
            base = _apply_form_multiplier(base, form_score)
            base = _apply_team_factor(base, player.ipl_team or "")
            base = min(base, OWNERSHIP_CAP)

            raw.append((pid, base, form_score))

        predictions = _normalise(raw, target_sum=TARGET_SQUAD_SUM)
        return predictions

    # Legacy shim for existing API endpoint
    async def predict(self, match_id: UUID) -> list[dict]:
        preds = await self.predict_for_match(match_id)
        return [
            {
                "player_id": str(p.player_id),
                "predicted_ownership": p.predicted_ownership_pct,
                "ownership_tier": p.ownership_tier,
                "is_recommended_differential": p.is_recommended_differential,
                "reasoning": p.reasoning,
            }
            for p in preds
        ]


# Backward-compat alias
OwnershipModel = OwnershipPredictor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_playing_xi(match) -> list[UUID]:
    """Extract player UUIDs from playing_xi_team1 / playing_xi_team2 JSON."""
    ids: list[UUID] = []
    for xi_field in (match.playing_xi_team1, match.playing_xi_team2):
        if not xi_field:
            continue
        if isinstance(xi_field, list):
            candidates = xi_field
        elif isinstance(xi_field, dict):
            # Support both {"players": [...]} and flat {name: id} formats
            if "players" in xi_field:
                candidates = xi_field["players"]
            else:
                candidates = list(xi_field.values())
        else:
            continue
        for v in candidates:
            try:
                ids.append(UUID(str(v)))
            except (ValueError, AttributeError):
                pass
    return ids


def _price_to_base_ownership(price: float) -> float:
    if price >= 9.5:
        return 55.0   # midpoint of 45-65
    if price >= 7.0:
        return 35.0   # midpoint of 25-45
    return 14.0       # midpoint of 8-20


def _apply_form_multiplier(base: float, form_score: float) -> float:
    if form_score > 75:
        return base + 15.0
    if form_score < 40:
        return base - 10.0
    return base


def _apply_team_factor(base: float, team: str) -> float:
    if any(t in team.lower() for t in HIGH_OWNERSHIP_TEAMS):
        return base + 8.0
    return base


def _normalise(
    raw: list[tuple[UUID, float, float]],
    target_sum: float,
) -> list[OwnershipPrediction]:
    if not raw:
        return []

    current_sum = sum(r[1] for r in raw)
    scale = target_sum / current_sum if current_sum > 0 else 1.0

    predictions = []
    for pid, base_own, form_score in raw:
        pct = round(min(base_own * scale, OWNERSHIP_CAP), 1)
        tier = _tier(pct)
        predictions.append(
            OwnershipPrediction(
                player_id=pid,
                predicted_ownership_pct=pct,
                ownership_tier=tier,
                is_recommended_differential=tier in ("differential", "deep-differential") and form_score >= 55,
                reasoning=_reasoning(pct, form_score, tier),
            )
        )

    return sorted(predictions, key=lambda p: p.predicted_ownership_pct, reverse=True)


def _tier(pct: float) -> str:
    if pct >= 50:
        return "chalk"
    if pct >= 20:
        return "medium"
    if pct >= 8:
        return "differential"
    return "deep-differential"


def _reasoning(pct: float, form_score: float, tier: str) -> str:
    parts = []
    if form_score >= 75:
        parts.append("elite form")
    elif form_score >= 55:
        parts.append("good form")
    else:
        parts.append("moderate form")

    if tier == "chalk":
        parts.append("high public ownership — risky for mega contests")
    elif tier in ("differential", "deep-differential"):
        parts.append("low public ownership — high leverage pick")

    return "; ".join(parts)
