"""
Dream11 Points Simulator — Monte Carlo estimation of expected fantasy points.

For each simulation run:
1. Sample batting performance from player's historical distribution at venue/format
2. Sample bowling performance similarly
3. Apply match-context adjustments (batting first, pitch type)
4. Score using the official Dream11 T20 formula
5. Aggregate into a PointsProjection

Minimum 500 iterations per projection.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

SIMULATIONS = 500

DREAM11_T20_RULES = {
    "run": 1,
    "boundary_bonus": 1,
    "six_bonus": 2,
    "half_century_bonus": 8,
    "century_bonus": 16,
    "duck_penalty": -2,
    "wicket": 25,
    "lbw_bowled_bonus": 8,
    "maiden_over": 8,
    "dot_ball": 1,
    "two_wickets_bonus": 8,
    "three_wickets_bonus": 16,
    "four_wickets_bonus": 25,
    "five_wickets_bonus": 33,
    "catch": 8,
    "stumping": 12,
    "run_out_direct": 12,
    "run_out_indirect": 6,
}

PITCH_BATTING_MULTIPLIERS = {
    "batting": 1.10,
    "bowling": 0.90,
    "balanced": 1.00,
}

BOOM_THRESHOLD = 80.0
BUST_THRESHOLD = 20.0


@dataclass
class PointsProjection:
    player_id: UUID
    mean_points: float
    p25_points: float    # pessimistic
    p75_points: float    # optimistic
    p90_points: float    # boom scenario
    std_dev: float
    boom_probability: float  # P(score > 80)
    bust_probability: float  # P(score < 20)


class MonteCarloSimulator:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def project(
        self,
        player_id: UUID,
        match_id: UUID,
        n_simulations: int = SIMULATIONS,
        rng: np.random.Generator | None = None,
    ) -> PointsProjection:
        from app.models.innings import PlayerMatchStats
        from app.models.match import Match
        from app.models.venue import Venue

        if rng is None:
            rng = np.random.default_rng()

        match_row = await self.db.execute(select(Match).where(Match.id == match_id))
        match = match_row.scalar_one_or_none()

        fmt = match.format.value if (match and match.format) else "T20"
        from app.models.match import MatchFormat as _MF
        fmt_enum = _MF(fmt) if fmt in _MF._value2member_map_ else _MF.T20
        venue_id = match.venue_id if match else None
        toss_decision = (match.toss_decision or "bat").lower() if match else "bat"
        batting_first = toss_decision == "bat"

        pitch_type = "balanced"
        if venue_id:
            venue_row = await self.db.execute(select(Venue).where(Venue.id == venue_id))
            venue = venue_row.scalar_one_or_none()
            if venue and venue.pitch_type:
                pitch_type = venue.pitch_type.value

        # fetch historical stats
        stmt = (
            select(PlayerMatchStats, Match)
            .join(Match, PlayerMatchStats.match_id == Match.id)
            .where(PlayerMatchStats.player_id == player_id)
            .where(Match.format == fmt_enum)
            .order_by(Match.date.desc())
            .limit(30)
        )
        rows = (await self.db.execute(stmt)).all()
        innings_list = [r[0] for r in rows]

        bat_dist = _batting_distribution(innings_list)
        bowl_dist = _bowling_distribution(innings_list)
        field_dist = _fielding_distribution(innings_list)

        pitch_bat_mult = PITCH_BATTING_MULTIPLIERS.get(pitch_type, 1.0)
        # chasing slightly harder on average
        context_bat_mult = pitch_bat_mult * (0.97 if not batting_first else 1.0)

        results = np.zeros(n_simulations)
        for i in range(n_simulations):
            pts = _simulate_once(rng, bat_dist, bowl_dist, field_dist, context_bat_mult)
            results[i] = pts

        return PointsProjection(
            player_id=player_id,
            mean_points=round(float(np.mean(results)), 1),
            p25_points=round(float(np.percentile(results, 25)), 1),
            p75_points=round(float(np.percentile(results, 75)), 1),
            p90_points=round(float(np.percentile(results, 90)), 1),
            std_dev=round(float(np.std(results)), 1),
            boom_probability=round(float(np.mean(results > BOOM_THRESHOLD)), 3),
            bust_probability=round(float(np.mean(results < BUST_THRESHOLD)), 3),
        )


# Backward-compat: the existing API used PointsSimulator with calculate_dream11_t20
class PointsSimulator(MonteCarloSimulator):
    """Legacy deterministic calculator kept for compatibility."""

    def calculate_dream11_t20(
        self,
        batting=None,
        bowling=None,
        fielding=None,
        is_captain: bool = False,
        is_vc: bool = False,
    ) -> dict:
        r = DREAM11_T20_RULES
        points = 0.0
        breakdown = {}

        if batting:
            bat_pts = (
                batting.runs * r["run"]
                + batting.fours * r["boundary_bonus"]
                + batting.sixes * r["six_bonus"]
                + (r["half_century_bonus"] if batting.runs >= 50 else 0)
                + (r["century_bonus"] if batting.runs >= 100 else 0)
                + (r["duck_penalty"] if batting.runs == 0 and batting.balls > 0 else 0)
            )
            breakdown["batting"] = bat_pts
            points += bat_pts

        if bowling:
            bowl_pts = (
                bowling.wickets * r["wicket"]
                + bowling.lbw_bowled * r["lbw_bowled_bonus"]
                + bowling.maidens * r["maiden_over"]
                + bowling.dots * r["dot_ball"]
                + (r["two_wickets_bonus"] if bowling.wickets >= 2 else 0)
                + (r["three_wickets_bonus"] if bowling.wickets >= 3 else 0)
                + (r["four_wickets_bonus"] if bowling.wickets >= 4 else 0)
                + (r["five_wickets_bonus"] if bowling.wickets >= 5 else 0)
            )
            breakdown["bowling"] = bowl_pts
            points += bowl_pts

        if fielding:
            field_pts = (
                fielding.catches * r["catch"]
                + fielding.stumpings * r["stumping"]
                + fielding.run_outs_direct * r["run_out_direct"]
                + fielding.run_outs_indirect * r["run_out_indirect"]
            )
            breakdown["fielding"] = field_pts
            points += field_pts

        multiplier = 2.0 if is_captain else (1.5 if is_vc else 1.0)
        return {
            "total": round(points * multiplier, 1),
            "base_points": round(points, 1),
            "multiplier": multiplier,
            "breakdown": breakdown,
        }


# ---------------------------------------------------------------------------
# Distribution helpers
# ---------------------------------------------------------------------------

def _batting_distribution(innings: list) -> dict:
    """Returns params for sampling batting performance."""
    if not innings:
        return {"runs_mean": 15.0, "runs_std": 18.0, "sr_mean": 120.0, "sr_std": 30.0,
                "four_rate": 0.08, "six_rate": 0.04, "duck_prob": 0.10}

    runs = [i.runs for i in innings]
    srs  = [i.strike_rate for i in innings if i.balls_faced >= 4]
    fours_per_ball = [i.fours / max(i.balls_faced, 1) for i in innings]
    sixes_per_ball = [i.sixes / max(i.balls_faced, 1) for i in innings]
    duck_prob = sum(1 for i in innings if i.runs == 0 and i.balls_faced > 0) / len(innings)

    return {
        "runs_mean": float(np.mean(runs)),
        "runs_std": float(np.std(runs)) + 1e-6,
        "sr_mean": float(np.mean(srs)) if srs else 120.0,
        "sr_std": float(np.std(srs)) + 1e-6 if srs else 30.0,
        "four_rate": float(np.mean(fours_per_ball)),
        "six_rate": float(np.mean(sixes_per_ball)),
        "duck_prob": float(duck_prob),
    }


def _bowling_distribution(innings: list) -> dict:
    """Returns params for sampling bowling performance."""
    bowling_innings = [i for i in innings if i.overs_bowled >= 1.0]
    if not bowling_innings:
        return {"bowl_prob": 0.0, "wkt_mean": 0.5, "wkt_std": 0.8,
                "eco_mean": 8.0, "eco_std": 2.0, "maiden_rate": 0.05, "lbw_bowled_rate": 0.2}

    bowl_prob = len(bowling_innings) / len(innings)
    wkts = [i.wickets for i in bowling_innings]
    ecos = [i.economy for i in bowling_innings]
    maiden_rate = sum(i.maidens for i in bowling_innings) / max(
        sum(int(i.overs_bowled) for i in bowling_innings), 1
    )

    return {
        "bowl_prob": float(bowl_prob),
        "wkt_mean": float(np.mean(wkts)),
        "wkt_std": float(np.std(wkts)) + 1e-6,
        "eco_mean": float(np.mean(ecos)),
        "eco_std": float(np.std(ecos)) + 1e-6,
        "maiden_rate": float(maiden_rate),
        "lbw_bowled_rate": 0.25,  # ~25% of wickets are lbw/bowled on average
    }


def _fielding_distribution(innings: list) -> dict:
    if not innings:
        return {"catch_per_match": 0.15, "stumping_per_match": 0.05, "ro_per_match": 0.05}
    return {
        "catch_per_match": float(np.mean([i.catches for i in innings])),
        "stumping_per_match": float(np.mean([i.stumpings for i in innings])),
        "ro_per_match": float(np.mean([i.run_outs for i in innings])),
    }


def _simulate_once(
    rng: np.random.Generator,
    bat_dist: dict,
    bowl_dist: dict,
    field_dist: dict,
    bat_context_mult: float,
) -> float:
    r = DREAM11_T20_RULES
    pts = 0.0

    # --- batting ---
    if rng.random() > bat_dist["duck_prob"]:
        raw_runs = max(0.0, rng.normal(bat_dist["runs_mean"], bat_dist["runs_std"]))
        runs = int(raw_runs * bat_context_mult)
        balls = max(1, int(runs / max(rng.normal(bat_dist["sr_mean"], bat_dist["sr_std"]), 1) * 100))
        fours = int(rng.binomial(balls, bat_dist["four_rate"]))
        sixes  = int(rng.binomial(balls, bat_dist["six_rate"]))

        pts += runs * r["run"]
        pts += fours * r["boundary_bonus"]
        pts += sixes * r["six_bonus"]
        if runs >= 100:
            pts += r["century_bonus"]
        elif runs >= 50:
            pts += r["half_century_bonus"]
    else:
        pts += r["duck_penalty"]

    # --- bowling ---
    if rng.random() < bowl_dist["bowl_prob"]:
        wkts = max(0, int(rng.normal(bowl_dist["wkt_mean"], bowl_dist["wkt_std"])))
        eco  = max(0.0, rng.normal(bowl_dist["eco_mean"], bowl_dist["eco_std"]))
        maiden = 1 if rng.random() < bowl_dist["maiden_rate"] else 0
        lbw_bowled = int(rng.binomial(wkts, bowl_dist["lbw_bowled_rate"]))

        # approximate dots from economy in a 4-over spell
        overs = 4.0
        total_balls = int(overs * 6)
        runs_conceded = int(eco * overs)
        dots = max(0, total_balls - runs_conceded)

        pts += wkts * r["wicket"]
        pts += lbw_bowled * r["lbw_bowled_bonus"]
        pts += maiden * r["maiden_over"]
        pts += min(dots, 24) * r["dot_ball"]
        if wkts >= 5:
            pts += r["five_wickets_bonus"]
        elif wkts >= 4:
            pts += r["four_wickets_bonus"]
        elif wkts >= 3:
            pts += r["three_wickets_bonus"]
        elif wkts >= 2:
            pts += r["two_wickets_bonus"]

    # --- fielding ---
    catches = int(rng.poisson(max(field_dist["catch_per_match"], 0)))
    stumpings = int(rng.poisson(max(field_dist["stumping_per_match"], 0)))
    run_outs = int(rng.poisson(max(field_dist["ro_per_match"], 0)))
    pts += catches * r["catch"]
    pts += stumpings * r["stumping"]
    pts += run_outs * r["run_out_direct"]

    return max(pts, 0.0)
