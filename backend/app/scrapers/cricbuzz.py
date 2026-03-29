"""
CricbuzzScraper — full scraper with retry, Redis caching, and DOM parsing.

All public methods return structured dataclasses. DOM parsing is wrapped in
try/except throughout so a single bad element never crashes the scraper.
"""
import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import httpx
import pytz
import redis.asyncio as aioredis
from bs4 import BeautifulSoup

from app.core.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://www.cricbuzz.com"
IST = pytz.timezone("Asia/Kolkata")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
]

_ua_index = 0


def _next_user_agent() -> str:
    global _ua_index
    ua = USER_AGENTS[_ua_index % len(USER_AGENTS)]
    _ua_index += 1
    return ua


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class MatchInfo:
    match_title: str
    date_time: datetime  # IST
    teams: list
    venue: str
    format: str
    competition: str
    match_url: str = ""


@dataclass
class PlayerInfo:
    name: str
    role: str
    playing_status: str  # "confirmed" | "not_announced" | "doubtful"


@dataclass
class PlayerStats:
    player_name: str
    formats: dict  # {"T20": {"matches": int, "runs": int, ...}, ...}
    recent_form: list


@dataclass
class BallEvent:
    over_ball: str
    runs: int
    is_wicket: bool
    description: str


# ---------------------------------------------------------------------------
# Scraper class
# ---------------------------------------------------------------------------

class CricbuzzScraper:
    def __init__(self, timeout: int = 30):
        self._timeout = timeout
        self._redis: Optional[aioredis.Redis] = None
        self._last_request_time: float = 0.0
        self.client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.client.aclose()
        if self._redis:
            await self._redis.aclose()

    def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        return self._redis

    async def _rate_limit(self):
        """Enforce minimum 2s between requests."""
        import time
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < 2.0:
            await asyncio.sleep(2.0 - elapsed)
        import time as t
        self._last_request_time = t.monotonic()

    async def scrape_with_retry(
        self, url: str, use_playwright: bool = False
    ) -> Optional[str]:
        """
        Fetch URL with 3 retries (exponential backoff 2s/4s/8s).
        Rotates user-agent on each attempt.
        Caches raw HTML in Redis for 1h.
        Returns HTML string or None on final failure.
        """
        url_hash = hashlib.md5(url.encode()).hexdigest()
        cache_key = f"cricbuzz:html:{url_hash}"

        # Check cache first
        try:
            r = self._get_redis()
            cached = await r.get(cache_key)
            if cached:
                logger.debug(f"Cache hit for {url}")
                return cached
        except Exception as e:
            logger.warning(f"Redis cache read failed for {url}: {e}")

        delays = [2, 4, 8]
        for attempt, delay in enumerate(delays, start=1):
            ua = _next_user_agent()
            try:
                await self._rate_limit()

                if use_playwright:
                    html = await self._fetch_with_playwright(url, ua)
                else:
                    response = await self.client.get(
                        url,
                        headers={
                            "User-Agent": ua,
                            "Accept-Language": "en-US,en;q=0.9",
                            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        },
                    )
                    response.raise_for_status()
                    html = response.text

                # Store in Redis with 1h TTL
                try:
                    r = self._get_redis()
                    await r.setex(cache_key, 3600, html)
                except Exception as cache_err:
                    logger.warning(f"Redis cache write failed for {url}: {cache_err}")

                return html

            except Exception as e:
                logger.warning(
                    f"scrape_with_retry attempt {attempt}/3 failed for {url}: {e}"
                )
                if attempt < len(delays):
                    await asyncio.sleep(delay)

        logger.error(f"scrape_with_retry: all 3 attempts failed for {url}")
        return None

    async def _fetch_with_playwright(self, url: str, ua: str) -> str:
        """Fetch JS-rendered page using Playwright."""
        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(user_agent=ua)
                page = await context.new_page()
                await page.goto(url, wait_until="networkidle", timeout=30000)
                html = await page.content()
                await browser.close()
                return html
        except Exception as e:
            raise RuntimeError(f"Playwright fetch failed for {url}: {e}") from e

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    async def get_upcoming_matches(self, days: int = 7) -> list:
        """
        Scrape upcoming matches from cricbuzz schedule page.
        Returns list[MatchInfo].
        """
        url = f"{BASE_URL}/cricket-schedule/upcoming-series/league"
        html = await self.scrape_with_retry(url)
        if not html:
            logger.warning("get_upcoming_matches: failed to fetch schedule page")
            return []

        matches = []
        try:
            soup = BeautifulSoup(html, "html.parser")

            # Cricbuzz is a Next.js app — parse schema.org SportsEvent structured data
            import json as _json
            from datetime import datetime as _dt, timezone as _tz
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    data = _json.loads(script.string or "")
                    events: list = []

                    def _extract(obj: any) -> None:
                        if isinstance(obj, dict):
                            if obj.get("@type") == "SportsEvent":
                                events.append(obj)
                            for v in obj.values():
                                _extract(v)
                        elif isinstance(obj, list):
                            for item in obj:
                                _extract(item)

                    _extract(data)
                    for ev in events:
                        try:
                            teams = [c.get("name", "") for c in ev.get("competitor", [])]
                            if len(teams) < 2:
                                continue
                            start_raw = ev.get("startDate", "")
                            start_dt = _dt.fromisoformat(start_raw.replace("Z", "+00:00")) if start_raw else None
                            venue_raw = ev.get("location", "")
                            venue_parts = venue_raw.split(",")
                            venue_name = venue_parts[0].strip() if venue_parts else venue_raw
                            competition = ev.get("name", "")
                            # Extract series name from event name e.g. "3rd Match, Indian Premier League 2026"
                            series = re.sub(r"^\d+(?:st|nd|rd|th) Match,\s*", "", competition).strip()
                            matches.append(MatchInfo(
                                match_title=f"{teams[0]} vs {teams[1]}",
                                date_time=start_dt.astimezone(IST) if start_dt else _dt.now(IST),
                                teams=teams,
                                venue=venue_name,
                                format="T20",
                                competition=series,
                            ))
                        except Exception as e:
                            logger.debug(f"SportsEvent parse error: {e}")
                except Exception:
                    pass

        except Exception as e:
            logger.warning(f"get_upcoming_matches parse error: {e}")

        logger.info(f"get_upcoming_matches: found {len(matches)} matches")
        return matches

    def _parse_match_card(self, card) -> Optional[MatchInfo]:
        """Parse a single match card element into MatchInfo."""
        try:
            # Extract match title / description
            title_el = (
                card.find("div", class_=re.compile(r"cb-card-match-title|cb-mtch-txt"))
                or card.find("a", class_=re.compile(r"match"))
                or card.find("span", class_=re.compile(r"title"))
            )
            match_title = title_el.get_text(strip=True) if title_el else "Unknown Match"

            # Extract teams — look for team name spans
            team_els = card.find_all(
                "div", class_=re.compile(r"cb-team|team-name", re.I)
            ) or card.find_all("span", class_=re.compile(r"team", re.I))
            teams = [el.get_text(strip=True) for el in team_els[:2] if el.get_text(strip=True)]
            if not teams:
                # Try to parse from title
                if " vs " in match_title.lower():
                    parts = re.split(r"\s+vs\s+", match_title, flags=re.I)
                    teams = [p.strip() for p in parts[:2]]

            # Extract venue
            venue_el = card.find("div", class_=re.compile(r"venue|ground|stadium", re.I))
            venue = venue_el.get_text(strip=True) if venue_el else ""

            # Extract date/time
            time_el = (
                card.find("div", class_=re.compile(r"cb-mtch-info|schedule-date|time", re.I))
                or card.find("span", class_=re.compile(r"time|date", re.I))
            )
            date_str = time_el.get_text(strip=True) if time_el else ""
            parsed_dt = self._parse_datetime_ist(date_str)

            # Extract format
            format_el = card.find(string=re.compile(r"\bT20\b|\bODI\b|\bTest\b|\bT10\b", re.I))
            match_format = "T20"
            if format_el:
                m = re.search(r"\b(T20|ODI|Test|T10)\b", str(format_el), re.I)
                if m:
                    match_format = m.group(1).upper()

            # Extract competition
            comp_el = card.find("div", class_=re.compile(r"series|competition|comp", re.I))
            competition = comp_el.get_text(strip=True) if comp_el else ""

            # Extract match URL
            link_el = card.find("a", href=True)
            match_url = ""
            if link_el:
                href = link_el["href"]
                match_url = href if href.startswith("http") else f"{BASE_URL}{href}"

            if not match_title or match_title == "Unknown Match":
                return None

            return MatchInfo(
                match_title=match_title,
                date_time=parsed_dt,
                teams=teams,
                venue=venue,
                format=match_format,
                competition=competition,
                match_url=match_url,
            )
        except Exception as e:
            logger.warning(f"_parse_match_card inner error: {e}")
            return None

    def _parse_datetime_ist(self, date_str: str) -> datetime:
        """Parse a date/time string and return IST datetime. Falls back to now()."""
        formats = [
            "%b %d, %Y %H:%M",
            "%d %b %Y %H:%M",
            "%b %d %Y, %H:%M",
            "%Y-%m-%d %H:%M",
            "%d/%m/%Y %H:%M",
        ]
        for fmt in formats:
            try:
                naive = datetime.strptime(date_str.strip(), fmt)
                return IST.localize(naive)
            except ValueError:
                continue

        # Try to extract a partial datetime
        try:
            m = re.search(
                r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})[,\s]+(\d{1,2}):(\d{2})",
                date_str,
            )
            if m:
                day, month_abbr, year, hour, minute = m.groups()
                naive = datetime.strptime(
                    f"{day} {month_abbr} {year} {hour}:{minute}", "%d %b %Y %H:%M"
                )
                return IST.localize(naive)
        except Exception:
            pass

        return IST.localize(datetime.now())

    async def get_match_squads(self, match_url: str) -> dict:
        """
        Fetch and parse squad tables from a match page.
        Returns {"team1": [PlayerInfo...], "team2": [PlayerInfo...]}.
        """
        html = await self.scrape_with_retry(match_url)
        if not html:
            logger.warning(f"get_match_squads: failed to fetch {match_url}")
            return {"team1": [], "team2": []}

        team1_players = []
        team2_players = []

        try:
            soup = BeautifulSoup(html, "html.parser")

            # Squad tables are typically in divs with class cb-squad or similar
            squad_tables = soup.find_all(
                "div", class_=re.compile(r"cb-squad|squad|playing-xi", re.I)
            )

            # Also check for table elements
            if not squad_tables:
                squad_tables = soup.find_all("table", class_=re.compile(r"squad|xi|team", re.I))

            teams_parsed = []
            for table in squad_tables[:2]:
                try:
                    players = self._parse_squad_table(table)
                    if players:
                        teams_parsed.append(players)
                except Exception as e:
                    logger.warning(f"Failed to parse squad table: {e}")

            if len(teams_parsed) >= 1:
                team1_players = teams_parsed[0]
            if len(teams_parsed) >= 2:
                team2_players = teams_parsed[1]

            # Fallback: look for player links
            if not team1_players and not team2_players:
                all_players = self._parse_players_from_links(soup)
                mid = len(all_players) // 2
                team1_players = all_players[:mid]
                team2_players = all_players[mid:]

        except Exception as e:
            logger.warning(f"get_match_squads parse error for {match_url}: {e}")

        return {"team1": team1_players, "team2": team2_players}

    def _parse_squad_table(self, table) -> list:
        """Parse a squad table element into list of PlayerInfo."""
        players = []
        try:
            rows = table.find_all("tr") or table.find_all("div", class_=re.compile(r"player|row"))
            for row in rows:
                try:
                    cells = row.find_all(["td", "div"])
                    if not cells:
                        continue
                    name = cells[0].get_text(strip=True) if cells else ""
                    if not name or len(name) < 3:
                        continue
                    role = cells[1].get_text(strip=True) if len(cells) > 1 else "Unknown"
                    status_text = cells[2].get_text(strip=True).lower() if len(cells) > 2 else ""
                    playing_status = self._infer_playing_status(status_text, row)
                    players.append(PlayerInfo(name=name, role=role, playing_status=playing_status))
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"_parse_squad_table error: {e}")
        return players

    def _parse_players_from_links(self, soup) -> list:
        """Fallback: extract player names from player profile links."""
        players = []
        try:
            links = soup.find_all("a", href=re.compile(r"/profiles/\d+/"))
            seen = set()
            for link in links:
                name = link.get_text(strip=True)
                if name and name not in seen and len(name) > 2:
                    seen.add(name)
                    players.append(PlayerInfo(
                        name=name,
                        role="Unknown",
                        playing_status="not_announced",
                    ))
        except Exception as e:
            logger.warning(f"_parse_players_from_links error: {e}")
        return players

    def _infer_playing_status(self, status_text: str, row_el) -> str:
        """Infer playing status from text content."""
        if not status_text:
            # Check CSS classes on the row
            try:
                classes = " ".join(row_el.get("class", []))
                if re.search(r"confirmed|playing", classes, re.I):
                    return "confirmed"
                if re.search(r"doubt|uncertain|injury", classes, re.I):
                    return "doubtful"
            except Exception:
                pass
            return "not_announced"

        if re.search(r"confirmed|playing|in xi", status_text, re.I):
            return "confirmed"
        if re.search(r"doubt|uncertain|may not|injury|injured", status_text, re.I):
            return "doubtful"
        return "not_announced"

    async def get_player_stats(self, player_url: str) -> Optional[PlayerStats]:
        """
        Scrape career stats tables from a player profile page.
        Returns PlayerStats with T20/ODI/Test format breakdowns and recent form.
        """
        html = await self.scrape_with_retry(player_url)
        if not html:
            logger.warning(f"get_player_stats: failed to fetch {player_url}")
            return None

        player_name = ""
        formats_data: dict = {}
        recent_form: list = []

        try:
            soup = BeautifulSoup(html, "html.parser")

            # Extract player name
            name_el = (
                soup.find("h1", class_=re.compile(r"player.*name|profile.*name", re.I))
                or soup.find("h1")
            )
            if name_el:
                player_name = name_el.get_text(strip=True)

            # Stats tables
            stat_tables = soup.find_all("table", class_=re.compile(r"stat|career|batting|bowling", re.I))
            if not stat_tables:
                stat_tables = soup.select("div.cb-col-100 table")

            for table in stat_tables:
                try:
                    parsed = self._parse_stats_table(table)
                    formats_data.update(parsed)
                except Exception as e:
                    logger.warning(f"Failed to parse stats table: {e}")

            # Recent form: look for score patterns in recent innings
            try:
                recent_el = soup.find(
                    "div", class_=re.compile(r"recent.*form|last.*innings|form", re.I)
                )
                if recent_el:
                    score_texts = re.findall(r"\b(\d{1,3})\*?\b", recent_el.get_text())
                    recent_form = [int(s) for s in score_texts[:5]]
            except Exception as e:
                logger.warning(f"Failed to parse recent form: {e}")

        except Exception as e:
            logger.warning(f"get_player_stats parse error for {player_url}: {e}")

        if not player_name and not formats_data:
            return None

        return PlayerStats(
            player_name=player_name,
            formats=formats_data,
            recent_form=recent_form,
        )

    def _parse_stats_table(self, table) -> dict:
        """Parse a stats table and return format-keyed dict."""
        result = {}
        try:
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            rows = table.find_all("tr")

            for row in rows[1:]:  # skip header row
                cells = row.find_all("td")
                if not cells:
                    continue
                try:
                    row_format = cells[0].get_text(strip=True).upper()
                    if row_format not in ("T20", "ODI", "TEST", "T20I", "LIST A", "FC"):
                        continue

                    # Normalise format names
                    if row_format == "T20I":
                        row_format = "T20"

                    cell_vals = [c.get_text(strip=True) for c in cells]

                    def safe_int(v: str) -> int:
                        try:
                            return int(v.replace(",", "").replace("-", "0") or 0)
                        except ValueError:
                            return 0

                    def safe_float(v: str) -> float:
                        try:
                            return float(v.replace("-", "0") or 0)
                        except ValueError:
                            return 0.0

                    # Try to align to known column positions
                    # Typical: Format | Matches | Runs | Avg | SR | Wickets | Bowl_Avg | Economy
                    result[row_format] = {
                        "matches": safe_int(cell_vals[1]) if len(cell_vals) > 1 else 0,
                        "runs": safe_int(cell_vals[2]) if len(cell_vals) > 2 else 0,
                        "avg": safe_float(cell_vals[3]) if len(cell_vals) > 3 else 0.0,
                        "sr": safe_float(cell_vals[4]) if len(cell_vals) > 4 else 0.0,
                        "wickets": safe_int(cell_vals[5]) if len(cell_vals) > 5 else 0,
                        "bowling_avg": safe_float(cell_vals[6]) if len(cell_vals) > 6 else 0.0,
                        "economy": safe_float(cell_vals[7]) if len(cell_vals) > 7 else 0.0,
                    }
                except Exception as e:
                    logger.warning(f"Row parse error in stats table: {e}")
                    continue

        except Exception as e:
            logger.warning(f"_parse_stats_table error: {e}")

        return result

    async def get_match_commentary(self, match_id: str) -> list:
        """
        Fetch ball-by-ball commentary for a live/recent match.
        Returns list[BallEvent].
        """
        url = f"{BASE_URL}/cricket-match/live-scores/{match_id}"
        html = await self.scrape_with_retry(url)
        if not html:
            logger.warning(f"get_match_commentary: failed to fetch match {match_id}")
            return []

        events: list = []
        try:
            soup = BeautifulSoup(html, "html.parser")

            # Commentary items — multiple possible selectors
            commentary_els = (
                soup.find_all("div", class_=re.compile(r"cb-col-commentary|commentary", re.I))
                or soup.find_all("p", class_=re.compile(r"commentary", re.I))
                or soup.select("div.cb-text-complete, div.cb-text-inprog, div.cb-text-bowling")
            )

            for el in commentary_els:
                try:
                    event = self._parse_commentary_element(el)
                    if event:
                        events.append(event)
                except Exception as e:
                    logger.warning(f"Failed to parse commentary element: {e}")
                    continue

        except Exception as e:
            logger.warning(f"get_match_commentary parse error for match {match_id}: {e}")

        return events

    def _parse_commentary_element(self, el) -> Optional[BallEvent]:
        """Parse a commentary DOM element into BallEvent."""
        try:
            text = el.get_text(strip=True)
            if not text:
                return None

            # Extract over.ball — look for pattern like "4.2" or "Over 4.2"
            over_match = re.search(r"\b(\d{1,3}\.\d)\b", text)
            over_ball = over_match.group(1) if over_match else "0.0"

            # Extract runs from text patterns like "1 run", "no run", "FOUR", "SIX"
            runs = 0
            if re.search(r"\bno[ -]run\b", text, re.I):
                runs = 0
            elif re.search(r"\bfour\b|boundary", text, re.I):
                runs = 4
            elif re.search(r"\bsix\b", text, re.I):
                runs = 6
            else:
                runs_match = re.search(r"\b(\d)\s*run", text, re.I)
                if runs_match:
                    runs = int(runs_match.group(1))

            # Detect wicket
            is_wicket = bool(
                re.search(r"\bwicket\b|out\b|caught\b|bowled\b|lbw\b|stumped\b|run out\b", text, re.I)
            )
            if is_wicket:
                runs = 0  # Wickets count as 0 fantasy runs for the batter

            return BallEvent(
                over_ball=over_ball,
                runs=runs,
                is_wicket=is_wicket,
                description=text[:300],  # cap description length
            )
        except Exception as e:
            logger.warning(f"_parse_commentary_element error: {e}")
            return None

    # Keep legacy methods for backward compatibility with existing tasks
    async def fetch_live_matches(self) -> list[dict]:
        """Legacy method — delegates to get_upcoming_matches."""
        matches = await self.get_upcoming_matches()
        return [
            {
                "match_title": m.match_title,
                "teams": m.teams,
                "venue": m.venue,
                "format": m.format,
                "competition": m.competition,
                "match_url": m.match_url,
            }
            for m in matches
        ]

    async def fetch_match_scorecard(self, cricbuzz_match_id: str) -> Optional[dict]:
        """Legacy method — fetch raw scorecard data."""
        url = f"{BASE_URL}/cricket-scores/{cricbuzz_match_id}"
        html = await self.scrape_with_retry(url)
        if not html:
            return None
        return {"match_id": cricbuzz_match_id, "raw": True}

    async def fetch_playing_xi(self, cricbuzz_match_id: str) -> dict:
        """Legacy method — delegates to get_match_squads."""
        url = f"{BASE_URL}/cricket-match-squads/{cricbuzz_match_id}"
        squads = await self.get_match_squads(url)
        return {
            "team_a": [{"name": p.name, "role": p.role} for p in squads["team1"]],
            "team_b": [{"name": p.name, "role": p.role} for p in squads["team2"]],
        }
