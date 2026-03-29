"""
Intelligence layer tests — Form Engine, Ownership Model, Points Simulator, Captain Picker.
"""
from __future__ import annotations

import uuid
import datetime
import pytest
import numpy as np

from app.models.player import Player, PlayerRole
from app.models.match import Match, MatchFormat, MatchStatus
from app.models.venue import Venue, PitchType
from app.models.innings import PlayerMatchStats

from app.intelligence.form_engine import PlayerFormEngine, RECENCY_DECAY
from app.intelligence.ownership_model import OwnershipPredictor
from app.intelligence.points_simulator import MonteCarloSimulator, _simulate_once
from app.intelligence.captain_picker import CaptainPicker


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _make_venue(db, name="Wankhede", pitch_type=PitchType.BATTING) -> Venue:
    v = Venue(id=uuid.uuid4(), name=name, city="Mumbai", country="India",
              pitch_type=pitch_type)
    db.add(v)
    return v


def _make_player(db, name="Kohli", role=PlayerRole.BATSMAN, team="RCB",
                 price=8.0) -> Player:
    p = Player(id=uuid.uuid4(), name=name, country="India", role=role,
               ipl_team=team, dream11_price=price)
    db.add(p)
    return p


def _make_match(db, venue: Venue | None, team1="MI", team2="RCB",
                fmt=MatchFormat.T20, date=None,
                xi_team1=None, xi_team2=None) -> Match:
    m = Match(
        id=uuid.uuid4(),
        team1=team1, team2=team2,
        format=fmt,
        status=MatchStatus.UPCOMING,
        date=date or datetime.date(2025, 4, 1),
        venue_id=venue.id if venue else None,
        playing_xi_team1=xi_team1 or [],
        playing_xi_team2=xi_team2 or [],
    )
    db.add(m)
    return m


def _make_stats(db, player: Player, match: Match, runs=30, balls_faced=25,
                strike_rate=120.0, wickets=0, overs_bowled=0.0, economy=0.0,
                fours=2, sixes=1, maidens=0, catches=0, stumpings=0,
                run_outs=0, dream11_points=30.0) -> PlayerMatchStats:
    s = PlayerMatchStats(
        id=uuid.uuid4(),
        player_id=player.id,
        match_id=match.id,
        runs=runs,
        balls_faced=balls_faced,
        fours=fours,
        sixes=sixes,
        strike_rate=strike_rate,
        wickets=wickets,
        overs_bowled=overs_bowled,
        economy=economy,
        maidens=maidens,
        catches=catches,
        stumpings=stumpings,
        run_outs=run_outs,
        dream11_points=dream11_points,
    )
    db.add(s)
    return s


async def _seed_22_players(db, match: Match, star_idx: int = 0,
                            star_team: str = "MI", star_price: float = 11.0,
                            diff_idx: int = 3, diff_team: str = "Sunrisers Hyderabad",
                            diff_price: float = 6.5) -> list[Player]:
    """Seed 22 players (11 per team) and attach them to match's playing XI."""
    players = []
    prices = [10.0, 9.5, 9.0, 8.5, 8.0, 7.5, 7.0, 6.5, 6.0, 5.5, 5.0]
    for i in range(22):
        price = prices[i % len(prices)]
        if i == star_idx:
            price = star_price
            team = star_team
        elif i == diff_idx:
            price = diff_price
            team = diff_team
        elif i < 11:
            team = "MI"
        else:
            team = "Chennai Super Kings"
        p = _make_player(db, name=f"P{i}", team=team, price=price)
        players.append(p)

    await db.flush()

    match.playing_xi_team1 = [str(p.id) for p in players[:11]]
    match.playing_xi_team2 = [str(p.id) for p in players[11:]]
    await db.flush()
    return players


# ---------------------------------------------------------------------------
# TASK 1 — Form Engine
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_form_engine_recency_weighting(db_session):
    """Recency weighting: recent great innings should dominate over old poor ones."""
    venue = _make_venue(db_session)
    player = _make_player(db_session, role=PlayerRole.BATSMAN, team="RCB")
    target_match = _make_match(db_session, venue, team1="MI", team2="RCB")
    await db_session.flush()

    # 6 matches: first 2 (most recent) great, last 4 poor
    perf = [
        (90, 60, 150.0, 95.0),  # most recent
        (80, 55, 145.0, 88.0),
        (8,  6,  70.0,  8.0),
        (8,  6,  70.0,  8.0),
        (5,  4,  60.0,  5.0),
        (5,  4,  60.0,  5.0),  # oldest
    ]
    base_date = datetime.date(2025, 3, 28)
    for idx, (runs, balls, sr, pts) in enumerate(perf):
        m = _make_match(db_session, venue, team1="MI", team2="RCB",
                        date=base_date - datetime.timedelta(days=idx * 7))
        _make_stats(db_session, player, m, runs=runs, balls_faced=balls,
                    strike_rate=sr, dream11_points=pts)

    await db_session.flush()

    engine = PlayerFormEngine(db_session)
    fs = await engine.compute(player.id, target_match.id, lookback_matches=6)

    # Recency-weighted score must be pulled toward recent great form
    assert fs.composite_score > 35.0, (
        f"Expected > 35 with recent great form, got {fs.composite_score}"
    )
    assert fs.form_trend == "improving"
    assert fs.confidence == "medium"   # 4–6 innings → medium


@pytest.mark.asyncio
async def test_form_engine_recency_decay_math(db_session):
    """Verify that weights decay by RECENCY_DECAY^i across innings."""
    venue = _make_venue(db_session)
    player = _make_player(db_session)
    target_match = _make_match(db_session, venue)
    await db_session.flush()

    # Seed 5 innings with known run values
    run_values = [50, 40, 30, 20, 10]  # index 0 = most recent
    base_date = datetime.date(2025, 3, 28)
    for idx, runs in enumerate(run_values):
        m = _make_match(db_session, venue,
                        date=base_date - datetime.timedelta(days=idx * 7))
        _make_stats(db_session, player, m, runs=runs, balls_faced=30,
                    strike_rate=float(runs) / 30 * 100, dream11_points=float(runs))

    await db_session.flush()

    # Compute expected weighted avg runs manually
    weights = np.array([RECENCY_DECAY ** i for i in range(5)])
    w_sum = weights.sum()
    expected_w_runs = float(np.dot(weights, run_values) / w_sum)

    engine = PlayerFormEngine(db_session)
    fs = await engine.compute(player.id, target_match.id, lookback_matches=5)

    # batting_score = min(expected_w_runs / 60.0 * 100, 100)
    benchmark_run_cap = 60.0
    expected_batting_score = min(expected_w_runs / benchmark_run_cap * 100.0, 100.0)
    assert abs(fs.batting_score - expected_batting_score) < 2.0, (
        f"Expected batting_score ≈ {expected_batting_score:.1f}, got {fs.batting_score}"
    )


@pytest.mark.asyncio
async def test_form_engine_low_confidence_no_data(db_session):
    venue = _make_venue(db_session)
    player = _make_player(db_session)
    target_match = _make_match(db_session, venue)
    await db_session.flush()

    engine = PlayerFormEngine(db_session)
    fs = await engine.compute(player.id, target_match.id)

    assert fs.composite_score == 0.0
    assert fs.confidence == "low"
    assert fs.form_trend == "stable"


@pytest.mark.asyncio
async def test_form_engine_high_confidence_many_innings(db_session):
    venue = _make_venue(db_session)
    player = _make_player(db_session)
    target_match = _make_match(db_session, venue)
    await db_session.flush()

    base_date = datetime.date(2025, 3, 28)
    for idx in range(8):
        m = _make_match(db_session, venue,
                        date=base_date - datetime.timedelta(days=idx * 7))
        _make_stats(db_session, player, m, runs=40, balls_faced=28,
                    strike_rate=142.0, dream11_points=50.0)

    await db_session.flush()

    engine = PlayerFormEngine(db_session)
    fs = await engine.compute(player.id, target_match.id)
    assert fs.confidence == "high"


@pytest.mark.asyncio
async def test_form_engine_venue_multiplier_above_one(db_session):
    """Player outperforming career avg at this venue gets multiplier > 1."""
    venue = _make_venue(db_session)
    other_venue = _make_venue(db_session, name="Other Ground")
    player = _make_player(db_session)
    target_match = _make_match(db_session, venue)
    await db_session.flush()

    base = datetime.date(2025, 3, 1)
    # 4 great innings AT this venue
    for i in range(4):
        m = _make_match(db_session, venue, team1="MI", team2="RCB",
                        date=base - datetime.timedelta(weeks=i))
        _make_stats(db_session, player, m, runs=80, balls_faced=50,
                    strike_rate=160.0, dream11_points=90.0)
    # 4 poor innings at other venues (pulls career avg down)
    for i in range(4):
        m = _make_match(db_session, other_venue, team1="MI", team2="RCB",
                        date=datetime.date(2024, 12, 1) - datetime.timedelta(weeks=i))
        _make_stats(db_session, player, m, runs=10, balls_faced=8,
                    strike_rate=80.0, dream11_points=8.0)

    await db_session.flush()

    engine = PlayerFormEngine(db_session)
    fs = await engine.compute(player.id, target_match.id)
    assert fs.venue_multiplier > 1.0, (
        f"Expected venue_multiplier > 1.0, got {fs.venue_multiplier}"
    )


@pytest.mark.asyncio
async def test_form_engine_bowler_role_weights(db_session):
    """Bowler's bowling_score should dominate when wickets are high."""
    venue = _make_venue(db_session)
    bowler = _make_player(db_session, role=PlayerRole.BOWLER, team="MI")
    target_match = _make_match(db_session, venue, team1="MI")
    await db_session.flush()

    base = datetime.date(2025, 3, 1)
    for i in range(5):
        m = _make_match(db_session, venue, team1="MI", team2="CSK",
                        date=base - datetime.timedelta(weeks=i))
        _make_stats(db_session, bowler, m, runs=5, wickets=3,
                    overs_bowled=4.0, economy=6.5, dream11_points=85.0)

    await db_session.flush()

    engine = PlayerFormEngine(db_session)
    fs = await engine.compute(bowler.id, target_match.id)
    assert fs.bowling_score >= 80.0, f"Expected bowling_score >= 80, got {fs.bowling_score}"


# ---------------------------------------------------------------------------
# TASK 2 — Ownership Model
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ownership_sums_to_approx_1100(db_session):
    """Total predicted ownership across 22-player squad ≈ 1100%."""
    venue = _make_venue(db_session)
    match = _make_match(db_session, venue)
    await db_session.flush()
    await _seed_22_players(db_session, match)

    predictor = OwnershipPredictor(db_session)
    preds = await predictor.predict_for_match(match.id)

    assert len(preds) == 22
    total = sum(p.predicted_ownership_pct for p in preds)
    assert 900 <= total <= 1300, f"Total ownership {total:.1f}% out of range [900, 1300]"


@pytest.mark.asyncio
async def test_ownership_chalk_cap(db_session):
    """No player should exceed 85% predicted ownership."""
    venue = _make_venue(db_session)
    match = _make_match(db_session, venue, team1="Mumbai Indians",
                        team2="Chennai Super Kings")
    await db_session.flush()
    await _seed_22_players(db_session, match)

    predictor = OwnershipPredictor(db_session)
    preds = await predictor.predict_for_match(match.id)

    for p in preds:
        assert p.predicted_ownership_pct <= 85.0, (
            f"Player {p.player_id} at {p.predicted_ownership_pct}% exceeds 85% cap"
        )


@pytest.mark.asyncio
async def test_ownership_tier_thresholds(db_session):
    """Tier must match documented thresholds for every player."""
    venue = _make_venue(db_session)
    match = _make_match(db_session, venue)
    await db_session.flush()
    await _seed_22_players(db_session, match)

    predictor = OwnershipPredictor(db_session)
    preds = await predictor.predict_for_match(match.id)

    for p in preds:
        pct = p.predicted_ownership_pct
        if pct >= 50:
            expected = "chalk"
        elif pct >= 20:
            expected = "medium"
        elif pct >= 8:
            expected = "differential"
        else:
            expected = "deep-differential"
        assert p.ownership_tier == expected, (
            f"Tier mismatch at {pct}%: got {p.ownership_tier}, expected {expected}"
        )


@pytest.mark.asyncio
async def test_ownership_high_price_more_than_low_price(db_session):
    """A 10-credit player should have higher raw ownership than a 5-credit player."""
    venue = _make_venue(db_session)
    match = _make_match(db_session, venue)
    await db_session.flush()
    players = await _seed_22_players(db_session, match,
                                      star_idx=0, star_price=10.5, star_team="SRH",
                                      diff_idx=1, diff_price=5.0, diff_team="SRH")

    predictor = OwnershipPredictor(db_session)
    preds = await predictor.predict_for_match(match.id)

    pred_map = {p.player_id: p for p in preds}
    star_pred = pred_map[players[0].id]
    diff_pred = pred_map[players[1].id]
    assert star_pred.predicted_ownership_pct > diff_pred.predicted_ownership_pct, (
        f"10.5-credit ({star_pred.predicted_ownership_pct}%) should be > "
        f"5-credit ({diff_pred.predicted_ownership_pct}%)"
    )


# ---------------------------------------------------------------------------
# TASK 3 — Points Simulator
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_simulator_percentile_ordering(db_session):
    """p25 ≤ mean ≤ p75 ≤ p90, all probabilities in [0, 1]."""
    venue = _make_venue(db_session)
    player = _make_player(db_session, role=PlayerRole.BATSMAN)
    match = _make_match(db_session, venue)
    await db_session.flush()

    base = datetime.date(2025, 3, 1)
    for i in range(15):
        m = _make_match(db_session, venue, team1="MI", team2="RCB",
                        date=base - datetime.timedelta(weeks=i))
        _make_stats(db_session, player, m, runs=35, balls_faced=24,
                    strike_rate=145.0, fours=3, sixes=2, dream11_points=45.0)

    await db_session.flush()

    rng = np.random.default_rng(42)
    simulator = MonteCarloSimulator(db_session)
    proj = await simulator.project(player.id, match.id, n_simulations=500, rng=rng)

    assert proj.p25_points <= proj.mean_points, "p25 must be ≤ mean"
    assert proj.mean_points <= proj.p75_points, "mean must be ≤ p75"
    assert proj.p75_points <= proj.p90_points, "p75 must be ≤ p90"
    assert 0.0 <= proj.boom_probability <= 1.0
    assert 0.0 <= proj.bust_probability <= 1.0
    assert proj.std_dev >= 0.0


@pytest.mark.asyncio
async def test_simulator_reasonable_range_for_known_batter(db_session):
    """A 35-avg batter should produce mean_points between 10 and 120."""
    venue = _make_venue(db_session)
    player = _make_player(db_session, role=PlayerRole.BATSMAN)
    match = _make_match(db_session, venue)
    await db_session.flush()

    base = datetime.date(2025, 3, 1)
    for i in range(15):
        m = _make_match(db_session, venue, team1="MI", team2="RCB",
                        date=base - datetime.timedelta(weeks=i))
        _make_stats(db_session, player, m, runs=35, balls_faced=24,
                    strike_rate=145.0, fours=3, sixes=2, dream11_points=45.0)

    await db_session.flush()

    rng = np.random.default_rng(42)
    simulator = MonteCarloSimulator(db_session)
    proj = await simulator.project(player.id, match.id, n_simulations=500, rng=rng)

    assert 10.0 <= proj.mean_points <= 120.0, (
        f"Unexpected mean_points={proj.mean_points}"
    )


@pytest.mark.asyncio
async def test_simulator_no_history_does_not_crash(db_session):
    """Simulator must handle a player with zero history gracefully."""
    venue = _make_venue(db_session)
    player = _make_player(db_session)
    match = _make_match(db_session, venue)
    await db_session.flush()

    rng = np.random.default_rng(99)
    simulator = MonteCarloSimulator(db_session)
    proj = await simulator.project(player.id, match.id, n_simulations=200, rng=rng)

    assert proj.mean_points >= 0
    assert proj.std_dev >= 0


def test_simulate_once_never_negative():
    """Single simulation must never return negative points."""
    rng = np.random.default_rng(0)
    bat_dist = {
        "runs_mean": 20.0, "runs_std": 15.0, "sr_mean": 120.0, "sr_std": 25.0,
        "four_rate": 0.08, "six_rate": 0.04, "duck_prob": 0.10,
    }
    bowl_dist = {
        "bowl_prob": 0.5, "wkt_mean": 1.0, "wkt_std": 1.0,
        "eco_mean": 8.0, "eco_std": 1.5, "maiden_rate": 0.05,
        "lbw_bowled_rate": 0.25,
    }
    field_dist = {
        "catch_per_match": 0.20, "stumping_per_match": 0.0, "ro_per_match": 0.05,
    }

    for _ in range(500):
        pts = _simulate_once(rng, bat_dist, bowl_dist, field_dist, 1.0)
        assert pts >= 0.0, f"Got negative points: {pts}"


def test_simulate_once_boom_player():
    """Elite bowler dist should occasionally boom (>80 pts) in 500 sims."""
    rng = np.random.default_rng(7)
    bat_dist = {
        "runs_mean": 30.0, "runs_std": 20.0, "sr_mean": 140.0, "sr_std": 20.0,
        "four_rate": 0.10, "six_rate": 0.06, "duck_prob": 0.05,
    }
    bowl_dist = {
        "bowl_prob": 1.0, "wkt_mean": 2.5, "wkt_std": 1.5,
        "eco_mean": 6.5, "eco_std": 1.0, "maiden_rate": 0.15,
        "lbw_bowled_rate": 0.30,
    }
    field_dist = {
        "catch_per_match": 0.5, "stumping_per_match": 0.0, "ro_per_match": 0.1,
    }
    results = [_simulate_once(rng, bat_dist, bowl_dist, field_dist, 1.0)
               for _ in range(500)]
    boom_count = sum(1 for r in results if r > 80)
    assert boom_count > 0, "Elite allrounder should occasionally boom across 500 sims"


# ---------------------------------------------------------------------------
# TASK 4 — Captain Picker
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_captain_mega_chalk_deprioritised(db_session):
    """
    Chalk player (MI, 11 credits, 85% ownership) should NOT be the top
    captain recommendation in mega contest — the differential with similar
    performance should rank higher after the chalk penalty.
    """
    venue = _make_venue(db_session)
    match = _make_match(db_session, venue, team1="Mumbai Indians",
                        team2="Sunrisers Hyderabad")
    await db_session.flush()

    # 22 players: chalk=players[0] (MI, 11cr), diff=players[3] (SRH, 6.5cr)
    players = await _seed_22_players(
        db_session, match,
        star_idx=0,  star_team="Mumbai Indians", star_price=11.0,
        diff_idx=3,  diff_team="Sunrisers Hyderabad", diff_price=6.5,
    )
    await db_session.flush()

    base = datetime.date(2025, 3, 1)
    # Give both the chalk player and the differential player similarly elite stats
    for i in range(10):
        m = _make_match(db_session, venue, team1="Mumbai Indians",
                        team2="Sunrisers Hyderabad",
                        date=base - datetime.timedelta(weeks=i))
        _make_stats(db_session, players[0], m, runs=80, balls_faced=50,
                    strike_rate=160.0, dream11_points=95.0)

    for i in range(10):
        m = _make_match(db_session, venue, team1="Mumbai Indians",
                        team2="Sunrisers Hyderabad",
                        date=base - datetime.timedelta(weeks=i))
        _make_stats(db_session, players[3], m, runs=78, balls_faced=48,
                    strike_rate=162.0, dream11_points=93.0)

    await db_session.flush()

    picker = CaptainPicker(db_session)
    result = await picker.pick(match.id, contest_type="mega")

    assert "captain" in result and len(result["captain"]) > 0

    top_captain_id = result["captain"][0]["player_id"]
    # The high-owned MI star should NOT be the #1 mega captain
    assert top_captain_id != str(players[0].id), (
        "Chalk player (MI, 11cr, ~85% ownership) should be deprioritised in mega"
    )
    # The differential (SRH, 6.5cr) should be preferred
    assert top_captain_id == str(players[3].id), (
        f"Expected differential player {players[3].id} as top mega C, got {top_captain_id}"
    )


@pytest.mark.asyncio
async def test_captain_small_league_best_player_wins(db_session):
    """In small league, the player with the best expected points ranks first."""
    venue = _make_venue(db_session)
    match = _make_match(db_session, venue, team1="MI", team2="CSK")
    await db_session.flush()

    players = await _seed_22_players(db_session, match,
                                      star_idx=0, star_team="MI", star_price=10.0,
                                      diff_idx=3, diff_team="CSK", diff_price=8.0)
    await db_session.flush()

    base = datetime.date(2025, 3, 1)
    # players[0] is dominant; others have mediocre stats
    for i in range(10):
        m = _make_match(db_session, venue, team1="MI", team2="CSK",
                        date=base - datetime.timedelta(weeks=i))
        _make_stats(db_session, players[0], m, runs=90, balls_faced=55,
                    strike_rate=163.0, dream11_points=100.0)

    for j in [1, 2, 3]:
        for i in range(10):
            m = _make_match(db_session, venue, team1="MI", team2="CSK",
                            date=base - datetime.timedelta(weeks=i))
            _make_stats(db_session, players[j], m, runs=20, balls_faced=15,
                        strike_rate=133.0, dream11_points=25.0)

    await db_session.flush()

    picker = CaptainPicker(db_session)
    result = await picker.pick(match.id, contest_type="small")

    assert len(result["captain"]) > 0
    assert result["captain"][0]["player_id"] == str(players[0].id), (
        "In small league the best performer must be the top captain pick"
    )


@pytest.mark.asyncio
async def test_captain_returns_top_3(db_session):
    """Captain and VC lists should each contain at least 3 recommendations."""
    venue = _make_venue(db_session)
    match = _make_match(db_session, venue)
    await db_session.flush()
    players = await _seed_22_players(db_session, match)
    await db_session.flush()

    base = datetime.date(2025, 3, 1)
    for idx, p in enumerate(players[:5]):
        for i in range(8):
            m = _make_match(db_session, venue, team1="MI", team2="RCB",
                            date=base - datetime.timedelta(weeks=i))
            _make_stats(db_session, p, m, runs=40 + idx * 5, balls_faced=28,
                        strike_rate=142.0, dream11_points=50.0 + idx * 5)

    await db_session.flush()

    picker = CaptainPicker(db_session)
    result = await picker.pick(match.id, contest_type="mega")

    assert len(result["captain"]) >= 3, "Should return at least 3 captain options"
    assert len(result["vice_captain"]) >= 3, "Should return at least 3 VC options"
