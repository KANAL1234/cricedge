"""Tests for the Cricsheet ingester using a 3-over mock match JSON."""
import json
import uuid
import pytest
import tempfile
from pathlib import Path
from sqlalchemy import select

from app.models.match import Match
from app.models.player import Player
from app.models.venue import Venue
from app.models.innings import PlayerMatchStats, BallByBall
from app.scripts.ingest_cricsheet import process_file, calculate_dream11_points


MOCK_MATCH = {
    "info": {
        "dates": ["2024-04-05"],
        "teams": ["Mumbai Indians", "Chennai Super Kings"],
        "venue": "Wankhede Stadium",
        "event": {"name": "Indian Premier League", "match_number": 1},
        "match_type": "T20",
        "toss": {"winner": "Mumbai Indians", "decision": "bat"},
        "outcome": {"winner": "Mumbai Indians", "by": {"runs": 20}},
        "players": {
            "Mumbai Indians": ["Rohit Sharma", "Ishan Kishan"],
            "Chennai Super Kings": ["MS Dhoni", "Ravindra Jadeja"],
        },
        "registry": {
            "people": {
                "Rohit Sharma": "rs001",
                "Ishan Kishan": "ik001",
                "MS Dhoni": "msd001",
                "Ravindra Jadeja": "rj001",
            }
        },
    },
    "innings": [
        {
            "team": "Mumbai Indians",
            "overs": [
                {
                    "over": 0,
                    "deliveries": [
                        {
                            "batter": "Rohit Sharma",
                            "bowler": "Ravindra Jadeja",
                            "non_striker": "Ishan Kishan",
                            "runs": {"batter": 4, "extras": 0, "total": 4},
                        },
                        {
                            "batter": "Rohit Sharma",
                            "bowler": "Ravindra Jadeja",
                            "non_striker": "Ishan Kishan",
                            "runs": {"batter": 6, "extras": 0, "total": 6},
                        },
                        {
                            "batter": "Rohit Sharma",
                            "bowler": "Ravindra Jadeja",
                            "non_striker": "Ishan Kishan",
                            "runs": {"batter": 1, "extras": 0, "total": 1},
                        },
                        {
                            "batter": "Ishan Kishan",
                            "bowler": "Ravindra Jadeja",
                            "non_striker": "Rohit Sharma",
                            "runs": {"batter": 0, "extras": 0, "total": 0},
                        },
                        {
                            "batter": "Ishan Kishan",
                            "bowler": "Ravindra Jadeja",
                            "non_striker": "Rohit Sharma",
                            "runs": {"batter": 0, "extras": 0, "total": 0},
                            "wickets": [
                                {
                                    "player_out": "Ishan Kishan",
                                    "kind": "caught",
                                    "fielders": [{"name": "MS Dhoni"}],
                                }
                            ],
                        },
                        {
                            "batter": "Rohit Sharma",
                            "bowler": "Ravindra Jadeja",
                            "non_striker": "Rohit Sharma",
                            "runs": {"batter": 0, "extras": 0, "total": 0},
                        },
                    ],
                },
                {
                    "over": 1,
                    "deliveries": [
                        {
                            "batter": "Rohit Sharma",
                            "bowler": "MS Dhoni",
                            "non_striker": "Rohit Sharma",
                            "runs": {"batter": 6, "extras": 0, "total": 6},
                        },
                        {
                            "batter": "Rohit Sharma",
                            "bowler": "MS Dhoni",
                            "non_striker": "Rohit Sharma",
                            "runs": {"batter": 4, "extras": 0, "total": 4},
                        },
                        {
                            "batter": "Rohit Sharma",
                            "bowler": "MS Dhoni",
                            "non_striker": "Rohit Sharma",
                            "runs": {"batter": 1, "extras": 0, "total": 1},
                        },
                        {
                            "batter": "Rohit Sharma",
                            "bowler": "MS Dhoni",
                            "non_striker": "Rohit Sharma",
                            "runs": {"batter": 0, "extras": 0, "total": 0},
                        },
                        {
                            "batter": "Rohit Sharma",
                            "bowler": "MS Dhoni",
                            "non_striker": "Rohit Sharma",
                            "runs": {"batter": 0, "extras": 0, "total": 0},
                        },
                        {
                            "batter": "Rohit Sharma",
                            "bowler": "MS Dhoni",
                            "non_striker": "Rohit Sharma",
                            "runs": {"batter": 2, "extras": 0, "total": 2},
                        },
                    ],
                },
                {
                    "over": 2,
                    "deliveries": [
                        {
                            "batter": "Rohit Sharma",
                            "bowler": "Ravindra Jadeja",
                            "non_striker": "Rohit Sharma",
                            "runs": {"batter": 4, "extras": 0, "total": 4},
                        },
                        {
                            "batter": "Rohit Sharma",
                            "bowler": "Ravindra Jadeja",
                            "non_striker": "Rohit Sharma",
                            "runs": {"batter": 1, "extras": 0, "total": 1},
                        },
                        {
                            "batter": "Rohit Sharma",
                            "bowler": "Ravindra Jadeja",
                            "non_striker": "Rohit Sharma",
                            "runs": {"batter": 0, "extras": 0, "total": 0},
                            "wickets": [
                                {
                                    "player_out": "Rohit Sharma",
                                    "kind": "bowled",
                                    "fielders": [],
                                }
                            ],
                        },
                    ],
                },
            ],
        }
    ],
}


@pytest.fixture
def mock_json_dir(tmp_path):
    """Write mock match JSON to a temp directory and return the path."""
    match_file = tmp_path / "1234999.json"
    match_file.write_text(json.dumps(MOCK_MATCH))
    return tmp_path


@pytest.mark.asyncio
async def test_ingester_processes_match(db_session, mock_json_dir):
    match_path = mock_json_dir / "1234999.json"
    result = await process_file(db_session, match_path, fmt=None)

    assert result["error"] is None
    assert result["match_processed"] == 1
    assert result["players_upserted"] > 0
    assert result["balls_inserted"] > 0

    # Verify match was created
    m = (await db_session.execute(select(Match).where(Match.match_code == "1234999"))).scalar_one()
    assert m.team1 == "Mumbai Indians"
    assert m.team2 == "Chennai Super Kings"
    assert m.winner == "Mumbai Indians"
    assert m.margin == "20 runs"
    assert m.competition == "Indian Premier League"


@pytest.mark.asyncio
async def test_ingester_upserts_players(db_session, mock_json_dir):
    match_path = mock_json_dir / "1234999.json"
    await process_file(db_session, match_path, fmt=None)

    # Rohit Sharma should exist
    p = (await db_session.execute(select(Player).where(Player.name == "Rohit Sharma"))).scalar_one_or_none()
    assert p is not None
    assert p.cricsheet_id == "rs001"


@pytest.mark.asyncio
async def test_ingester_skips_duplicate(db_session, mock_json_dir):
    match_path = mock_json_dir / "1234999.json"
    # First ingest
    r1 = await process_file(db_session, match_path, fmt=None)
    assert r1["match_processed"] == 1

    # Second ingest — should skip
    r2 = await process_file(db_session, match_path, fmt=None)
    assert r2["match_processed"] == 0


@pytest.mark.asyncio
async def test_ingester_balls_inserted(db_session, mock_json_dir):
    match_path = mock_json_dir / "1234999.json"
    result = await process_file(db_session, match_path, fmt=None)

    # 3 overs: 6 + 6 + 3 = 15 deliveries
    assert result["balls_inserted"] == 15


@pytest.mark.asyncio
async def test_ingester_computes_player_stats(db_session, mock_json_dir):
    match_path = mock_json_dir / "1234999.json"
    await process_file(db_session, match_path, fmt=None)

    rohit = (await db_session.execute(select(Player).where(Player.name == "Rohit Sharma"))).scalar_one()
    match = (await db_session.execute(select(Match).where(Match.match_code == "1234999"))).scalar_one()

    stats = (await db_session.execute(
        select(PlayerMatchStats).where(
            PlayerMatchStats.player_id == rohit.id,
            PlayerMatchStats.match_id == match.id,
        )
    )).scalar_one()

    # Rohit scored: 4+6+1+0+6+4+1+0+0+2+4+1+0 = 29 runs across 3 overs
    assert stats.runs == 29
    assert stats.fours >= 3
    assert stats.sixes >= 2
    assert stats.dream11_points > 0


@pytest.mark.asyncio
async def test_ingester_fielding_credited(db_session, mock_json_dir):
    match_path = mock_json_dir / "1234999.json"
    await process_file(db_session, match_path, fmt=None)

    msd = (await db_session.execute(select(Player).where(Player.name == "MS Dhoni"))).scalar_one()
    match = (await db_session.execute(select(Match).where(Match.match_code == "1234999"))).scalar_one()

    stats = (await db_session.execute(
        select(PlayerMatchStats).where(
            PlayerMatchStats.player_id == msd.id,
            PlayerMatchStats.match_id == match.id,
        )
    )).scalar_one_or_none()

    # MS Dhoni took a catch
    assert stats is not None
    assert stats.catches >= 1


# ---------------------------------------------------------------------------
# Unit tests for Dream11 points calculator
# ---------------------------------------------------------------------------

def test_dream11_duck_penalty():
    pts = calculate_dream11_points({"runs": 0, "balls_faced": 3, "is_out": True})
    assert pts == -2


def test_dream11_fifty():
    pts = calculate_dream11_points({
        "runs": 50, "balls_faced": 35, "fours": 4, "sixes": 2, "is_out": True
    })
    # 50*1 + 4*1 + 2*2 + 8 (fifty bonus) = 50+4+4+8 = 66
    assert pts == 66.0


def test_dream11_century():
    pts = calculate_dream11_points({
        "runs": 100, "balls_faced": 65, "fours": 8, "sixes": 4, "is_out": False
    })
    # 100 + 8 + 8 + 16 = 132
    assert pts == 132.0


def test_dream11_five_wickets():
    pts = calculate_dream11_points({
        "wickets": 5, "overs_bowled": 4.0, "runs_conceded": 20
    })
    # 5*25=125 + 5wkt bonus 16 + economy 5.0 (falls in <6 range) = +4 bonus
    # total = 125 + 16 + 4 = 145
    assert pts == 145.0


def test_dream11_catch():
    pts = calculate_dream11_points({"catches": 2})
    assert pts == 16.0


def test_dream11_stumping():
    pts = calculate_dream11_points({"stumpings": 1})
    assert pts == 12.0
