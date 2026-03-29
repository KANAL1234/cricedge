"""
WeatherService — OpenWeatherMap forecast integration for cricket venues.

Caches results in Redis with 3h TTL.
Returns None gracefully when API key is missing or requests fail.
"""
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx
import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

OWM_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"

VENUE_CITY_MAP = {
    "Wankhede Stadium": "Mumbai",
    "M. Chinnaswamy Stadium": "Bengaluru",
    "Eden Gardens": "Kolkata",
    "MA Chidambaram Stadium": "Chennai",
    "Narendra Modi Stadium": "Ahmedabad",
    "Punjab Cricket Association Stadium": "Mohali",
    "Sawai Mansingh Stadium": "Jaipur",
    "Rajiv Gandhi International Cricket Stadium": "Hyderabad",
    "Arun Jaitley Stadium": "Delhi",
    "BRSABV Ekana Cricket Stadium": "Lucknow",
}


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class WeatherForecast:
    city: str
    temperature: float          # Celsius
    humidity: int               # %
    wind_speed: float           # km/h
    precipitation_probability: float  # 0.0 - 1.0
    weather_condition: str
    dew_risk: bool
    rain_risk: bool
    forecast_time: datetime


# ---------------------------------------------------------------------------
# Service class
# ---------------------------------------------------------------------------

class WeatherService:
    def __init__(self):
        self._redis: Optional[aioredis.Redis] = None
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=15)
        return self._client

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        return self._redis

    async def close(self):
        """Clean up HTTP client and Redis connection."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        if self._redis:
            await self._redis.aclose()

    async def get_city_for_venue(self, venue_name: str) -> str:
        """
        Map venue name to city.
        Uses VENUE_CITY_MAP with fuzzy fallback via difflib.
        """
        if venue_name in VENUE_CITY_MAP:
            return VENUE_CITY_MAP[venue_name]

        # Fuzzy match against known venues
        import difflib
        matches = difflib.get_close_matches(
            venue_name, list(VENUE_CITY_MAP.keys()), n=1, cutoff=0.5
        )
        if matches:
            return VENUE_CITY_MAP[matches[0]]

        # Last resort: try to extract city from venue name itself
        # e.g., "Some Stadium, Mumbai" → "Mumbai"
        if "," in venue_name:
            parts = [p.strip() for p in venue_name.split(",")]
            if len(parts) >= 2:
                return parts[-1]

        logger.warning(f"Could not map venue '{venue_name}' to a city, using venue name as city")
        return venue_name

    async def _fetch_forecast(self, city: str) -> Optional[list]:
        """
        Fetch forecast list from OWM API.
        Extracted to a separate method to allow easy mocking in tests.
        """
        if not settings.OPENWEATHER_API_KEY:
            return None

        client = self._get_client()
        try:
            response = await client.get(
                OWM_FORECAST_URL,
                params={
                    "q": f"{city},IN",
                    "appid": settings.OPENWEATHER_API_KEY,
                    "cnt": 40,  # max 5 days of 3h slots
                },
            )
            response.raise_for_status()
            data = response.json()
            return data.get("list", [])
        except httpx.HTTPError as e:
            logger.warning(f"WeatherService OWM request failed for {city}: {e}")
            return None
        except Exception as e:
            logger.warning(f"WeatherService unexpected error for {city}: {e}")
            return None

    async def get_match_weather(
        self, venue_city: str, match_datetime: datetime
    ) -> Optional[WeatherForecast]:
        """
        Get weather forecast for a venue at the given match time.

        - Resolves city from venue name using VENUE_CITY_MAP + fuzzy fallback
        - Finds OWM forecast slot closest to match_datetime
        - Computes dew_risk and rain_risk
        - Caches result in Redis for 3h
        - Returns None if API key is missing or request fails
        """
        if not settings.OPENWEATHER_API_KEY:
            logger.warning(
                "WeatherService: OPENWEATHER_API_KEY is not set — returning None"
            )
            return None

        # Resolve city
        city = await self.get_city_for_venue(venue_city)

        # Normalise match_datetime to UTC-aware
        if match_datetime.tzinfo is None:
            match_datetime = match_datetime.replace(tzinfo=timezone.utc)

        date_str = match_datetime.strftime("%Y-%m-%d")
        cache_key = f"weather:{city.lower().replace(' ', '_')}:{date_str}"

        # Check Redis cache
        try:
            r = await self._get_redis()
            cached = await r.get(cache_key)
            if cached:
                logger.debug(f"Weather cache hit for {city} on {date_str}")
                raw = json.loads(cached)
                return WeatherForecast(
                    city=raw["city"],
                    temperature=raw["temperature"],
                    humidity=raw["humidity"],
                    wind_speed=raw["wind_speed"],
                    precipitation_probability=raw["precipitation_probability"],
                    weather_condition=raw["weather_condition"],
                    dew_risk=raw["dew_risk"],
                    rain_risk=raw["rain_risk"],
                    forecast_time=datetime.fromisoformat(raw["forecast_time"]),
                )
        except Exception as e:
            logger.warning(f"Redis cache read failed for weather {city}: {e}")

        # Fetch from OWM
        forecast_list = await self._fetch_forecast(city)
        if not forecast_list:
            return None

        # Find forecast slot closest to match_datetime
        best_slot = None
        best_diff = float("inf")
        match_ts = match_datetime.timestamp()

        for slot in forecast_list:
            try:
                slot_ts = float(slot["dt"])
                diff = abs(slot_ts - match_ts)
                if diff < best_diff:
                    best_diff = diff
                    best_slot = slot
            except Exception:
                continue

        if not best_slot:
            logger.warning(f"No suitable forecast slot found for {city} at {match_datetime}")
            return None

        try:
            # Temperature: Kelvin → Celsius
            temp_kelvin = best_slot["main"]["temp"]
            temperature = round(temp_kelvin - 273.15, 1)

            humidity = int(best_slot["main"].get("humidity", 0))

            # Wind: m/s → km/h
            wind_ms = float(best_slot.get("wind", {}).get("speed", 0))
            wind_kmh = round(wind_ms * 3.6, 1)

            # Precipitation probability (OWM 'pop' field, 0.0-1.0)
            pop = float(best_slot.get("pop", 0.0))

            # Weather condition description
            weather_condition = ""
            weather_list = best_slot.get("weather", [])
            if weather_list:
                weather_condition = weather_list[0].get("description", "")

            # Forecast time
            forecast_time = datetime.fromtimestamp(best_slot["dt"], tz=timezone.utc)

            # Computed risk flags
            dew_risk = humidity > 70 and match_datetime.hour >= 18
            rain_risk = pop > 0.3

            forecast = WeatherForecast(
                city=city,
                temperature=temperature,
                humidity=humidity,
                wind_speed=wind_kmh,
                precipitation_probability=pop,
                weather_condition=weather_condition,
                dew_risk=dew_risk,
                rain_risk=rain_risk,
                forecast_time=forecast_time,
            )

            # Cache in Redis for 3 hours
            try:
                cache_data = {
                    "city": forecast.city,
                    "temperature": forecast.temperature,
                    "humidity": forecast.humidity,
                    "wind_speed": forecast.wind_speed,
                    "precipitation_probability": forecast.precipitation_probability,
                    "weather_condition": forecast.weather_condition,
                    "dew_risk": forecast.dew_risk,
                    "rain_risk": forecast.rain_risk,
                    "forecast_time": forecast.forecast_time.isoformat(),
                }
                r = await self._get_redis()
                await r.setex(cache_key, 10800, json.dumps(cache_data))  # 3h TTL
            except Exception as cache_err:
                logger.warning(f"Redis cache write failed for weather {city}: {cache_err}")

            return forecast

        except Exception as e:
            logger.warning(f"WeatherService parse error for slot data: {e}")
            return None
