"""
ESPNScraper — pitch reports, head-to-head, and player vs team stats.

Uses Playwright for JS-rendered pages (pitch reports).
All DOM parsing wrapped in try/except for resilience.
"""
import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass
from typing import Optional

import httpx
import redis.asyncio as aioredis
from bs4 import BeautifulSoup

from app.core.config import settings

logger = logging.getLogger(__name__)

ESPN_BASE = "https://www.espncricinfo.com"
ESPN_API_BASE = "https://site.api.espn.com/apis/site/v2/sports/cricket"

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
class PitchReport:
    pitch_type: str          # "batting" | "bowling" | "spin" | "balanced"
    bounce_rating: int       # 1-5
    spin_rating: int         # 1-5
    pace_rating: int         # 1-5
    curator_quote: str
    raw_report: str


# ---------------------------------------------------------------------------
# Scraper class
# ---------------------------------------------------------------------------

class ESPNScraper:
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
        cache_key = f"espn:html:{url_hash}"

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
                    f"ESPNScraper scrape_with_retry attempt {attempt}/3 failed for {url}: {e}"
                )
                if attempt < len(delays):
                    await asyncio.sleep(delay)

        logger.error(f"ESPNScraper scrape_with_retry: all 3 attempts failed for {url}")
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

    async def get_pitch_report(self, match_id: str) -> Optional[PitchReport]:
        """
        Scrape pitch report from ESPN match preview page (JS-rendered).
        Returns PitchReport or None.
        """
        url = f"{ESPN_BASE}/series/_/id/{match_id}/match-preview"
        html = await self.scrape_with_retry(url, use_playwright=True)
        if not html:
            logger.warning(f"get_pitch_report: failed to fetch {url}")
            return None

        try:
            soup = BeautifulSoup(html, "html.parser")
            return self._parse_pitch_report(soup)
        except Exception as e:
            logger.warning(f"get_pitch_report parse error for match {match_id}: {e}")
            return None

    def _parse_pitch_report(self, soup) -> Optional[PitchReport]:
        """Parse pitch report section from BeautifulSoup."""
        raw_report = ""
        curator_quote = ""

        try:
            # Find pitch report section using multiple selector strategies
            pitch_el = (
                soup.find("div", class_=re.compile(r"pitch.*report|pitch.*preview", re.I))
                or soup.find("section", class_=re.compile(r"pitch", re.I))
                or soup.find(string=re.compile(r"pitch report|pitch condition", re.I))
            )

            if pitch_el:
                if hasattr(pitch_el, "get_text"):
                    raw_report = pitch_el.get_text(separator=" ", strip=True)
                else:
                    # NavigableString — get parent
                    raw_report = pitch_el.parent.get_text(separator=" ", strip=True) if pitch_el.parent else str(pitch_el)
            else:
                # Fallback: search entire page for pitch-related text
                text_content = soup.get_text(separator=" ")
                m = re.search(
                    r"(pitch[^.]{0,500}(?:batting|bowling|spin|pace|bounce|turn)[^.]*\.)",
                    text_content,
                    re.I | re.DOTALL,
                )
                if m:
                    raw_report = m.group(1).strip()

            if not raw_report:
                return None

            # Extract curator quote if present
            quote_el = soup.find("blockquote") or soup.find("q")
            if quote_el:
                curator_quote = quote_el.get_text(strip=True)
            else:
                # Look for quoted speech in raw_report
                quote_m = re.search(r'"([^"]{10,200})"', raw_report)
                if quote_m:
                    curator_quote = quote_m.group(1)

            pitch_type = self._infer_pitch_type(raw_report)
            bounce_rating = self._infer_rating(raw_report, ["bounce", "carry", "lively"], ["flat", "low", "slow"])
            spin_rating = self._infer_rating(raw_report, ["spin", "turn", "spinning", "spinner"], ["pace", "seam", "flat"])
            pace_rating = self._infer_rating(raw_report, ["pace", "seam", "swing", "movement"], ["spin", "slow", "flat"])

            return PitchReport(
                pitch_type=pitch_type,
                bounce_rating=bounce_rating,
                spin_rating=spin_rating,
                pace_rating=pace_rating,
                curator_quote=curator_quote,
                raw_report=raw_report[:1000],
            )

        except Exception as e:
            logger.warning(f"_parse_pitch_report error: {e}")
            return None

    def _infer_pitch_type(self, text: str) -> str:
        """Infer pitch type from text description."""
        text_lower = text.lower()
        scores = {
            "batting": 0,
            "bowling": 0,
            "spin": 0,
            "balanced": 0,
        }

        batting_keywords = ["batting paradise", "flat track", "high scoring", "batsman's dream", "good for batting"]
        bowling_keywords = ["bowler's pitch", "seam friendly", "swing", "movement", "tough for batsmen"]
        spin_keywords = ["spin friendly", "turn", "spinners will", "dry", "dusty", "crumbling"]
        balanced_keywords = ["balanced", "even contest", "something for everyone"]

        for kw in batting_keywords:
            if kw in text_lower:
                scores["batting"] += 2
        for kw in bowling_keywords:
            if kw in text_lower:
                scores["bowling"] += 2
        for kw in spin_keywords:
            if kw in text_lower:
                scores["spin"] += 2
        for kw in balanced_keywords:
            if kw in text_lower:
                scores["balanced"] += 2

        # Single-word fallbacks
        if re.search(r"\bbatting\b", text_lower):
            scores["batting"] += 1
        if re.search(r"\bbowling\b", text_lower):
            scores["bowling"] += 1
        if re.search(r"\bspin\b", text_lower):
            scores["spin"] += 1

        best = max(scores, key=lambda k: scores[k])
        if scores[best] == 0:
            return "balanced"
        return best

    def _infer_rating(self, text: str, positive_kws: list, negative_kws: list) -> int:
        """Compute 1-5 rating based on keyword presence."""
        text_lower = text.lower()
        score = 3  # neutral start

        for kw in positive_kws:
            if kw in text_lower:
                score += 1

        for kw in negative_kws:
            if kw in text_lower:
                score -= 1

        return max(1, min(5, score))

    async def get_head_to_head(
        self, team1: str, team2: str, format: str
    ) -> dict:
        """
        Fetch head-to-head stats between two teams.
        Returns structured h2h dict.
        """
        # Build ESPN search URL for h2h
        search_query = f"{team1} vs {team2} {format}"
        url_slug = search_query.lower().replace(" ", "-")
        url = f"{ESPN_BASE}/cricket/series/_/format/{format.lower()}"

        html = await self.scrape_with_retry(url)

        # Default structure
        result: dict = {
            "last_10": [],
            "team1_wins": 0,
            "team2_wins": 0,
            "no_result": 0,
            "team1_avg_score": 0.0,
            "team2_avg_score": 0.0,
        }

        if not html:
            logger.warning(f"get_head_to_head: failed to fetch data for {team1} vs {team2}")
            return result

        try:
            soup = BeautifulSoup(html, "html.parser")
            result = self._parse_h2h_data(soup, team1, team2, result)
        except Exception as e:
            logger.warning(f"get_head_to_head parse error: {e}")

        return result

    def _parse_h2h_data(self, soup, team1: str, team2: str, default: dict) -> dict:
        """Parse h2h data from BeautifulSoup object."""
        result = default.copy()
        try:
            rows = soup.find_all("tr", class_=re.compile(r"match|result", re.I))
            for row in rows[:10]:
                try:
                    cells = row.find_all("td")
                    if len(cells) < 3:
                        continue
                    winner = cells[0].get_text(strip=True)
                    margin = cells[1].get_text(strip=True) if len(cells) > 1 else ""
                    date = cells[2].get_text(strip=True) if len(cells) > 2 else ""

                    result["last_10"].append({
                        "winner": winner,
                        "margin": margin,
                        "date": date,
                    })

                    if team1.lower() in winner.lower():
                        result["team1_wins"] += 1
                    elif team2.lower() in winner.lower():
                        result["team2_wins"] += 1
                    else:
                        result["no_result"] += 1
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"_parse_h2h_data error: {e}")
        return result

    async def get_player_vs_team(
        self, player_id: str, team_name: str, format: str
    ) -> dict:
        """
        Fetch player stats against a specific team.
        Returns structured batting/bowling stats dict.
        """
        url = f"{ESPN_BASE}/player/{player_id}/record-vs-teams"

        result: dict = {
            "batting": {
                "avg": 0.0,
                "sr": 0.0,
                "matches": 0,
                "dismissal_patterns": {},
            },
            "bowling": {
                "avg": 0.0,
                "economy": 0.0,
                "wickets": 0,
                "wicket_types": {},
            },
        }

        html = await self.scrape_with_retry(url)
        if not html:
            logger.warning(f"get_player_vs_team: failed to fetch player {player_id} vs {team_name}")
            return result

        try:
            soup = BeautifulSoup(html, "html.parser")
            result = self._parse_player_vs_team(soup, team_name, format, result)
        except Exception as e:
            logger.warning(f"get_player_vs_team parse error: {e}")

        return result

    def _parse_player_vs_team(
        self, soup, team_name: str, format: str, default: dict
    ) -> dict:
        """Parse player vs team stats from BeautifulSoup."""
        result = default.copy()
        try:
            tables = soup.find_all("table", class_=re.compile(r"stat|record|vs", re.I))
            for table in tables:
                try:
                    headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
                    rows = table.find_all("tr")[1:]  # skip header

                    for row in rows:
                        cells = [td.get_text(strip=True) for td in row.find_all("td")]
                        if not cells:
                            continue
                        # Look for the target team in first column
                        if team_name.lower() not in cells[0].lower():
                            continue

                        def safe_float(v: str) -> float:
                            try:
                                return float(v.replace("-", "0") or 0)
                            except ValueError:
                                return 0.0

                        def safe_int(v: str) -> int:
                            try:
                                return int(v.replace("-", "0") or 0)
                            except ValueError:
                                return 0

                        # Try to map columns by header position
                        col_map = {h: i for i, h in enumerate(headers)}

                        if "avg" in col_map and col_map["avg"] < len(cells):
                            result["batting"]["avg"] = safe_float(cells[col_map["avg"]])
                        if "sr" in col_map and col_map["sr"] < len(cells):
                            result["batting"]["sr"] = safe_float(cells[col_map["sr"]])
                        if "mat" in col_map and col_map["mat"] < len(cells):
                            result["batting"]["matches"] = safe_int(cells[col_map["mat"]])
                        if "wkts" in col_map and col_map["wkts"] < len(cells):
                            result["bowling"]["wickets"] = safe_int(cells[col_map["wkts"]])
                        if "econ" in col_map and col_map["econ"] < len(cells):
                            result["bowling"]["economy"] = safe_float(cells[col_map["econ"]])
                        break
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"_parse_player_vs_team error: {e}")
        return result

    # Keep legacy methods for backward compatibility
    async def fetch_player_stats(self, espn_player_id: str) -> Optional[dict]:
        """Legacy method."""
        try:
            resp = await self.client.get(
                f"{ESPN_API_BASE}/athletes/{espn_player_id}/statistics",
                headers={"User-Agent": _next_user_agent()},
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            logger.error(f"ESPN fetch_player_stats({espn_player_id}) failed: {e}")
            return None

    async def fetch_match_data(self, espn_match_id: str) -> Optional[dict]:
        """Legacy method."""
        try:
            resp = await self.client.get(
                f"{ESPN_API_BASE}/summary?event={espn_match_id}",
                headers={"User-Agent": _next_user_agent()},
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            logger.error(f"ESPN fetch_match_data({espn_match_id}) failed: {e}")
            return None

    async def fetch_rankings(self, format: str = "t20i") -> list[dict]:
        """Legacy method."""
        try:
            resp = await self.client.get(
                "https://www.espncricinfo.com/rankings/content/page/211270.html",
                headers={"User-Agent": _next_user_agent()},
            )
            resp.raise_for_status()
            return []
        except httpx.HTTPError as e:
            logger.error(f"ESPN fetch_rankings({format}) failed: {e}")
            return []
