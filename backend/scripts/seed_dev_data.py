"""
CricEdge Dev Seed Script
========================
Downloads IPL 2023-2025 from Cricsheet, ingests them, scrapes IPL 2026 fixtures,
and updates venue stats. Single command: python scripts/seed_dev_data.py
"""
from __future__ import annotations

import asyncio
import io
import logging
import sys
import uuid
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx

# Allow running from backend/ directory
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select, text

from app.core.database import AsyncSessionLocal
from app.models.innings import BallByBall, PlayerMatchStats
from app.models.match import Match, MatchFormat, MatchStatus
from app.models.player import Player
from app.models.venue import Venue
from app.scripts.ingest_cricsheet import process_file

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, **kwargs):
        return iterable

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_ROOT = Path(__file__).resolve().parents[1] / "data" / "cricsheet" / "ipl"

CRICSHEET_IPL_URL = "https://cricsheet.org/downloads/ipl_json.zip"  # full IPL archive

IPL_2026_TEAMS = [
    "Chennai Super Kings",
    "Mumbai Indians",
    "Royal Challengers Bengaluru",
    "Kolkata Knight Riders",
    "Delhi Capitals",
    "Rajasthan Royals",
    "Sunrisers Hyderabad",
    "Punjab Kings",
    "Gujarat Titans",
    "Lucknow Super Giants",
]

IPL_2026_VENUES = [
    ("MA Chidambaram Stadium", "Chennai"),
    ("Wankhede Stadium", "Mumbai"),
    ("M Chinnaswamy Stadium", "Bengaluru"),
    ("Eden Gardens", "Kolkata"),
    ("Arun Jaitley Stadium", "Delhi"),
    ("Sawai Mansingh Stadium", "Jaipur"),
    ("Rajiv Gandhi International Stadium", "Hyderabad"),
    ("Punjab Cricket Association Stadium", "Mohali"),
    ("Narendra Modi Stadium", "Ahmedabad"),
    ("BRSABV Ekana Cricket Stadium", "Lucknow"),
]


# ---------------------------------------------------------------------------
# Step 1: Download and unzip Cricsheet seasons
# ---------------------------------------------------------------------------

async def download_all_ipl() -> Optional[Path]:
    """Download the full IPL archive (all seasons) from Cricsheet."""
    all_dir = DATA_ROOT / "all"
    all_dir.mkdir(parents=True, exist_ok=True)

    existing = list(all_dir.glob("*.json"))
    if existing:
        logger.info(f"IPL archive: already extracted ({len(existing)} files), skipping download")
        return all_dir

    logger.info("IPL archive: downloading from Cricsheet (all seasons)...")
    try:
        async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
            resp = await client.get(CRICSHEET_IPL_URL)
            resp.raise_for_status()

        zip_bytes = io.BytesIO(resp.content)
        with zipfile.ZipFile(zip_bytes) as z:
            json_names = [n for n in z.namelist() if n.endswith(".json")]
            for name in json_names:
                out_path = all_dir / Path(name).name
                out_path.write_bytes(z.read(name))

        count = len(list(all_dir.glob("*.json")))
        logger.info(f"IPL archive: extracted {count} match files to {all_dir}")
        return all_dir

    except Exception as exc:
        logger.error(f"IPL archive download failed — {exc}")
        logger.error(f"  Manual: wget '{CRICSHEET_IPL_URL}' -O /tmp/ipl.zip && unzip /tmp/ipl.zip -d {all_dir}")
        return None


# ---------------------------------------------------------------------------
# Step 2: Ingest a season directory
# ---------------------------------------------------------------------------

async def ingest_all(data_dir: Path) -> dict:
    json_files = sorted(data_dir.glob("*.json"))
    if not json_files:
        logger.warning(f"No JSON files found in {data_dir}")
        return {"matches": 0, "balls": 0, "players": 0}

    logger.info(f"Ingesting {len(json_files)} match files...")
    total_matches = 0
    total_balls = 0
    total_players = 0

    async with AsyncSessionLocal() as session:
        for path in tqdm(json_files, desc="Ingesting IPL", unit="match", leave=True):
            try:
                result = await process_file(session, path, fmt="T20")
                if result.get("error"):
                    logger.debug(f"  skip {path.name}: {result['error']}")
                    await session.rollback()
                else:
                    await session.commit()
                    total_matches += result.get("match_processed", 0)
                    total_balls += result.get("balls_inserted", 0)
                    total_players += result.get("players_upserted", 0)
            except Exception as exc:
                await session.rollback()
                logger.warning(f"  error in {path.name}: {exc}")

    return {"matches": total_matches, "balls": total_balls, "players": total_players}


# ---------------------------------------------------------------------------
# Step 3: Scrape IPL 2026 fixtures from Cricbuzz (with mock fallback)
# ---------------------------------------------------------------------------

async def load_ipl_2026_fixtures() -> int:
    """Try Cricbuzz; fall back to mock fixtures. Returns count inserted."""
    # First try the scraper
    scraped_count = await _try_cricbuzz_fixtures()
    if scraped_count > 0:
        return scraped_count

    logger.warning("Cricbuzz scrape yielded 0 matches — using mock IPL 2026 fixtures")
    return await _insert_mock_fixtures()


async def _try_cricbuzz_fixtures() -> int:
    try:
        from app.scrapers.cricbuzz import CricbuzzScraper  # type: ignore[import]  # deprecated

        async with CricbuzzScraper() as scraper:
            matches = await scraper.get_upcoming_matches(days=14)

        ipl_matches = [
            m for m in matches
            if "ipl" in m.competition.lower() or "indian premier league" in m.competition.lower()
            or any(t in " ".join(m.teams).lower() for t in ["csk", "mi", "rcb", "kkr", "dc", "rr", "srh", "pbks", "gt", "lsg",
                                                              "chennai", "mumbai", "bangalore", "bengaluru", "kolkata",
                                                              "delhi", "rajasthan", "hyderabad", "punjab", "gujarat", "lucknow"])
        ]

        if not ipl_matches:
            return 0

        inserted = 0
        async with AsyncSessionLocal() as session:
            for m in ipl_matches[:14]:
                try:
                    teams = m.teams if len(m.teams) >= 2 else ["TBD", "TBD"]
                    venue_obj = await _get_or_create_venue(session, m.venue or "TBD", "")

                    match_date = m.date_time.date() if hasattr(m.date_time, "date") else date.today()
                    match_start = m.date_time.astimezone(timezone.utc).replace(tzinfo=None) if m.date_time else None

                    match = Match(
                        id=uuid.uuid4(),
                        match_code=f"ipl2026-cricbuzz-{uuid.uuid4().hex[:8]}",
                        date=match_date,
                        venue_id=venue_obj.id,
                        team1=teams[0],
                        team2=teams[1] if len(teams) > 1 else "TBD",
                        format=MatchFormat.T20,
                        status=MatchStatus.UPCOMING,
                        competition="Indian Premier League 2026",
                        match_start_utc=match_start,
                        xi_confirmed_at=None,
                        playing_xi_team1=[],
                        playing_xi_team2=[],
                    )
                    session.add(match)
                    inserted += 1
                except Exception as exc:
                    logger.debug(f"  fixture insert error: {exc}")
                    await session.rollback()
                    continue

            await session.commit()

        logger.info(f"Cricbuzz: imported {inserted} IPL 2026 fixtures")
        return inserted

    except Exception as exc:
        logger.warning(f"Cricbuzz scrape failed: {exc}")
        return 0


async def _get_or_create_venue(session, name: str, city: str) -> Venue:
    result = await session.execute(select(Venue).where(Venue.name == name))
    v = result.scalar_one_or_none()
    if v:
        return v
    v = Venue(id=uuid.uuid4(), name=name, city=city, country="India")
    session.add(v)
    await session.flush()
    return v


async def _insert_mock_fixtures() -> int:
    """Insert 10 mock IPL 2026 fixtures using real team+venue names."""
    fixtures = [
        (IPL_2026_TEAMS[i % len(IPL_2026_TEAMS)],
         IPL_2026_TEAMS[(i + 1) % len(IPL_2026_TEAMS)],
         IPL_2026_VENUES[i % len(IPL_2026_VENUES)])
        for i in range(10)
    ]

    inserted = 0
    base_date = date(2026, 3, 29)

    async with AsyncSessionLocal() as session:
        for idx, (team1, team2, (venue_name, city)) in enumerate(fixtures):
            try:
                venue_obj = await _get_or_create_venue(session, venue_name, city)
                match_date = base_date + timedelta(days=idx // 2)
                match_start = datetime(
                    match_date.year, match_date.month, match_date.day,
                    14, 0, 0, tzinfo=timezone.utc  # 7:30 PM IST = 14:00 UTC
                )

                match = Match(
                    id=uuid.uuid4(),
                    match_code=f"ipl2026-mock-{idx+1:02d}",
                    date=match_date,
                    venue_id=venue_obj.id,
                    team1=team1,
                    team2=team2,
                    format=MatchFormat.T20,
                    status=MatchStatus.UPCOMING,
                    competition="Indian Premier League 2026",
                    match_number=idx + 1,
                    match_start_utc=match_start,
                    lock_time_utc=datetime(
                        match_date.year, match_date.month, match_date.day,
                        13, 30, 0, tzinfo=timezone.utc
                    ),
                    xi_confirmed_at=None,
                    playing_xi_team1=[],
                    playing_xi_team2=[],
                )
                session.add(match)
                inserted += 1
            except Exception as exc:
                logger.warning(f"  mock fixture error: {exc}")
                await session.rollback()
                continue

        await session.commit()

    logger.info(f"Mock fallback: inserted {inserted} IPL 2026 fixtures")
    return inserted


# ---------------------------------------------------------------------------
# Step 4: Update venue stats from ingested data
# ---------------------------------------------------------------------------

async def update_venue_stats() -> int:
    """
    Calculate avg first/second innings scores and pace/spin percentages.
    Weights recent seasons more heavily: 2025 = 3x, 2024 = 2x, 2023 = 1x.
    """
    updated = 0
    async with AsyncSessionLocal() as session:
        venues_result = await session.execute(select(Venue))
        venues = venues_result.scalars().all()

        for venue in venues:
            try:
                # Get all completed T20 matches at this venue
                matches_result = await session.execute(
                    select(Match).where(
                        Match.venue_id == venue.id,
                        Match.status == MatchStatus.COMPLETED,
                        Match.format == MatchFormat.T20,
                    )
                )
                venue_matches = matches_result.scalars().all()
                if not venue_matches:
                    continue

                first_inn_scores: list[tuple[float, float]] = []   # (score, weight)
                second_inn_scores: list[tuple[float, float]] = []
                pace_wickets = 0.0
                spin_wickets = 0.0
                total_wicket_weight = 0.0

                for match in venue_matches:
                    # Season weight
                    match_year = match.date.year if match.date else 2023
                    weight = 3.0 if match_year >= 2025 else (2.0 if match_year == 2024 else 1.0)

                    # Get PlayerMatchStats for this match, grouped by innings
                    stats_result = await session.execute(
                        select(PlayerMatchStats).where(PlayerMatchStats.match_id == match.id)
                    )
                    stats = stats_result.scalars().all()

                    inn1_runs = sum(s.runs for s in stats if s.innings_number == 1 and s.balls_faced > 0)
                    inn2_runs = sum(s.runs for s in stats if s.innings_number == 2 and s.balls_faced > 0)

                    if inn1_runs > 0:
                        first_inn_scores.append((inn1_runs, weight))
                    if inn2_runs > 0:
                        second_inn_scores.append((inn2_runs, weight))

                    # Pace vs spin: use bowling wickets by bowler role
                    for s in stats:
                        if s.wickets > 0:
                            player_result = await session.execute(
                                select(Player).where(Player.id == s.player_id)
                            )
                            player = player_result.scalar_one_or_none()
                            if player:
                                role_str = str(player.role).upper()
                                if "BOWL" in role_str or "PACE" in role_str:
                                    pace_wickets += s.wickets * weight
                                    total_wicket_weight += s.wickets * weight
                                elif "SPIN" in role_str:
                                    spin_wickets += s.wickets * weight
                                    total_wicket_weight += s.wickets * weight

                if first_inn_scores:
                    total_w = sum(w for _, w in first_inn_scores)
                    venue.avg_first_innings_score_t20 = sum(s * w for s, w in first_inn_scores) / total_w if total_w else None

                if second_inn_scores:
                    total_w = sum(w for _, w in second_inn_scores)
                    venue.avg_second_innings_score_t20 = sum(s * w for s, w in second_inn_scores) / total_w if total_w else None

                if total_wicket_weight > 0:
                    venue.pace_wickets_pct = round(pace_wickets / total_wicket_weight * 100, 1)
                    venue.spin_wickets_pct = round(spin_wickets / total_wicket_weight * 100, 1)

                updated += 1

            except Exception as exc:
                logger.warning(f"  venue stats error for {venue.name}: {exc}")
                continue

        await session.commit()

    return updated


# ---------------------------------------------------------------------------
# Summary helpers
# ---------------------------------------------------------------------------

async def get_db_counts() -> dict:
    async with AsyncSessionLocal() as session:
        matches = (await session.execute(
            select(func.count()).select_from(Match).where(Match.status == MatchStatus.COMPLETED)
        )).scalar_one()
        upcoming = (await session.execute(
            select(func.count()).select_from(Match).where(Match.status == MatchStatus.UPCOMING)
        )).scalar_one()
        players = (await session.execute(
            select(func.count()).select_from(Player)
        )).scalar_one()
        balls = (await session.execute(
            select(func.count()).select_from(BallByBall)
        )).scalar_one()
        venues = (await session.execute(
            select(func.count()).select_from(Venue)
        )).scalar_one()
        return {
            "matches_completed": matches,
            "matches_upcoming": upcoming,
            "players": players,
            "balls": balls,
            "venues": venues,
        }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    print("\n" + "=" * 60)
    print("  CricEdge — Dev Seed Script")
    print("  Loading IPL 2023-2025 + IPL 2026 fixtures")
    print("=" * 60 + "\n")

    # Step 1+2: Download full IPL archive and ingest
    print("\n[CRICSHEET] Downloading full IPL archive...")
    data_dir = await download_all_ipl()
    ingest_result = {"matches": 0, "balls": 0, "players": 0}
    if data_dir:
        print("[CRICSHEET] Ingesting matches...")
        ingest_result = await ingest_all(data_dir)
        print(f"[CRICSHEET] Done — {ingest_result['matches']} matches, {ingest_result['balls']:,} balls, {ingest_result['players']} players")

    # Step 3: IPL 2026 fixtures
    print("\n[2026] Fetching IPL 2026 upcoming fixtures from Cricbuzz...")
    fixtures_loaded = await load_ipl_2026_fixtures()
    print(f"[2026] {fixtures_loaded} upcoming fixtures loaded")

    # Step 4: Venue stats
    print("\n[VENUES] Updating venue stats from ingested data...")
    venues_updated = await update_venue_stats()
    print(f"[VENUES] Updated stats for {venues_updated} venues")

    # Final counts
    counts = await get_db_counts()

    print("\n" + "=" * 60)
    print(f"✓ Matches ingested: {counts['matches_completed']}")
    print(f"✓ Players created: {counts['players']}")
    print(f"✓ Ball-by-ball records: {counts['balls']:,}")
    print(f"✓ IPL 2026 upcoming fixtures loaded: {counts['matches_upcoming']}")
    print(f"✓ Venue stats updated: {counts['venues']}")
    print()
    print("  Dev environment ready.")
    print("  Backend:  http://localhost:8000")
    print("  Frontend: http://localhost:3000")
    print("  API docs: http://localhost:8000/docs")
    if not data_dir:
        print(f"\n⚠ Cricsheet download failed. Manual download:")
        print(f"    wget '{CRICSHEET_IPL_URL}' -O /tmp/ipl.zip")
        print(f"    unzip /tmp/ipl.zip -d {DATA_ROOT}/all/")
        print(f"    Then re-run: python scripts/seed_dev_data.py")

    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
