"""
CricbuzzClient — single point of entry for ALL Cricbuzz RapidAPI calls.

Actual endpoints confirmed via live testing (versioned paths):
  series/v1/{seriesId}              — schedule
  series/v1/{seriesId}/squads       — squad list
  series/v1/{seriesId}/squads/{id}  — squad players
  stats/v1/player/{id}              — player info
  stats/v1/player/{id}/batting      — batting stats
  stats/v1/player/{id}/bowling      — bowling stats
  stats/v1/venue/{id}               — venue stats

Every method:
1. Checks Redis cache first — returns cached if exists
2. Only calls API on cache miss
3. Stores result in Redis with TTL
4. Increments prometheus counter
5. Logs endpoint + cache hit/miss
6. Logs to api_call_log table (async, best-effort)
"""
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx
import redis.asyncio as aioredis

from app.core.config import settings
from app.core.metrics import cricbuzz_api_calls_total

logger = logging.getLogger(__name__)

# IPL 2026 squad IDs (seriesId: 9241)
IPL_2026_SQUADS: dict[str, dict] = {
    "Chennai Super Kings":          {"teamId": 58,  "squadId": 99705},
    "Delhi Capitals":               {"teamId": 61,  "squadId": 99716},
    "Gujarat Titans":               {"teamId": 971, "squadId": 99727},
    "Royal Challengers Bengaluru":  {"teamId": 59,  "squadId": 99738},
    "Punjab Kings":                 {"teamId": 65,  "squadId": 99749},
    "Kolkata Knight Riders":        {"teamId": 63,  "squadId": 99760},
    "Sunrisers Hyderabad":          {"teamId": 255, "squadId": 99771},
    "Rajasthan Royals":             {"teamId": 64,  "squadId": 99782},
    "Lucknow Super Giants":         {"teamId": 966, "squadId": 99793},
    "Mumbai Indians":               {"teamId": 62,  "squadId": 99804},
}

ALL_SQUAD_IDS = [v["squadId"] for v in IPL_2026_SQUADS.values()]


def _midnight_ist_seconds() -> int:
    now_utc = datetime.now(timezone.utc)
    ist_offset = timedelta(hours=5, minutes=30)
    now_ist = now_utc + ist_offset
    midnight_ist = (now_ist + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(int((midnight_ist - now_ist).total_seconds()), 60)


def _end_of_month_seconds() -> int:
    now_utc = datetime.now(timezone.utc)
    ist_offset = timedelta(hours=5, minutes=30)
    now_ist = now_utc + ist_offset
    if now_ist.month == 12:
        next_month = now_ist.replace(year=now_ist.year + 1, month=1, day=1,
                                     hour=0, minute=0, second=0, microsecond=0)
    else:
        next_month = now_ist.replace(month=now_ist.month + 1, day=1,
                                     hour=0, minute=0, second=0, microsecond=0)
    return max(int((next_month - now_ist).total_seconds()), 60)


class CricbuzzClient:
    BASE_URL = "https://cricbuzz-cricket.p.rapidapi.com"

    def __init__(self):
        self._redis: aioredis.Redis | None = None

    @property
    def _headers(self) -> dict:
        return {
            "x-rapidapi-host": settings.RAPIDAPI_HOST,
            "x-rapidapi-key": settings.RAPIDAPI_KEY,
        }

    def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        return self._redis

    async def _get_cache(self, key: str) -> Any | None:
        try:
            raw = await self._get_redis().get(key)
            if raw:
                return json.loads(raw)
        except Exception as e:
            logger.warning(f"Redis read failed for {key}: {e}")
        return None

    async def _set_cache(self, key: str, data: Any, ttl: int) -> None:
        try:
            await self._get_redis().setex(key, ttl, json.dumps(data))
        except Exception as e:
            logger.warning(f"Redis write failed for {key}: {e}")

    async def _increment_usage(self, endpoint: str) -> None:
        try:
            r = self._get_redis()
            daily_key = "cricbuzz:usage:daily"
            monthly_key = "cricbuzz:usage:monthly"
            await r.incr(daily_key)
            await r.expire(daily_key, _midnight_ist_seconds())
            await r.incr(monthly_key)
            await r.expire(monthly_key, _end_of_month_seconds())
            ep_key = f"cricbuzz:usage:endpoint:{endpoint.replace('/', ':')}"
            await r.incr(ep_key)
            await r.expire(ep_key, _midnight_ist_seconds())
        except Exception as e:
            logger.warning(f"Redis usage increment failed: {e}")

    async def _log_api_call(self, endpoint: str, params: dict,
                             cache_hit: bool, response_code: int) -> None:
        try:
            from app.core.database import AsyncSessionLocal
            from app.models.api_call_log import ApiCallLog
            async with AsyncSessionLocal() as db:
                log = ApiCallLog(
                    endpoint=endpoint,
                    params=params,
                    cache_hit=cache_hit,
                    response_code=response_code,
                    called_at=datetime.now(timezone.utc),
                    month_year=datetime.now(timezone.utc).strftime("%Y-%m"),
                )
                db.add(log)
                await db.commit()
        except Exception as e:
            logger.debug(f"api_call_log write failed (non-critical): {e}")

    async def _fetch(self, path: str) -> Any:
        """Make a real API call. Path is appended directly to BASE_URL."""
        url = f"{self.BASE_URL}/{path}"
        endpoint_label = path

        cricbuzz_api_calls_total.labels(endpoint=endpoint_label).inc()
        await self._increment_usage(endpoint_label)

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, headers=self._headers)
            response.raise_for_status()
            data = response.json()

        await self._log_api_call(endpoint_label, {}, False, response.status_code)
        logger.info(f"[cricbuzz] API CALL  {endpoint_label}")
        return data

    async def _cached_fetch(self, path: str, cache_key: str, ttl: int) -> Any:
        """Cache-first fetch."""
        cached = await self._get_cache(cache_key)
        if cached is not None:
            logger.debug(f"[cricbuzz] CACHE HIT {path} key={cache_key}")
            await self._log_api_call(path, {}, True, 200)
            return cached

        data = await self._fetch(path)
        await self._set_cache(cache_key, data, ttl)
        return data

    # -----------------------------------------------------------------------
    # Public API methods — confirmed working endpoints
    # -----------------------------------------------------------------------

    async def get_ipl_schedule(self) -> Any:
        """series/v1/{seriesId} — full IPL 2026 fixture list. TTL 6h."""
        return await self._cached_fetch(
            f"series/v1/{settings.IPL_2026_SERIES_ID}",
            cache_key="cricbuzz:ipl:schedule",
            ttl=6 * 3600,
        )

    async def get_ipl_squads(self) -> Any:
        """series/v1/{seriesId}/squads — all 10 squad IDs. TTL 24h."""
        return await self._cached_fetch(
            f"series/v1/{settings.IPL_2026_SERIES_ID}/squads",
            cache_key="cricbuzz:ipl:squads",
            ttl=24 * 3600,
        )

    async def get_team_players(self, squad_id: int) -> Any:
        """series/v1/{seriesId}/squads/{squadId} — full player list. TTL 24h."""
        return await self._cached_fetch(
            f"series/v1/{settings.IPL_2026_SERIES_ID}/squads/{squad_id}",
            cache_key=f"cricbuzz:squad:{squad_id}:players",
            ttl=24 * 3600,
        )

    async def get_player_info(self, player_id: int) -> Any:
        """stats/v1/player/{playerId} — full player profile. TTL 7d."""
        return await self._cached_fetch(
            f"stats/v1/player/{player_id}",
            cache_key=f"cricbuzz:player:{player_id}:info",
            ttl=7 * 24 * 3600,
        )

    async def get_player_batting(self, player_id: int) -> Any:
        """stats/v1/player/{playerId}/batting — batting stats by format. TTL 12h."""
        return await self._cached_fetch(
            f"stats/v1/player/{player_id}/batting",
            cache_key=f"cricbuzz:player:{player_id}:batting",
            ttl=12 * 3600,
        )

    async def get_player_bowling(self, player_id: int) -> Any:
        """stats/v1/player/{playerId}/bowling — bowling stats by format. TTL 12h."""
        return await self._cached_fetch(
            f"stats/v1/player/{player_id}/bowling",
            cache_key=f"cricbuzz:player:{player_id}:bowling",
            ttl=12 * 3600,
        )

    async def get_venue_stats(self, venue_id: int) -> Any:
        """stats/v1/venue/{venueId} — venue stats. TTL 24h."""
        return await self._cached_fetch(
            f"stats/v1/venue/{venue_id}",
            cache_key=f"cricbuzz:venue:{venue_id}:stats",
            ttl=24 * 3600,
        )

    # Kept for compatibility — delegates to get_venue_stats
    async def get_venue_info(self, venue_id: int) -> Any:
        return await self._get_cache(f"cricbuzz:venue:{venue_id}:info") or {}

    async def get_match_scorecard(self, match_id: int) -> Any:
        """mcenter/v1/{matchId}/hscard — full scorecard with batsmen+bowlers. TTL 24h."""
        return await self._cached_fetch(
            f"mcenter/v1/{match_id}/hscard",
            cache_key=f"cricbuzz:match:{match_id}:scorecard",
            ttl=24 * 3600,
        )

    async def get_recent_matches(self) -> Any:
        """matches/v1/recent — live + completed matches with scores. TTL 30min."""
        return await self._cached_fetch(
            "matches/v1/recent",
            cache_key="cricbuzz:matches:recent",
            ttl=30 * 60,
        )

    # get_match_squads — playing XI from in-progress matches (no static endpoint)
    async def get_match_squads(self, match_id: int) -> Any:
        cache_key = f"cricbuzz:match:{match_id}:squads"
        cached = await self._get_cache(cache_key)
        if cached is not None:
            return cached
        # No static playing XI endpoint on this plan — return empty
        # Real XI updates come via score endpoints during live match window
        return {}

    async def get_player_career(self, player_id: int) -> Any:
        """Alias for get_player_batting (career stats are embedded there)."""
        return await self._cached_fetch(
            f"stats/v1/player/{player_id}/batting",
            cache_key=f"cricbuzz:player:{player_id}:career",
            ttl=12 * 3600,
        )

    # -----------------------------------------------------------------------
    # Budget tracking
    # -----------------------------------------------------------------------

    async def get_api_budget_status(self) -> dict:
        try:
            r = self._get_redis()
            calls_today = int(await r.get("cricbuzz:usage:daily") or 0)
            calls_month = int(await r.get("cricbuzz:usage:monthly") or 0)
        except Exception:
            calls_today = 0
            calls_month = 0

        limit = settings.CRICBUZZ_MONTHLY_LIMIT
        remaining = max(limit - calls_month, 0)

        if calls_month < 100:
            health = "green"
        elif calls_month <= 160:
            health = "amber"
        else:
            health = "red"

        return {
            "calls_today": calls_today,
            "calls_this_month": calls_month,
            "monthly_limit": limit,
            "remaining": remaining,
            "budget_health": health,
        }

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()
            self._redis = None


_client: CricbuzzClient | None = None


def get_client() -> CricbuzzClient:
    global _client
    if _client is None:
        _client = CricbuzzClient()
    return _client
