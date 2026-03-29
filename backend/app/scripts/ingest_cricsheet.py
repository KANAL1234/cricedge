"""
Cricsheet JSON ingester for CricEdge.

Usage:
    python ingest_cricsheet.py --dir ./data/ipl/
    python ingest_cricsheet.py --dir ./data/ipl/ --format T20
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

# Allow running as a script from backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.core.database import AsyncSessionLocal
from app.models.innings import BallByBall, PlayerMatchStats
from app.models.match import Match, MatchFormat, MatchStatus
from app.models.player import Player, PlayerRole
from app.models.venue import Venue

try:
    from tqdm import tqdm
except ImportError:
    # Graceful fallback — tqdm is optional for this script to function
    def tqdm(iterable, **kwargs):  # type: ignore[misc]
        return iterable

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dream11 T20 points calculator
# ---------------------------------------------------------------------------

def calculate_dream11_points(stats: dict) -> float:
    """Return Dream11 T20 fantasy points given aggregated match stats dict."""
    points: float = 0.0

    runs: int = stats.get("runs", 0)
    balls_faced: int = stats.get("balls_faced", 0)
    fours: int = stats.get("fours", 0)
    sixes: int = stats.get("sixes", 0)
    wickets: int = stats.get("wickets", 0)
    overs_bowled: float = stats.get("overs_bowled", 0.0)
    runs_conceded: int = stats.get("runs_conceded", 0)
    maidens: int = stats.get("maidens", 0)
    catches: int = stats.get("catches", 0)
    stumpings: int = stats.get("stumpings", 0)
    run_outs_direct: int = stats.get("run_outs_direct", 0)
    run_outs_indirect: int = stats.get("run_outs", 0) - run_outs_direct
    is_out: bool = stats.get("is_out", False)

    # --- Batting ---
    if balls_faced > 0:
        points += runs * 1                  # 1 pt per run
        points += fours * 1                 # boundary bonus: +1 per four
        points += sixes * 2                 # boundary bonus: +2 per six
        if runs >= 100:
            points += 16                    # century bonus
        elif runs >= 50:
            points += 8                     # half-century bonus
        elif runs >= 30:
            points += 4                     # 30+ bonus
        if runs == 0 and is_out:
            points -= 2                     # duck penalty

    # --- Bowling ---
    if overs_bowled > 0:
        points += wickets * 25              # 25 pts per wicket (not run out)
        points += maidens * 8              # 8 pts per maiden
        if wickets >= 5:
            points += 16
        elif wickets >= 4:
            points += 8
        elif wickets >= 3:
            points += 4
        # Economy bonus / penalty (minimum 2 overs bowled)
        if overs_bowled >= 2 and runs_conceded > 0:
            economy = (runs_conceded / overs_bowled)
            if economy < 5:
                points += 6
            elif economy < 6:
                points += 4
            elif economy < 7:
                points += 2
            elif economy >= 10 and economy < 11:
                points -= 2
            elif economy >= 11 and economy < 12:
                points -= 4
            elif economy >= 12:
                points -= 6

    # --- Fielding ---
    points += catches * 8
    points += stumpings * 12
    points += run_outs_direct * 12
    points += max(run_outs_indirect, 0) * 6

    return round(points, 2)


# ---------------------------------------------------------------------------
# Helper: upsert or get Player
# ---------------------------------------------------------------------------

async def get_or_create_player(session: AsyncSession, name: str, cricsheet_id: str | None = None) -> Player:
    """Return existing player by cricsheet_id or name; create if absent."""
    if cricsheet_id:
        result = await session.execute(
            select(Player).where(Player.cricsheet_id == cricsheet_id)
        )
        player = result.scalar_one_or_none()
        if player:
            return player

    result = await session.execute(select(Player).where(Player.name == name))
    player = result.scalar_one_or_none()
    if player:
        if cricsheet_id and not player.cricsheet_id:
            player.cricsheet_id = cricsheet_id
        return player

    player = Player(
        id=uuid.uuid4(),
        name=name,
        full_name=name,
        cricsheet_id=cricsheet_id,
        country="",
        role=PlayerRole.BATSMAN,
        is_active=True,
        dream11_price=8.0,
    )
    session.add(player)
    await session.flush()
    return player


# ---------------------------------------------------------------------------
# Helper: upsert or get Venue
# ---------------------------------------------------------------------------

async def get_or_create_venue(session: AsyncSession, name: str) -> Venue:
    result = await session.execute(select(Venue).where(Venue.name == name))
    venue = result.scalar_one_or_none()
    if venue:
        return venue

    venue = Venue(id=uuid.uuid4(), name=name, city="", country="India")
    session.add(venue)
    await session.flush()
    return venue


# ---------------------------------------------------------------------------
# Helper: parse outcome margin string
# ---------------------------------------------------------------------------

def _parse_margin(outcome: dict) -> str | None:
    by = outcome.get("by", {})
    if "runs" in by:
        return f"{by['runs']} runs"
    if "wickets" in by:
        return f"{by['wickets']} wickets"
    return None


# ---------------------------------------------------------------------------
# Core: process a single Cricsheet JSON file
# ---------------------------------------------------------------------------

async def process_file(session: AsyncSession, path: Path, fmt: str | None) -> dict:
    """Parse one Cricsheet JSON match file and upsert into DB.

    Returns a summary dict: {match_processed, players_upserted, balls_inserted, error}
    """
    summary = {"match_processed": 0, "players_upserted": 0, "balls_inserted": 0, "error": None}

    try:
        raw = json.loads(path.read_text())
    except Exception as exc:
        summary["error"] = f"JSON parse error: {exc}"
        return summary

    info: dict[str, Any] = raw.get("info", {})
    innings_data: list[dict] = raw.get("innings", [])

    # Match code from filename (Cricsheet uses numeric IDs as filenames)
    match_code = path.stem

    # Check existing
    existing = await session.execute(select(Match).where(Match.match_code == match_code))
    if existing.scalar_one_or_none():
        return summary  # already ingested, skip

    # Format
    match_format_str = info.get("match_type", "T20").upper()
    try:
        match_format = MatchFormat(match_format_str)
    except ValueError:
        match_format = MatchFormat.T20

    if fmt and match_format.value != fmt.upper():
        return summary  # filtered out by --format flag

    dates = info.get("dates", [])
    match_date = dates[0] if dates else None
    from datetime import date as date_cls
    import datetime as dt
    parsed_date = dt.date.fromisoformat(match_date) if match_date else None

    teams = info.get("teams", [])
    team1 = teams[0] if len(teams) > 0 else ""
    team2 = teams[1] if len(teams) > 1 else ""

    venue_name = info.get("venue", "")
    venue = await get_or_create_venue(session, venue_name) if venue_name else None

    toss = info.get("toss", {})
    outcome = info.get("outcome", {})
    winner = outcome.get("winner")
    result_str = "win" if winner else outcome.get("result", None)

    event = info.get("event", {})
    competition = event.get("name")
    match_number = event.get("match_number")

    match = Match(
        id=uuid.uuid4(),
        match_code=match_code,
        date=parsed_date,
        venue_id=venue.id if venue else None,
        team1=team1,
        team2=team2,
        format=match_format,
        status=MatchStatus.COMPLETED,
        competition=competition,
        match_number=match_number,
        toss_winner=toss.get("winner"),
        toss_decision=toss.get("decision"),
        result=result_str,
        winner=winner,
        margin=_parse_margin(outcome),
    )
    session.add(match)
    await session.flush()
    summary["match_processed"] = 1

    # Build registry: player_name -> cricsheet_id
    registry: dict[str, str] = info.get("registry", {}).get("people", {})

    # Pre-load all players from registry to avoid N+1 queries
    player_cache: dict[str, Player] = {}

    # Collect all names across innings
    all_names: set[str] = set()
    for inn in innings_data:
        for over in inn.get("overs", []):
            for delivery in over.get("deliveries", []):
                all_names.add(delivery.get("batter", ""))
                all_names.add(delivery.get("bowler", ""))
                ns = delivery.get("non_striker")
                if ns:
                    all_names.add(ns)
                for w in delivery.get("wickets", []):
                    all_names.add(w.get("player_out", ""))
                    for f in w.get("fielders", []):
                        if isinstance(f, dict):
                            all_names.add(f.get("name", ""))
                        elif isinstance(f, str):
                            all_names.add(f)
    all_names.discard("")

    for name in all_names:
        cs_id = registry.get(name)
        p = await get_or_create_player(session, name, cs_id)
        player_cache[name] = p

    summary["players_upserted"] = len(all_names)

    # Accumulate per-innings stats for each player
    # key: (player_name, innings_number)
    stats_map: dict[tuple[str, int], dict] = {}

    def _get_stats(player_name: str, innings_num: int) -> dict:
        key = (player_name, innings_num)
        if key not in stats_map:
            stats_map[key] = {
                "runs": 0,
                "balls_faced": 0,
                "fours": 0,
                "sixes": 0,
                "wickets": 0,
                "overs_bowled": 0.0,
                "runs_conceded": 0,
                "maidens": 0,
                "catches": 0,
                "stumpings": 0,
                "run_outs": 0,
                "run_outs_direct": 0,
                "is_out": False,
                "batting_position": None,
                "_batter_ball_count": 0,   # track balls per over for maiden detection
                "_bowler_ball_runs": {},   # over_num -> runs in that over (for maiden)
                "_batting_order": [],      # track first ball faced per player
            }
        return stats_map[key]

    balls_to_insert: list[BallByBall] = []

    for innings_idx, inn in enumerate(innings_data, start=1):
        batting_order: list[str] = []
        batting_position: dict[str, int] = {}

        for over in inn.get("overs", []):
            over_num: int = over.get("over", 0)
            over_runs: dict[str, int] = {}  # bowler_name -> runs conceded in this over

            for ball_idx, delivery in enumerate(over.get("deliveries", []), start=1):
                batter_name: str = delivery.get("batter", "")
                bowler_name: str = delivery.get("bowler", "")
                non_striker_name: str | None = delivery.get("non_striker")
                runs_info: dict = delivery.get("runs", {})

                runs_batter: int = runs_info.get("batter", 0)
                runs_extras: int = runs_info.get("extras", 0)
                runs_total: int = runs_info.get("total", runs_batter + runs_extras)
                extras_info: dict = delivery.get("extras", {})
                extras_type: str | None = next(iter(extras_info.keys()), None) if extras_info else None

                # Batting position tracking
                if batter_name and batter_name not in batting_position:
                    batting_position[batter_name] = len(batting_position) + 1
                    batting_order.append(batter_name)

                # Determine if this is a legal delivery (not wide/noball)
                is_legal = extras_type not in ("wides", "noballs")

                # Batter stats (only if legal delivery for ball count)
                if batter_name:
                    s = _get_stats(batter_name, innings_idx)
                    s["batting_position"] = batting_position.get(batter_name)
                    if is_legal:
                        s["balls_faced"] += 1
                    s["runs"] += runs_batter
                    if runs_batter == 4:
                        s["fours"] += 1
                    elif runs_batter == 6:
                        s["sixes"] += 1

                # Bowler stats
                if bowler_name:
                    s = _get_stats(bowler_name, innings_idx)
                    if is_legal:
                        s["_batter_ball_count"] = s.get("_batter_ball_count", 0) + 1
                    s["runs_conceded"] += runs_total - runs_info.get("penalty", 0)
                    # Track runs per over for maiden detection
                    if over_num not in over_runs:
                        over_runs[over_num] = {}
                    over_runs[over_num][bowler_name] = (
                        over_runs[over_num].get(bowler_name, 0) + runs_total
                    )

                # Wickets
                wicket_type: str | None = None
                dismissed_player: Player | None = None
                fielder: Player | None = None

                wickets_list = delivery.get("wickets", [])
                for wicket in wickets_list:
                    player_out: str = wicket.get("player_out", "")
                    kind: str = wicket.get("kind", "")
                    wicket_type = kind

                    if player_out and player_out in player_cache:
                        dismissed_player = player_cache[player_out]
                        s_out = _get_stats(player_out, innings_idx)
                        s_out["is_out"] = True

                    fielders_raw = wicket.get("fielders", [])
                    primary_fielder_name: str | None = None
                    if fielders_raw:
                        f0 = fielders_raw[0]
                        primary_fielder_name = f0.get("name") if isinstance(f0, dict) else f0

                    if primary_fielder_name and primary_fielder_name in player_cache:
                        fielder = player_cache[primary_fielder_name]

                    # Credit wicket to bowler (not run out)
                    if bowler_name and kind not in ("run out", "retired hurt", "obstructing the field"):
                        s = _get_stats(bowler_name, innings_idx)
                        s["wickets"] += 1

                    # Credit fielding events
                    if kind in ("caught", "caught and bowled") and primary_fielder_name:
                        if primary_fielder_name in player_cache:
                            _get_stats(primary_fielder_name, innings_idx)["catches"] += 1
                    elif kind == "stumped" and primary_fielder_name:
                        if primary_fielder_name in player_cache:
                            _get_stats(primary_fielder_name, innings_idx)["stumpings"] += 1
                    elif kind == "run out":
                        if primary_fielder_name and primary_fielder_name in player_cache:
                            sf = _get_stats(primary_fielder_name, innings_idx)
                            sf["run_outs"] += 1
                            sf["run_outs_direct"] += 1  # credit as direct; refine with fielder data if available

                # Build BallByBall row
                batter_obj = player_cache.get(batter_name)
                bowler_obj = player_cache.get(bowler_name)
                if batter_obj and bowler_obj:
                    bbb = BallByBall(
                        id=uuid.uuid4(),
                        match_id=match.id,
                        innings_number=innings_idx,
                        over_number=over_num,
                        ball_number=ball_idx,
                        batter_id=batter_obj.id,
                        bowler_id=bowler_obj.id,
                        non_striker_id=player_cache[non_striker_name].id if non_striker_name and non_striker_name in player_cache else None,
                        runs_batter=runs_batter,
                        runs_extras=runs_extras,
                        runs_total=runs_total,
                        extras_type=extras_type,
                        wicket_type=wicket_type,
                        dismissed_player_id=dismissed_player.id if dismissed_player else None,
                        fielder_id=fielder.id if fielder else None,
                    )
                    balls_to_insert.append(bbb)

            # Maiden detection: if any bowler conceded 0 runs in a completed over (6 legal balls)
            for bowler_name, over_run_map in over_runs.items():
                bowler_stats = _get_stats(bowler_name, innings_idx)
                bowler_stats["overs_bowled"] = round(bowler_stats["overs_bowled"] + 1, 1)
                if over_run_map.get(bowler_name, 1) == 0:
                    bowler_stats["maidens"] += 1

    # Bulk insert balls
    if balls_to_insert:
        session.add_all(balls_to_insert)
        await session.flush()
    summary["balls_inserted"] = len(balls_to_insert)

    # Build PlayerMatchStats rows and compute Dream11 points
    for (player_name, innings_num), s in stats_map.items():
        player = player_cache.get(player_name)
        if not player:
            continue
        sr = round((s["runs"] / s["balls_faced"] * 100) if s["balls_faced"] > 0 else 0.0, 2)
        eco = round((s["runs_conceded"] / s["overs_bowled"]) if s["overs_bowled"] > 0 else 0.0, 2)

        d11_pts = calculate_dream11_points({**s, "strike_rate": sr, "economy": eco})

        pms = PlayerMatchStats(
            id=uuid.uuid4(),
            player_id=player.id,
            match_id=match.id,
            innings_number=innings_num,
            runs=s["runs"],
            balls_faced=s["balls_faced"],
            fours=s["fours"],
            sixes=s["sixes"],
            strike_rate=sr,
            batting_position=s.get("batting_position"),
            is_out=s["is_out"],
            wickets=s["wickets"],
            overs_bowled=s["overs_bowled"],
            runs_conceded=s["runs_conceded"],
            economy=eco,
            maidens=s["maidens"],
            catches=s["catches"],
            stumpings=s["stumpings"],
            run_outs=s["run_outs"],
            run_outs_direct=s["run_outs_direct"],
            dream11_points=d11_pts,
        )
        session.add(pms)

    await session.flush()
    return summary


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main(data_dir: str, fmt: str | None) -> None:
    directory = Path(data_dir)
    if not directory.is_dir():
        logger.error("Directory not found: %s", data_dir)
        sys.exit(1)

    json_files = sorted(directory.glob("*.json"))
    if not json_files:
        logger.warning("No .json files found in %s", data_dir)
        return

    total_matches = 0
    total_players = 0
    total_balls = 0
    errors: list[str] = []

    async with AsyncSessionLocal() as session:
        for path in tqdm(json_files, desc="Processing", unit="file"):
            try:
                result = await process_file(session, path, fmt)
                if result["error"]:
                    errors.append(f"{path.name}: {result['error']}")
                    logger.warning("Error in %s: %s", path.name, result["error"])
                    await session.rollback()
                else:
                    await session.commit()
                    total_matches += result["match_processed"]
                    total_players += result["players_upserted"]
                    total_balls += result["balls_inserted"]
            except Exception as exc:
                await session.rollback()
                errors.append(f"{path.name}: {exc}")
                logger.exception("Unhandled error processing %s", path.name)

    print(f"\n{'='*50}")
    print(f"Ingestion complete")
    print(f"  Matches processed : {total_matches}")
    print(f"  Players upserted  : {total_players}")
    print(f"  Balls inserted    : {total_balls}")
    print(f"  Files with errors : {len(errors)}")
    if errors:
        print("\nErrors:")
        for e in errors[:10]:
            print(f"  - {e}")
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more")
    print("="*50)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest Cricsheet JSON files into CricEdge DB")
    parser.add_argument("--dir", required=True, help="Directory containing Cricsheet .json files")
    parser.add_argument(
        "--format", dest="fmt", default=None, choices=["T20", "ODI", "TEST", "T10"],
        help="Only ingest matches of this format",
    )
    args = parser.parse_args()
    asyncio.run(main(args.dir, args.fmt))
