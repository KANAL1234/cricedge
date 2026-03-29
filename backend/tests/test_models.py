"""Tests for SQLAlchemy model creation and relationships."""
import uuid
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.player import Player, PlayerRole
from app.models.match import Match, MatchFormat, MatchStatus
from app.models.venue import Venue, PitchType
from app.models.innings import PlayerMatchStats, BallByBall


@pytest.mark.asyncio
async def test_create_venue(db_session):
    venue = Venue(
        id=uuid.uuid4(),
        name="Wankhede Stadium",
        city="Mumbai",
        country="India",
        pitch_type=PitchType.BATTING,
        avg_first_innings_score_t20=175.0,
        avg_second_innings_score_t20=162.0,
        pace_wickets_pct=55.0,
        spin_wickets_pct=45.0,
        dew_factor=True,
        capacity=33000,
    )
    db_session.add(venue)
    await db_session.flush()

    result = await db_session.execute(select(Venue).where(Venue.name == "Wankhede Stadium"))
    fetched = result.scalar_one()
    assert fetched.city == "Mumbai"
    assert fetched.pitch_type == PitchType.BATTING
    assert fetched.dew_factor is True


@pytest.mark.asyncio
async def test_create_player(db_session):
    player = Player(
        id=uuid.uuid4(),
        name="Rohit Sharma",
        full_name="Rohit Gurunath Sharma",
        country="India",
        role=PlayerRole.BATSMAN,
        batting_style="Right-hand bat",
        ipl_team="Mumbai Indians",
        dream11_price=10.5,
        is_active=True,
    )
    db_session.add(player)
    await db_session.flush()

    result = await db_session.execute(select(Player).where(Player.name == "Rohit Sharma"))
    fetched = result.scalar_one()
    assert fetched.full_name == "Rohit Gurunath Sharma"
    assert fetched.role == PlayerRole.BATSMAN
    assert fetched.ipl_team == "Mumbai Indians"


@pytest.mark.asyncio
async def test_create_match_with_venue(db_session):
    venue = Venue(id=uuid.uuid4(), name="Eden Gardens", city="Kolkata", country="India")
    db_session.add(venue)
    await db_session.flush()

    import datetime
    match = Match(
        id=uuid.uuid4(),
        match_code="1234567",
        date=datetime.date(2024, 4, 5),
        venue_id=venue.id,
        team1="Kolkata Knight Riders",
        team2="Mumbai Indians",
        format=MatchFormat.T20,
        status=MatchStatus.COMPLETED,
        competition="Indian Premier League",
        toss_winner="Kolkata Knight Riders",
        toss_decision="bat",
        result="win",
        winner="Kolkata Knight Riders",
        margin="20 runs",
    )
    db_session.add(match)
    await db_session.flush()

    result = await db_session.execute(select(Match).where(Match.match_code == "1234567"))
    fetched = result.scalar_one()
    assert fetched.team1 == "Kolkata Knight Riders"
    assert fetched.venue_id == venue.id
    assert fetched.competition == "Indian Premier League"


@pytest.mark.asyncio
async def test_player_match_stats_relationship(db_session):
    player = Player(
        id=uuid.uuid4(), name="Virat Kohli", country="India",
        role=PlayerRole.BATSMAN, is_active=True
    )
    venue = Venue(id=uuid.uuid4(), name="Chinnaswamy", city="Bangalore", country="India")
    db_session.add_all([player, venue])
    await db_session.flush()

    import datetime
    match = Match(
        id=uuid.uuid4(),
        match_code="9999001",
        date=datetime.date(2024, 4, 10),
        venue_id=venue.id,
        team1="Royal Challengers Bangalore",
        team2="Delhi Capitals",
        format=MatchFormat.T20,
        status=MatchStatus.COMPLETED,
    )
    db_session.add(match)
    await db_session.flush()

    stats = PlayerMatchStats(
        id=uuid.uuid4(),
        player_id=player.id,
        match_id=match.id,
        innings_number=1,
        runs=82,
        balls_faced=53,
        fours=8,
        sixes=3,
        strike_rate=154.72,
        is_out=True,
        wickets=0,
        catches=1,
        dream11_points=0.0,  # will be computed
    )
    db_session.add(stats)
    await db_session.flush()

    result = await db_session.execute(
        select(PlayerMatchStats).where(
            PlayerMatchStats.player_id == player.id,
            PlayerMatchStats.match_id == match.id,
        )
    )
    fetched = result.scalar_one()
    assert fetched.runs == 82
    assert fetched.strike_rate == 154.72
    assert fetched.catches == 1


@pytest.mark.asyncio
async def test_ball_by_ball(db_session):
    batter = Player(id=uuid.uuid4(), name="MS Dhoni", country="India", role=PlayerRole.WICKET_KEEPER, is_active=True)
    bowler = Player(id=uuid.uuid4(), name="Jasprit Bumrah", country="India", role=PlayerRole.BOWLER, is_active=True)
    venue = Venue(id=uuid.uuid4(), name="MA Chidambaram", city="Chennai", country="India")
    db_session.add_all([batter, bowler, venue])
    await db_session.flush()

    import datetime
    match = Match(
        id=uuid.uuid4(), match_code="1111001",
        date=datetime.date(2024, 5, 1),
        venue_id=venue.id,
        team1="Chennai Super Kings",
        team2="Mumbai Indians",
        format=MatchFormat.T20,
        status=MatchStatus.COMPLETED,
    )
    db_session.add(match)
    await db_session.flush()

    ball = BallByBall(
        id=uuid.uuid4(),
        match_id=match.id,
        innings_number=2,
        over_number=19,
        ball_number=3,
        batter_id=batter.id,
        bowler_id=bowler.id,
        runs_batter=6,
        runs_extras=0,
        runs_total=6,
    )
    db_session.add(ball)
    await db_session.flush()

    result = await db_session.execute(
        select(BallByBall).where(BallByBall.match_id == match.id)
    )
    fetched = result.scalar_one()
    assert fetched.runs_batter == 6
    assert fetched.over_number == 19
    assert fetched.batter_id == batter.id
