"""Tests for all API endpoints using TestClient with mocked DB session."""
import uuid
import datetime
import pytest

from sqlalchemy import select

from app.models.player import Player, PlayerRole
from app.models.match import Match, MatchFormat, MatchStatus
from app.models.venue import Venue, PitchType
from app.models.innings import PlayerMatchStats


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_venue(db_session) -> Venue:
    v = Venue(
        id=uuid.uuid4(), name="Wankhede Stadium", city="Mumbai", country="India",
        pitch_type=PitchType.BATTING, avg_first_innings_score_t20=175.0,
        avg_second_innings_score_t20=162.0, dew_factor=True,
    )
    db_session.add(v)
    await db_session.commit()
    return v


async def _seed_match(db_session, venue: Venue | None = None) -> Match:
    m = Match(
        id=uuid.uuid4(),
        match_code="T001",
        date=datetime.date.today(),
        venue_id=venue.id if venue else None,
        team1="Mumbai Indians",
        team2="Chennai Super Kings",
        format=MatchFormat.T20,
        status=MatchStatus.UPCOMING,
        competition="IPL 2024",
        match_start_utc=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=2),
    )
    db_session.add(m)
    await db_session.commit()
    return m


async def _seed_player(db_session) -> Player:
    p = Player(
        id=uuid.uuid4(), name="Rohit Sharma", full_name="Rohit Gurunath Sharma",
        country="India", role=PlayerRole.BATSMAN, ipl_team="Mumbai Indians",
        dream11_price=10.5, is_active=True,
    )
    db_session.add(p)
    await db_session.commit()
    return p


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Matches API
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_matches_empty(client):
    resp = await client.get("/api/v1/matches")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    assert "total" in body


@pytest.mark.asyncio
async def test_list_matches_with_data(client, db_session):
    venue = await _seed_venue(db_session)
    await _seed_match(db_session, venue)

    resp = await client.get("/api/v1/matches")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    match_data = body["data"][0]
    assert "team1" in match_data
    assert "venue" in match_data


@pytest.mark.asyncio
async def test_get_match_detail(client, db_session):
    venue = await _seed_venue(db_session)
    match = await _seed_match(db_session, venue)

    resp = await client.get(f"/api/v1/matches/{match.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(match.id)
    assert body["team1"] == "Mumbai Indians"
    assert "venue_stats" in body
    assert body["venue_stats"]["dew_factor"] is True


@pytest.mark.asyncio
async def test_get_match_not_found(client):
    resp = await client.get(f"/api/v1/matches/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_playing_xi(client, db_session):
    match = await _seed_match(db_session)

    resp = await client.get(f"/api/v1/matches/{match.id}/playing-xi")
    assert resp.status_code == 200
    body = resp.json()
    assert "xi_confirmed" in body
    assert body["xi_confirmed"] is False


@pytest.mark.asyncio
async def test_search_matches(client, db_session):
    await _seed_match(db_session)

    resp = await client.get("/api/v1/matches/search?q=Mumbai")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1


# ---------------------------------------------------------------------------
# Players API
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_players_empty(client):
    resp = await client.get("/api/v1/players")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_list_players(client, db_session):
    await _seed_player(db_session)
    resp = await client.get("/api/v1/players")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1


@pytest.mark.asyncio
async def test_get_player(client, db_session):
    player = await _seed_player(db_session)
    resp = await client.get(f"/api/v1/players/{player.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Rohit Sharma"
    assert body["ipl_team"] == "Mumbai Indians"
    assert "career_stats" in body


@pytest.mark.asyncio
async def test_get_player_not_found(client):
    resp = await client.get(f"/api/v1/players/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_search_players(client, db_session):
    await _seed_player(db_session)
    resp = await client.get("/api/v1/players/search?q=Rohit")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert body["data"][0]["name"] == "Rohit Sharma"


@pytest.mark.asyncio
async def test_search_players_min_length(client):
    resp = await client.get("/api/v1/players/search?q=R")
    assert resp.status_code == 422  # min_length=2


@pytest.mark.asyncio
async def test_get_player_form(client, db_session):
    player = await _seed_player(db_session)
    venue = await _seed_venue(db_session)
    match = Match(
        id=uuid.uuid4(), match_code="FORM01",
        date=datetime.date.today(),
        venue_id=venue.id,
        team1="Mumbai Indians", team2="Delhi Capitals",
        format=MatchFormat.T20, status=MatchStatus.COMPLETED,
        match_start_utc=datetime.datetime.now(datetime.timezone.utc),
    )
    db_session.add(match)
    await db_session.flush()

    stats = PlayerMatchStats(
        id=uuid.uuid4(), player_id=player.id, match_id=match.id,
        innings_number=1, runs=65, balls_faced=42, fours=6, sixes=3,
        strike_rate=154.76, is_out=True, dream11_points=85.0,
    )
    db_session.add(stats)
    await db_session.commit()

    resp = await client.get(f"/api/v1/players/{player.id}/form?n=5&format=T20")
    assert resp.status_code == 200
    body = resp.json()
    assert body["games"] == 1
    assert body["innings"][0]["runs"] == 65
    assert body["innings"][0]["dream11_points"] == 85.0


@pytest.mark.asyncio
async def test_get_player_form_invalid_format(client, db_session):
    player = await _seed_player(db_session)
    resp = await client.get(f"/api/v1/players/{player.id}/form?format=INVALID")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Venues API
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_venues_empty(client):
    resp = await client.get("/api/v1/venues")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_get_venue(client, db_session):
    venue = await _seed_venue(db_session)
    resp = await client.get(f"/api/v1/venues/{venue.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Wankhede Stadium"
    assert body["pitch_type"] == "batting"
    assert body["avg_first_innings_score_t20"] == 175.0
    assert "total_matches" in body


@pytest.mark.asyncio
async def test_get_venue_not_found(client):
    resp = await client.get(f"/api/v1/venues/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_venue_stats(client, db_session):
    venue = await _seed_venue(db_session)
    resp = await client.get(f"/api/v1/venues/{venue.id}/stats?format=T20")
    assert resp.status_code == 200
    body = resp.json()
    assert body["venue_name"] == "Wankhede Stadium"
    assert "pace_vs_spin" in body
    assert "scoring_patterns" in body
    assert body["dew_factor"] is True
