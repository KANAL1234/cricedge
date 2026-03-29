"""
Form Engine — computes a composite 0-100 form score for a player going into a match.

Sub-scores
----------
- recent_run_score     : recency-weighted average runs, normalised 0-100
- recent_wicket_score  : recency-weighted average wickets, normalised 0-100
- strike_rate_score    : weighted SR vs format benchmark
- economy_score        : weighted economy vs format benchmark
- venue_bonus          : ratio of venue performance vs career average (if 3+ innings)
- vs_opponent_bonus    : ratio of opponent performance vs career average (if 3+ innings)

Data Sources (merged strategy)
-------------------------------
- career averages     → Cricbuzz player_format_stats (current, API-sourced)
- recent form trend   → Cricsheet PlayerMatchStats (historical depth, free)
- venue-specific      → Cricsheet filtered by venue
- current IPL season  → Cricbuzz player_format_stats (most current)

Role weights
------------
BAT  : 60% batting + 35% SR  + 5%  bowling
BOWL : 10% batting + 30% eco  + 60% bowling
AR   : 40% batting + 20% SR/eco blend + 40% bowling
WK   : 55% batting + 35% SR  + 10% bowling  (+ stumping bonus)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from uuid import UUID

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

FORMAT_BENCHMARKS: dict[str, dict] = {
    "T20":  {"sr": 130.0, "economy": 8.0,  "run_cap": 60.0,  "wkt_cap": 3.0},
    "ODI":  {"sr": 90.0,  "economy": 5.5,  "run_cap": 80.0,  "wkt_cap": 3.0},
    "TEST": {"sr": 60.0,  "economy": 3.5,  "run_cap": 60.0,  "wkt_cap": 4.0},
    "T10":  {"sr": 160.0, "economy": 12.0, "run_cap": 40.0,  "wkt_cap": 2.0},
}
DEFAULT_BENCHMARK = FORMAT_BENCHMARKS["T20"]

RECENCY_DECAY = 0.85

ROLE_WEIGHTS: dict[str, dict] = {
    "BAT":  {"batting": 0.60, "bowling": 0.05, "sr_eco": 0.35},
    "BOWL": {"batting": 0.10, "bowling": 0.60, "sr_eco": 0.30},
    "AR":   {"batting": 0.40, "bowling": 0.40, "sr_eco": 0.20},
    "WK":   {"batting": 0.55, "bowling": 0.10, "sr_eco": 0.35},
}
DEFAULT_ROLE_WEIGHTS = ROLE_WEIGHTS["BAT"]

STUMPING_BONUS_PER = 5.0

# Weight given to Cricbuzz career stats vs Cricsheet recent form
CRICBUZZ_CAREER_BLEND = 0.30  # 30% career average from Cricbuzz, 70% recent from Cricsheet


@dataclass
class FormScore:
    player_id: UUID
    composite_score: float
    batting_score: float
    bowling_score: float
    venue_multiplier: float
    opponent_multiplier: float
    last_n_innings: list[dict]
    confidence: str   # "high" / "medium" / "low"
    form_trend: str   # "improving" / "stable" / "declining"
    # Cricbuzz data source fields
    data_source: str = "cricsheet"          # "cricbuzz" | "cricsheet" | "mixed"
    cricbuzz_t20_avg: float = 0.0
    cricbuzz_t20_sr: float = 0.0
    recent_form_source: str = "cricsheet"


class PlayerFormEngine:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def compute(
        self,
        player_id: UUID,
        match_id: UUID,
        lookback_matches: int = 10,
    ) -> FormScore:
        from app.models.innings import PlayerMatchStats
        from app.models.match import Match
        from app.models.player import Player

        player_row = await self.db.execute(select(Player).where(Player.id == player_id))
        player = player_row.scalar_one_or_none()

        match_row = await self.db.execute(select(Match).where(Match.id == match_id))
        match = match_row.scalar_one_or_none()

        venue_id = match.venue_id if match else None
        fmt = match.format.value if (match and match.format) else "T20"
        from app.models.match import MatchFormat as _MF
        fmt_enum = _MF(fmt) if fmt in _MF._value2member_map_ else _MF.T20
        opponent = _opponent_for(match, player)

        benchmark = FORMAT_BENCHMARKS.get(fmt, DEFAULT_BENCHMARK)
        role = player.role.value if player else "BAT"
        weights = ROLE_WEIGHTS.get(role, DEFAULT_ROLE_WEIGHTS)

        # ------------------------------------------------------------------
        # Source 1: Cricsheet — recent form (primary for trend)
        # ------------------------------------------------------------------
        stmt = (
            select(PlayerMatchStats, Match)
            .join(Match, PlayerMatchStats.match_id == Match.id)
            .where(PlayerMatchStats.player_id == player_id)
            .where(Match.format == fmt_enum)
            .order_by(Match.date.desc())
            .limit(lookback_matches)
        )
        rows = (await self.db.execute(stmt)).all()

        innings_list = [r[0] for r in rows]
        match_list = [r[1] for r in rows]

        n = len(innings_list)
        recency_weights = np.array([RECENCY_DECAY ** i for i in range(n)], dtype=float)
        w_sum = recency_weights.sum() if n > 0 else 1.0

        batting_score, bowling_score, sr_eco_score = 0.0, 0.0, 0.0
        w_runs_cricsheet = w_sr_cricsheet = 0.0

        if n > 0:
            w_runs_cricsheet = float(np.dot(recency_weights, [i.runs for i in innings_list]) / w_sum)
            w_wkts = float(np.dot(recency_weights, [i.wickets for i in innings_list]) / w_sum)
            w_sr_cricsheet = float(np.dot(recency_weights, [i.strike_rate for i in innings_list]) / w_sum)

            bowled_mask = np.array([1.0 if i.overs_bowled > 0 else 0.0 for i in innings_list])
            eco_weights = recency_weights * bowled_mask
            eco_sum = eco_weights.sum()
            w_eco = float(
                np.dot(eco_weights, [i.economy for i in innings_list]) / eco_sum
            ) if eco_sum > 0 else benchmark["economy"]

            batting_score = min(w_runs_cricsheet / benchmark["run_cap"] * 100.0, 100.0)
            bowling_score = min(w_wkts / benchmark["wkt_cap"] * 100.0, 100.0)

            sr_score = min(max(w_sr_cricsheet / (benchmark["sr"] * 1.5) * 100.0, 0.0), 100.0)
            eco_score = min(max(
                (benchmark["economy"] * 2 - w_eco) / benchmark["economy"] * 50.0, 0.0
            ), 100.0)

            if role in ("BAT", "WK"):
                sr_eco_score = sr_score
            elif role == "BOWL":
                sr_eco_score = eco_score
            else:
                sr_eco_score = (sr_score + eco_score) / 2.0

        # ------------------------------------------------------------------
        # Source 2: Cricbuzz player_format_stats (career T20 avg for IPL)
        # Blended in to lift or anchor the form score with career context.
        # ------------------------------------------------------------------
        cricbuzz_t20_avg = 0.0
        cricbuzz_t20_sr = 0.0
        data_source = "cricsheet"

        if fmt == "T20":
            cb_stats = await self._get_cricbuzz_t20_stats(player_id)
            if cb_stats:
                cricbuzz_t20_avg = cb_stats.avg or 0.0
                cricbuzz_t20_sr = cb_stats.strike_rate or 0.0
                data_source = "mixed"

                # Blend: career batting avg into batting_score
                cb_batting_score = min(cricbuzz_t20_avg / benchmark["run_cap"] * 100.0, 100.0)
                cb_sr_score = min(max(cricbuzz_t20_sr / (benchmark["sr"] * 1.5) * 100.0, 0.0), 100.0)

                if n > 0:
                    batting_score = (
                        (1 - CRICBUZZ_CAREER_BLEND) * batting_score
                        + CRICBUZZ_CAREER_BLEND * cb_batting_score
                    )
                    if role in ("BAT", "WK"):
                        sr_eco_score = (
                            (1 - CRICBUZZ_CAREER_BLEND) * sr_eco_score
                            + CRICBUZZ_CAREER_BLEND * cb_sr_score
                        )
                else:
                    # No Cricsheet data — fall back entirely to Cricbuzz career stats
                    batting_score = cb_batting_score
                    if role in ("BAT", "WK"):
                        sr_eco_score = cb_sr_score
                    data_source = "cricbuzz"
            elif n == 0:
                data_source = "cricsheet"  # no data from either source

        raw_score = (
            weights["batting"] * batting_score
            + weights["bowling"] * bowling_score
            + weights["sr_eco"] * sr_eco_score
        )

        if role == "WK" and n > 0:
            avg_stumpings = sum(i.stumpings for i in innings_list) / n
            raw_score = min(raw_score + avg_stumpings * STUMPING_BONUS_PER, 100.0)

        venue_multiplier = (
            await self._venue_multiplier(player_id, venue_id, fmt) if venue_id else 1.0
        )
        opp_multiplier = (
            await self._opponent_multiplier(player_id, opponent, fmt) if opponent else 1.0
        )

        composite = min(raw_score * venue_multiplier * opp_multiplier, 100.0)

        confidence = "high" if n >= 7 else ("medium" if n >= 4 else "low")
        form_trend = _compute_trend(innings_list)
        last_n = [_innings_to_dict(i, m) for i, m in zip(innings_list, match_list)]

        return FormScore(
            player_id=player_id,
            composite_score=round(composite, 2),
            batting_score=round(batting_score, 2),
            bowling_score=round(bowling_score, 2),
            venue_multiplier=round(venue_multiplier, 3),
            opponent_multiplier=round(opp_multiplier, 3),
            last_n_innings=last_n,
            confidence=confidence,
            form_trend=form_trend,
            data_source=data_source,
            cricbuzz_t20_avg=round(cricbuzz_t20_avg, 2),
            cricbuzz_t20_sr=round(cricbuzz_t20_sr, 2),
            recent_form_source="cricsheet" if n > 0 else "none",
        )

    async def _get_cricbuzz_t20_stats(self, player_id: UUID):
        """Fetch T20 stats from player_format_stats table (Cricbuzz-sourced)."""
        try:
            from app.models.player_format_stats import PlayerFormatStats, CricketFormat
            result = await self.db.execute(
                select(PlayerFormatStats)
                .where(PlayerFormatStats.player_id == player_id)
                .where(PlayerFormatStats.format == CricketFormat.T20)
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.debug(f"_get_cricbuzz_t20_stats: {e}")
            return None

    # Legacy shim used by existing API
    async def compute_ev(self, player_id: UUID, match_id: UUID) -> float:
        fs = await self.compute(player_id, match_id)
        return fs.composite_score

    async def _venue_multiplier(self, player_id: UUID, venue_id: UUID, fmt: str) -> float:
        from app.models.innings import PlayerMatchStats
        from app.models.match import Match, MatchFormat as _MF
        fmt_enum = _MF(fmt) if fmt in _MF._value2member_map_ else _MF.T20

        stmt = (
            select(PlayerMatchStats)
            .join(Match, PlayerMatchStats.match_id == Match.id)
            .where(PlayerMatchStats.player_id == player_id)
            .where(Match.venue_id == venue_id)
            .where(Match.format == fmt_enum)
        )
        venue_rows = (await self.db.execute(stmt)).scalars().all()
        if len(venue_rows) < 3:
            return 1.0

        venue_avg = sum(r.dream11_points for r in venue_rows) / len(venue_rows)

        stmt2 = (
            select(PlayerMatchStats)
            .join(Match, PlayerMatchStats.match_id == Match.id)
            .where(PlayerMatchStats.player_id == player_id)
            .where(Match.format == fmt_enum)
        )
        career_rows = (await self.db.execute(stmt2)).scalars().all()
        if not career_rows:
            return 1.0
        career_avg = sum(r.dream11_points for r in career_rows) / len(career_rows)
        if career_avg <= 0:
            return 1.0
        return min(max(venue_avg / career_avg, 0.5), 2.0)

    async def _opponent_multiplier(self, player_id: UUID, opponent: str, fmt: str) -> float:
        from app.models.innings import PlayerMatchStats
        from app.models.match import Match, MatchFormat as _MF
        fmt_enum = _MF(fmt) if fmt in _MF._value2member_map_ else _MF.T20

        stmt = (
            select(PlayerMatchStats)
            .join(Match, PlayerMatchStats.match_id == Match.id)
            .where(PlayerMatchStats.player_id == player_id)
            .where(Match.format == fmt_enum)
            .where((Match.team1 == opponent) | (Match.team2 == opponent))
        )
        opp_rows = (await self.db.execute(stmt)).scalars().all()
        if len(opp_rows) < 3:
            return 1.0

        opp_avg = sum(r.dream11_points for r in opp_rows) / len(opp_rows)

        stmt2 = (
            select(PlayerMatchStats)
            .join(Match, PlayerMatchStats.match_id == Match.id)
            .where(PlayerMatchStats.player_id == player_id)
            .where(Match.format == fmt_enum)
        )
        career_rows = (await self.db.execute(stmt2)).scalars().all()
        if not career_rows:
            return 1.0
        career_avg = sum(r.dream11_points for r in career_rows) / len(career_rows)
        if career_avg <= 0:
            return 1.0
        return min(max(opp_avg / career_avg, 0.5), 2.0)


# Backward-compat alias
FormEngine = PlayerFormEngine


def _opponent_for(match, player) -> str | None:
    if not match or not player:
        return None
    team = player.ipl_team or ""
    if team and match.team1 and team.lower() in match.team1.lower():
        return match.team2
    if team and match.team2 and team.lower() in match.team2.lower():
        return match.team1
    return None


def _compute_trend(innings: list) -> str:
    if len(innings) < 4:
        return "stable"
    scores = [i.dream11_points for i in innings]
    mid = len(scores) // 2
    recent_avg = sum(scores[:mid]) / mid
    older_avg  = sum(scores[mid:]) / (len(scores) - mid)
    if recent_avg > older_avg * 1.1:
        return "improving"
    if recent_avg < older_avg * 0.9:
        return "declining"
    return "stable"


def _innings_to_dict(innings, match) -> dict:
    return {
        "match_id": str(innings.match_id),
        "date": str(match.date) if match.date else None,
        "opponent": f"{match.team1} vs {match.team2}" if match else "",
        "runs": innings.runs,
        "balls_faced": innings.balls_faced,
        "strike_rate": innings.strike_rate,
        "wickets": innings.wickets,
        "economy": innings.economy,
        "catches": innings.catches,
        "stumpings": innings.stumpings,
        "dream11_points": innings.dream11_points,
    }
