#!/usr/bin/env python3
"""
Scrape IPL 2026 squad data from Cricbuzz and update player ipl_team fields.
Uses Playwright to render the JS-heavy Cricbuzz pages.

Usage:
    docker exec cricedge-backend-1 python scripts/scrape_ipl2026_squads.py
    docker exec cricedge-backend-1 python scripts/scrape_ipl2026_squads.py --dry-run
"""

import asyncio
import argparse
import re
import sys
import os

sys.path.insert(0, "/app")

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://cricedge:cricedge@postgres:5432/cricedge")

IPL_2026_SERIES_ID = 9241
SQUADS_URL = f"https://www.cricbuzz.com/cricket-series/{IPL_2026_SERIES_ID}/indian-premier-league-2026/squads"

TEAMS = [
    "Chennai Super Kings",
    "Delhi Capitals",
    "Gujarat Titans",
    "Royal Challengers Bengaluru",
    "Punjab Kings",
    "Kolkata Knight Riders",
    "Sunrisers Hyderabad",
    "Rajasthan Royals",
    "Lucknow Super Giants",
    "Mumbai Indians",
]

# Manual name overrides: Cricsheet abbreviated name -> IPL team
# These players exist in DB under abbreviated Cricsheet names
CRICSHEET_NAME_OVERRIDES = {
    "V Kohli": "Royal Challengers Bengaluru",
    "RG Sharma": "Mumbai Indians",
    "HH Pandya": "Mumbai Indians",
    "N Rana": "Delhi Capitals",
    "MK Pandey": "Kolkata Knight Riders",
    "SS Iyer": "Punjab Kings",
    "HV Patel": "Sunrisers Hyderabad",
    "B Kumar": "Royal Challengers Bengaluru",
    "DL Chahar": "Mumbai Indians",
    "KH Pandya": "Royal Challengers Bengaluru",
    "C Green": "Kolkata Knight Riders",
    "MR Marsh": "Lucknow Super Giants",
    "AR Patel": "Delhi Capitals",
    "PWH de Silva": "Lucknow Super Giants",
    "RD Chahar": "Chennai Super Kings",
    "AS Roy": "Kolkata Knight Riders",
    "Nithish Kumar Reddy": "Sunrisers Hyderabad",
    "VG Arora": "Kolkata Knight Riders",
}


async def scrape_squads() -> dict[str, list[str]]:
    """Scrape all team squads from Cricbuzz IPL 2026 squads page."""
    from playwright.async_api import async_playwright

    squads: dict[str, list[str]] = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            executable_path="/usr/bin/chromium",
            args=[
                "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36"
            ),
            locale="en-IN",
            timezone_id="Asia/Kolkata",
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )

        page = await context.new_page()

        # Warm up with main page first to get cookies
        await page.goto("https://www.cricbuzz.com", timeout=15000)
        await asyncio.sleep(1)

        for team_name in TEAMS:
            await page.goto(SQUADS_URL, timeout=25000)
            await asyncio.sleep(3)

            # Click the team div using JS
            await page.evaluate(f"""
                () => {{
                    const divs = document.querySelectorAll('div.w-full.px-4.py-2');
                    for (const div of divs) {{
                        const span = div.querySelector('span:first-child');
                        if (span && span.innerText.trim() === {repr(team_name)}) {{
                            div.click();
                            return;
                        }}
                    }}
                }}
            """)
            await asyncio.sleep(2)

            # Parse player names from body text sections
            body = await page.evaluate("() => document.body.innerText")
            lines = body.split("\n")
            players = []
            in_squad = False

            for line in lines:
                line = line.strip()
                if line in ("BATTERS", "ALL ROUNDERS", "WICKET KEEPERS", "BOWLERS"):
                    in_squad = True
                    continue
                if line in TEAMS or line in ("APPS", "Android", "iOS", "FOLLOW US ON", "COMPANY"):
                    in_squad = False
                if in_squad and line and line not in (
                    "Batsman", "Batting Allrounder", "Bowling Allrounder",
                    "WK-Batsman", "Bowler", "Captain",
                ):
                    name = re.sub(r"\s*\(.*?\)", "", line).strip()
                    if name and len(name) > 2:
                        players.append(name)

            squads[team_name] = players
            print(f"  {team_name}: {len(players)} players")

        await browser.close()

    return squads


def normalize(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip()).lower()


async def update_db(squads: dict[str, list[str]], dry_run: bool = False) -> None:
    """Match scraped players to DB records and update ipl_team."""
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        result = await session.execute(text("SELECT id, name FROM players"))
        db_players = {normalize(row.name): str(row.id) for row in result}
        print(f"\nDB has {len(db_players)} players")

        if not dry_run:
            # Clear all existing IPL team assignments
            await session.execute(text("UPDATE players SET ipl_team = NULL"))

        total_matched = 0
        unmatched_list = []

        for team, players in squads.items():
            for name in players:
                norm = normalize(name)
                pid = db_players.get(norm)

                if not pid:
                    # Fuzzy: last name match
                    last = norm.split()[-1]
                    candidates = [k for k in db_players if k.split()[-1] == last]
                    if len(candidates) == 1:
                        pid = db_players[candidates[0]]
                    elif len(candidates) > 1:
                        first = norm.split()[0]
                        candidates2 = [k for k in candidates if k.split()[0] == first]
                        if len(candidates2) == 1:
                            pid = db_players[candidates2[0]]

                if pid:
                    if not dry_run:
                        await session.execute(
                            text("UPDATE players SET ipl_team = :team WHERE id = :id"),
                            {"team": team, "id": pid},
                        )
                    total_matched += 1
                else:
                    unmatched_list.append(f"{name} ({team})")

        # Apply Cricsheet name overrides
        for cricsheet_name, team in CRICSHEET_NAME_OVERRIDES.items():
            if not dry_run:
                await session.execute(
                    text("UPDATE players SET ipl_team = :team WHERE LOWER(name) = LOWER(:name)"),
                    {"team": team, "name": cricsheet_name},
                )

        if not dry_run:
            await session.commit()

        # Summary by team
        if not dry_run:
            result = await session.execute(text(
                "SELECT ipl_team, COUNT(*) FROM players WHERE ipl_team IS NOT NULL GROUP BY ipl_team ORDER BY ipl_team"
            ))
            print("\nPlayers per team:")
            total = 0
            for r in result:
                print(f"  {r[0]}: {r[1]}")
                total += r[1]
            print(f"  TOTAL: {total}")

        mode = "DRY RUN — " if dry_run else ""
        print(f"\n{mode}{total_matched} players matched from scrape")
        if unmatched_list:
            print(f"{len(unmatched_list)} unmatched (new players not in historical data):")
            for u in unmatched_list[:20]:
                print(f"  - {u}")
            if len(unmatched_list) > 20:
                print(f"  ... and {len(unmatched_list) - 20} more")

    await engine.dispose()


async def main(dry_run: bool = False) -> None:
    print("=== IPL 2026 Squad Scraper ===\n")
    print(f"Scraping: {SQUADS_URL}\n")

    squads = await scrape_squads()

    if not squads:
        print("ERROR: No squad data scraped.")
        sys.exit(1)

    await update_db(squads, dry_run=dry_run)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
