#!/usr/bin/env python3
"""
Bootstrap IPL 2026 data from Cricbuzz API.

Run ONCE to seed the database before the tournament.
Completes in ≤27 API calls, leaving 173+ calls for the season.

Usage:
    python scripts/bootstrap_cricbuzz_data.py
    python scripts/bootstrap_cricbuzz_data.py --dry-run
"""
import asyncio
import argparse
import sys
import os

# Allow running from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.cricbuzz_client import CricbuzzClient, IPL_2026_SQUADS
from app.core.config import settings


def _step(n: int, total: int, msg: str, dry_run: bool = False) -> None:
    prefix = "[DRY-RUN]" if dry_run else ""
    tick = "~" if dry_run else "✓"
    print(f"[{n}/{total}] {tick} {prefix} {msg}")


async def bootstrap(dry_run: bool = False) -> None:
    TOTAL_STEPS = 27  # 1 schedule + 10 squads + 16 venues (8 × 2)
    step = 0
    client = CricbuzzClient()

    players_synced = 0
    matches_synced = 0
    venues_synced = 0

    print(f"\nCricEdge Bootstrap — IPL 2026 (seriesId: {settings.IPL_2026_SERIES_ID})")
    print(f"Mode: {'DRY RUN — no API calls will be made' if dry_run else 'LIVE'}")
    print(f"Monthly limit: {settings.CRICBUZZ_MONTHLY_LIMIT} calls\n")

    # -----------------------------------------------------------------------
    # Step 1: IPL Schedule
    # -----------------------------------------------------------------------
    step += 1
    if not dry_run:
        from app.core.database import AsyncSessionLocal
        from app.services.data_sync import DataSyncService
        async with AsyncSessionLocal() as db:
            svc = DataSyncService(db, client)
            result = await svc.sync_ipl_schedule()
        matches_synced = result["new"] + result.get("updated", 0)
        _step(step, TOTAL_STEPS, f"IPL 2026 schedule synced — {matches_synced} matches loaded")
    else:
        matches_synced = 74
        _step(step, TOTAL_STEPS, f"IPL 2026 schedule would be synced — ~74 matches expected", dry_run=True)

    # -----------------------------------------------------------------------
    # Steps 2–11: All 10 team squads
    # -----------------------------------------------------------------------
    team_player_counts: dict[str, int] = {}
    for team_name, squad_info in IPL_2026_SQUADS.items():
        step += 1
        squad_id = squad_info["squadId"]
        if not dry_run:
            from app.core.database import AsyncSessionLocal
            from app.services.data_sync import DataSyncService
            async with AsyncSessionLocal() as db:
                svc = DataSyncService(db, client)
                data = await client.get_team_players(squad_id)
                raw_players = svc._extract_players(data)
                count = await svc._upsert_players(raw_players, team_name, squad_id)
            players_synced += count
            team_player_counts[team_name] = count
            _step(step, TOTAL_STEPS, f"{team_name} squad synced — {count} players")
        else:
            est = 22  # typical IPL squad size
            players_synced += est
            team_player_counts[team_name] = est
            _step(step, TOTAL_STEPS, f"{team_name} squad would be synced — ~{est} players expected", dry_run=True)

    # -----------------------------------------------------------------------
    # Steps 12–27: Venue data (8 IPL venues × 2 calls each = 16 calls)
    # -----------------------------------------------------------------------
    ipl_venue_ids: list[int] = []

    if not dry_run:
        # Pull venue IDs from the cached schedule (no API call)
        import json
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        raw = await r.get("cricbuzz:ipl:schedule")
        await r.aclose()
        if raw:
            schedule = json.loads(raw)
            venue_ids_seen: set[int] = set()
            for day in schedule.get("matchDetails", []):
                for m in day.get("matchDetailsMap", {}).get("match", []):
                    vi = m.get("matchInfo", {}).get("venueInfo", {})
                    vid = vi.get("id")
                    if vid:
                        venue_ids_seen.add(int(vid))
            ipl_venue_ids = list(venue_ids_seen)[:8]
    else:
        # Mock venue IDs for dry-run display
        ipl_venue_ids = list(range(101, 109))  # 8 placeholder IDs

    if not ipl_venue_ids:
        print("  ⚠  No venue IDs found in schedule. Skipping venue sync.")
        print("     (Run sync_ipl_schedule_task first if schedule is empty.)")
        # Still count the steps
        for i in range(16):
            step += 1
    else:
        for vid in ipl_venue_ids:
            step += 1
            if step > TOTAL_STEPS:
                break
            if not dry_run:
                from app.core.database import AsyncSessionLocal
                from app.services.data_sync import DataSyncService
                try:
                    async with AsyncSessionLocal() as db:
                        svc = DataSyncService(db, client)
                        res = await svc.sync_venue_data(vid)
                    venues_synced += 1
                    venue_name = res.get("name", f"Venue {vid}")
                    _step(step, TOTAL_STEPS, f"{venue_name} venue stats synced")
                except Exception as e:
                    print(f"[{step}/{TOTAL_STEPS}] ⚠  Venue {vid} skipped: {e}")
            else:
                venues_synced += 1
                _step(step, TOTAL_STEPS, f"Venue {vid} stats would be synced", dry_run=True)
                step += 1  # each venue = 1 real call (stats only, info from schedule cache)

    await client.close()

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    calls_used = 0 if dry_run else await _get_calls_used()
    remaining = settings.CRICBUZZ_MONTHLY_LIMIT - calls_used
    player_count = players_synced
    days_to_full_coverage = max(1, round(player_count / 10))  # 20 calls/day = 10 players/day

    print(f"""
Bootstrap {'(DRY RUN) ' if dry_run else ''}complete.
─────────────────────────────────────────
API calls used:         {calls_used if not dry_run else '~27 (estimated)'}
Remaining budget:       {remaining if not dry_run else f'~{settings.CRICBUZZ_MONTHLY_LIMIT - 27} (estimated)'}
Players in DB:          {player_count}
Matches in DB:          {matches_synced}
Venues in DB:           {venues_synced}
─────────────────────────────────────────
Player stats will sync in background via Celery (20 calls/day).
Estimated days to full stats coverage: {days_to_full_coverage} days

Next step:
  celery -A app.tasks.celery_app worker --beat --loglevel=info
""")


async def _get_calls_used() -> int:
    import redis.asyncio as aioredis
    try:
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        val = await r.get("cricbuzz:usage:monthly")
        await r.aclose()
        return int(val or 0)
    except Exception:
        return 0


def main():
    parser = argparse.ArgumentParser(description="Bootstrap CricEdge with IPL 2026 Cricbuzz data")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be fetched without making API calls",
    )
    args = parser.parse_args()
    asyncio.run(bootstrap(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
