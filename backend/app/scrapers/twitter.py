"""
TwitterMonitor — monitors IPL team accounts for playing XI announcements.

Extends the existing TwitterScraper structure with XI parsing and fuzzy
player name matching against a known player roster.
"""
import difflib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

TWITTER_API_BASE = "https://api.twitter.com/2"

IPL_TEAM_ACCOUNTS = [
    "mipaltan",
    "ChennaiIPL",
    "RCBTweets",
    "KKRiders",
    "rajasthanroyals",
    "SunRisersHyd",
    "DelhiCapitals",
    "PunjabKingsIPL",
    "LucknowIPL",
    "gujarat_titans",
    "IPL",
    "BCCI",
]

XI_KEYWORDS = [
    "Playing XI",
    "Playing 11",
    "Final XI",
    "#PlayingXI",
    "Playing Eleven",
]

KNOWN_IPL_PLAYERS = [
    "Rohit Sharma", "Virat Kohli", "MS Dhoni", "Hardik Pandya", "Jasprit Bumrah",
    "KL Rahul", "Shubman Gill", "Rishabh Pant", "Ravindra Jadeja", "Mohammed Shami",
    "Ishan Kishan", "Suryakumar Yadav", "Yashasvi Jaiswal", "Shreyas Iyer",
    "Ruturaj Gaikwad", "Devon Conway", "Faf du Plessis", "Glenn Maxwell",
    "David Warner", "Jos Buttler", "Sanju Samson", "Yuzvendra Chahal",
    "Rashid Khan", "Mohammed Siraj", "Trent Boult", "Pat Cummins",
    "Mitchell Starc", "Marcus Stoinis", "Nicholas Pooran", "Andre Russell",
    "Sunil Narine", "Tim David", "Liam Livingstone", "Sam Curran",
    "Axar Patel", "Washington Sundar", "Deepak Chahar", "Bhuvneshwar Kumar",
    "Ravichandran Ashwin", "Kuldeep Yadav", "Arshdeep Singh", "Harshal Patel",
    "Prasidh Krishna", "Umran Malik", "Tilak Varma", "Rinku Singh",
    "Shimron Hetmyer", "Prabhsimran Singh", "Abhishek Sharma", "Shivam Dube",
]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class XIAnnouncement:
    account: str
    tweet_id: str
    tweet_text: str
    players: list
    created_at: datetime


@dataclass
class ParsedPlayer:
    raw_name: str
    matched_name: Optional[str]
    confidence: float


# ---------------------------------------------------------------------------
# TwitterScraper base (preserved for backward compatibility)
# ---------------------------------------------------------------------------

class TwitterScraper:
    """Monitors cricket journalist accounts for playing XI leaks and injury news."""

    WATCH_ACCOUNTS = [
        "cricbuzz",
        "ESPNcricinfo",
        "ICC",
        "BCCI",
    ]

    PLAYING_XI_KEYWORDS = [
        "playing xi", "playing 11", "playing eleven",
        "team announced", "confirmed squad", "lineup",
    ]

    def __init__(self):
        self.client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {settings.TWITTER_BEARER_TOKEN}"},
            timeout=30,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.client.aclose()

    async def search_playing_xi_tweets(self, team_names: list[str]) -> list[dict]:
        """Search recent tweets for playing XI announcements."""
        query_parts = [f'"{kw}"' for kw in self.PLAYING_XI_KEYWORDS[:3]]
        team_part = " OR ".join([f'"{t}"' for t in team_names])
        query = f"({' OR '.join(query_parts)}) ({team_part}) -is:retweet lang:en"

        try:
            resp = await self.client.get(
                f"{TWITTER_API_BASE}/tweets/search/recent",
                params={
                    "query": query,
                    "max_results": 20,
                    "tweet.fields": "created_at,author_id,text",
                    "expansions": "author_id",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", [])
        except httpx.HTTPError as e:
            logger.error(f"Twitter search failed: {e}")
            return []

    async def get_user_timeline(self, username: str, max_results: int = 10) -> list[dict]:
        """Fetch recent tweets from a specific account."""
        try:
            # First resolve username to user ID
            user_resp = await self.client.get(
                f"{TWITTER_API_BASE}/users/by/username/{username}",
                params={"user.fields": "id"},
            )
            user_resp.raise_for_status()
            user_id = user_resp.json()["data"]["id"]

            timeline_resp = await self.client.get(
                f"{TWITTER_API_BASE}/users/{user_id}/tweets",
                params={"max_results": max_results, "tweet.fields": "created_at,text"},
            )
            timeline_resp.raise_for_status()
            return timeline_resp.json().get("data", [])
        except httpx.HTTPError as e:
            logger.error(f"Twitter get_user_timeline({username}) failed: {e}")
            return []


# ---------------------------------------------------------------------------
# TwitterMonitor — XI-focused monitor
# ---------------------------------------------------------------------------

class TwitterMonitor(TwitterScraper):
    """
    Extended scraper focused on IPL Playing XI announcements.
    Monitors IPL_TEAM_ACCOUNTS for XI keyword tweets and parses player lists.
    """

    def __init__(self):
        super().__init__()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.client.aclose()

    async def monitor_xi_accounts(self) -> list:
        """
        Monitor all IPL_TEAM_ACCOUNTS for Playing XI tweets.
        Returns list[XIAnnouncement].
        """
        announcements = []

        for account in IPL_TEAM_ACCOUNTS:
            try:
                tweets = await self.get_user_timeline(account, max_results=10)
                for tweet in tweets:
                    try:
                        tweet_text = tweet.get("text", "")
                        # Filter tweets containing any XI keyword (case-insensitive)
                        if not self._is_xi_tweet(tweet_text):
                            continue

                        players = self.parse_xi_from_tweet(tweet_text)

                        # Parse created_at
                        created_at_str = tweet.get("created_at", "")
                        try:
                            created_at = datetime.fromisoformat(
                                created_at_str.replace("Z", "+00:00")
                            )
                        except Exception:
                            created_at = datetime.now()

                        announcement = XIAnnouncement(
                            account=account,
                            tweet_id=tweet.get("id", ""),
                            tweet_text=tweet_text,
                            players=players,
                            created_at=created_at,
                        )
                        announcements.append(announcement)

                    except Exception as e:
                        logger.warning(f"Failed to process tweet from {account}: {e}")
                        continue

            except Exception as e:
                logger.warning(f"monitor_xi_accounts: failed for account {account}: {e}")
                continue

        logger.info(
            f"monitor_xi_accounts: scanned {len(IPL_TEAM_ACCOUNTS)} accounts, "
            f"found {len(announcements)} XI announcements"
        )
        return announcements

    def _is_xi_tweet(self, tweet_text: str) -> bool:
        """Check if tweet contains any XI keyword (case-insensitive)."""
        text_lower = tweet_text.lower()
        for keyword in XI_KEYWORDS:
            if keyword.lower() in text_lower:
                return True
        return False

    def parse_xi_from_tweet(self, tweet_text: str) -> list:
        """
        Parse player names from a tweet text.

        Handles 3 formats:
          1. Numbered list:  "1. Player Name" or "1) Player Name"
          2. Bullet list:    "• Player Name" or "- Player Name" or "* Player Name"
          3. Comma-separated: "P1, P2, P3, ..."

        Uses fuzzy matching against KNOWN_IPL_PLAYERS.
        Returns list[ParsedPlayer].
        """
        raw_names = []

        # Strategy 1: numbered list (multiline)
        numbered_matches = re.findall(
            r"^\d+[.)]\s*([A-Za-z][A-Za-z\s]{2,25})",
            tweet_text,
            re.MULTILINE,
        )
        if numbered_matches:
            raw_names.extend(numbered_matches)

        # Strategy 2: bullet list (multiline) — handles •, -, *, and emoji-prefixed lines
        if not raw_names:
            bullet_matches = re.findall(
                r"^[•\-\*]\s*([A-Za-z][A-Za-z\s]{2,25})",
                tweet_text,
                re.MULTILINE,
            )
            if bullet_matches:
                raw_names.extend(bullet_matches)

        # Strategy 3: comma-separated (look for lines with 3+ comma-separated tokens)
        if not raw_names:
            for line in tweet_text.splitlines():
                parts = [p.strip() for p in line.split(",")]
                # A valid XI line has 3+ parts that look like names
                name_like = [
                    p for p in parts
                    if p and re.match(r"^[A-Za-z][A-Za-z\s]{2,30}$", p)
                ]
                if len(name_like) >= 3:
                    raw_names.extend(name_like)
                    break

            # Also try splitting full tweet text on commas if nothing found yet
            if not raw_names and "," in tweet_text:
                parts = [p.strip() for p in tweet_text.split(",")]
                name_like = [
                    p for p in parts
                    if p and re.match(r"^[A-Za-z][A-Za-z\s]{2,30}$", p)
                ]
                if len(name_like) >= 3:
                    raw_names.extend(name_like)

        # Deduplicate while preserving order
        seen = set()
        deduped = []
        for name in raw_names:
            cleaned = name.strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                deduped.append(cleaned)

        # Fuzzy match each raw name against KNOWN_IPL_PLAYERS
        parsed_players = []
        for raw_name in deduped:
            cleaned = raw_name.strip()
            if not cleaned or len(cleaned) < 3:
                continue
            parsed = self._fuzzy_match_player(cleaned)
            parsed_players.append(parsed)

        return parsed_players

    def _fuzzy_match_player(self, raw_name: str) -> ParsedPlayer:
        """
        Match a raw name against KNOWN_IPL_PLAYERS using difflib.
        Returns ParsedPlayer with confidence score.
        """
        # Exact match first
        for known in KNOWN_IPL_PLAYERS:
            if raw_name.lower() == known.lower():
                return ParsedPlayer(
                    raw_name=raw_name,
                    matched_name=known,
                    confidence=1.0,
                )

        # Close match via difflib
        close_matches = difflib.get_close_matches(
            raw_name,
            KNOWN_IPL_PLAYERS,
            n=1,
            cutoff=0.6,
        )

        if close_matches:
            matched = close_matches[0]
            ratio = difflib.SequenceMatcher(
                None, raw_name.lower(), matched.lower()
            ).ratio()
            return ParsedPlayer(
                raw_name=raw_name,
                matched_name=matched,
                confidence=round(ratio, 3),
            )

        # No match found
        return ParsedPlayer(
            raw_name=raw_name,
            matched_name=None,
            confidence=0.0,
        )
