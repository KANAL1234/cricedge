"""
Tests for CricbuzzClient, DataSyncService, budget protection, and bootstrap.

Covers:
1. CricbuzzClient cache behaviour (cache hit vs miss, TTLs, call counter)
2. DataSyncService deduplication (schedule, player stats, playing XI)
3. Budget protection (health thresholds, emergency_mode)
4. Bootstrap script --dry-run
"""
import asyncio
import json
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_redis(data: dict | None = None):
    """Return a mock Redis client with controlled get/set/expire/incr."""
    r = AsyncMock()
    store = dict(data or {})

    async def get(key):
        val = store.get(key)
        if val is None:
            return None
        # Return JSON string for cache values, plain string for counters
        if isinstance(val, (dict, list)):
            return json.dumps(val)
        return str(val)

    async def setex(key, ttl, value):
        store[key] = value

    async def incr(key):
        store[key] = int(store.get(key, 0)) + 1
        return store[key]

    async def expire(key, ttl):
        pass

    async def delete(*keys):
        for k in keys:
            store.pop(k, None)

    async def set(key, value):
        store[key] = value

    r.get = get
    r.setex = setex
    r.incr = incr
    r.expire = expire
    r.delete = delete
    r.set = set
    r.aclose = AsyncMock()
    r._store = store
    return r


def _make_httpx_response(payload: dict, status: int = 200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# 1. CricbuzzClient cache behaviour
# ---------------------------------------------------------------------------

class TestCricbuzzClientCacheBehaviour:
    """First call hits API, second call returns cache."""

    @pytest.mark.asyncio
    async def test_first_call_hits_api_second_returns_cache(self):
        from app.services.cricbuzz_client import CricbuzzClient

        fake_schedule = {"matchList": [{"matchId": "1001", "team1": {}, "team2": {}, "venue": {}}]}
        redis = _make_redis()
        call_count = 0

        async def fake_get(url, headers, params):
            nonlocal call_count
            call_count += 1
            return _make_httpx_response(fake_schedule)

        client = CricbuzzClient()
        client._redis = redis

        with patch("httpx.AsyncClient") as mock_httpx, \
             patch("app.services.cricbuzz_client.cricbuzz_api_calls_total") as mock_counter, \
             patch.object(client, "_log_api_call", new=AsyncMock()):
            mock_counter.labels.return_value.inc = MagicMock()
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=None)
            mock_ctx.get = fake_get
            mock_httpx.return_value = mock_ctx

            # First call — should hit API
            result1 = await client.get_ipl_schedule()
            assert call_count == 1
            assert result1 == fake_schedule

            # Second call — should hit cache
            result2 = await client.get_ipl_schedule()
            assert call_count == 1  # no new API call
            assert result2 == fake_schedule

    @pytest.mark.asyncio
    async def test_ttl_set_on_cache_write(self):
        from app.services.cricbuzz_client import CricbuzzClient

        redis = _make_redis()
        set_calls: list[tuple] = []

        original_setex = redis.setex

        async def spy_setex(key, ttl, value):
            set_calls.append((key, ttl))
            return await original_setex(key, ttl, value)

        redis.setex = spy_setex
        client = CricbuzzClient()
        client._redis = redis

        with patch("httpx.AsyncClient") as mock_httpx, \
             patch("app.services.cricbuzz_client.cricbuzz_api_calls_total") as mock_counter, \
             patch.object(client, "_log_api_call", new=AsyncMock()):
            mock_counter.labels.return_value.inc = MagicMock()
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=None)
            mock_ctx.get = AsyncMock(return_value=_make_httpx_response({"data": "ok"}))
            mock_httpx.return_value = mock_ctx

            # Schedule TTL = 6 hours
            await client.get_ipl_schedule()
            schedule_call = next((c for c in set_calls if "schedule" in c[0]), None)
            assert schedule_call is not None
            assert schedule_call[1] == 6 * 3600

            # Player info TTL = 7 days
            set_calls.clear()
            await client.get_player_info(12345)
            info_call = next((c for c in set_calls if "info" in c[0]), None)
            assert info_call is not None
            assert info_call[1] == 7 * 24 * 3600

    @pytest.mark.asyncio
    async def test_api_counter_increments_on_miss_not_hit(self):
        from app.services.cricbuzz_client import CricbuzzClient

        redis = _make_redis()
        client = CricbuzzClient()
        client._redis = redis

        increment_count = 0

        with patch("httpx.AsyncClient") as mock_httpx, \
             patch("app.services.cricbuzz_client.cricbuzz_api_calls_total") as mock_counter, \
             patch.object(client, "_log_api_call", new=AsyncMock()):

            def count_inc(*args, **kwargs):
                nonlocal increment_count
                increment_count += 1

            mock_counter.labels.return_value.inc = count_inc
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=None)
            mock_ctx.get = AsyncMock(return_value=_make_httpx_response({"players": []}))
            mock_httpx.return_value = mock_ctx

            # First call — counter should increment
            await client.get_team_players(99705)
            assert increment_count == 1

            # Second call — same key, cache hit, counter should NOT increment again
            await client.get_team_players(99705)
            assert increment_count == 1


# ---------------------------------------------------------------------------
# 2. DataSyncService deduplication
# ---------------------------------------------------------------------------

class TestDataSyncDeduplication:

    @pytest.mark.asyncio
    async def test_sync_ipl_schedule_skips_within_6_hours(self):
        """sync_ipl_schedule called twice — second call skips API."""
        from app.services.data_sync import DataSyncService
        from app.services.cricbuzz_client import CricbuzzClient

        db = AsyncMock()
        client = AsyncMock(spec=CricbuzzClient)
        client.get_ipl_schedule = AsyncMock(return_value={"matchList": []})

        redis = _make_redis({"cricbuzz:sync:schedule:last_run": "1"})
        svc = DataSyncService(db, client)
        svc._redis = redis

        result = await svc.sync_ipl_schedule()

        assert result.get("skipped") is True
        client.get_ipl_schedule.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_player_stats_skips_if_fresh(self):
        """sync_player_stats skips if stats_last_synced < 12 hours ago."""
        from app.services.data_sync import DataSyncService
        from app.services.cricbuzz_client import CricbuzzClient
        from app.models.player import Player

        fresh_time = datetime.now(timezone.utc) - timedelta(hours=6)

        mock_player = MagicMock(spec=Player)
        mock_player.cricbuzz_id = "42"
        mock_player.id = uuid.uuid4()
        mock_player.stats_last_synced = fresh_time

        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_player)))

        client = AsyncMock(spec=CricbuzzClient)

        svc = DataSyncService(db, client)

        result = await svc.sync_player_stats(42, force=False)

        assert result.get("skipped") is True
        assert result.get("reason") == "fresh"
        client.get_player_batting.assert_not_called()
        client.get_player_bowling.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_player_stats_calls_api_if_stale(self):
        """sync_player_stats calls API when stats are older than 12 hours."""
        from app.services.data_sync import DataSyncService
        from app.services.cricbuzz_client import CricbuzzClient
        from app.models.player import Player

        stale_time = datetime.now(timezone.utc) - timedelta(hours=24)

        mock_player = MagicMock(spec=Player)
        mock_player.cricbuzz_id = "99"
        mock_player.id = uuid.uuid4()
        mock_player.stats_last_synced = stale_time

        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_player)))
        db.commit = AsyncMock()

        client = AsyncMock(spec=CricbuzzClient)
        client.get_player_batting = AsyncMock(return_value={"stats": []})
        client.get_player_bowling = AsyncMock(return_value={"stats": []})

        svc = DataSyncService(db, client)

        with patch.object(svc, "_upsert_format_stats", new=AsyncMock()):
            result = await svc.sync_player_stats(99, force=False)

        assert result.get("skipped") is not True
        client.get_player_batting.assert_called_once_with(99)
        client.get_player_bowling.assert_called_once_with(99)

    @pytest.mark.asyncio
    async def test_sync_match_xi_skips_if_already_confirmed(self):
        """sync_match_playing_xi returns immediately if xi_confirmed_at is set."""
        from app.services.data_sync import DataSyncService
        from app.services.cricbuzz_client import CricbuzzClient
        from app.models.match import Match

        mock_match = MagicMock(spec=Match)
        mock_match.cricbuzz_id = "5001"
        mock_match.xi_confirmed_at = datetime.now(timezone.utc)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_match)))

        client = AsyncMock(spec=CricbuzzClient)
        svc = DataSyncService(db, client)

        result = await svc.sync_match_playing_xi(5001)

        assert result.get("skipped") is True
        assert result.get("reason") == "already_confirmed"
        client.get_match_squads.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_match_xi_skips_when_too_early(self):
        """sync_match_playing_xi skips if match is > 4 hours away."""
        from app.services.data_sync import DataSyncService
        from app.services.cricbuzz_client import CricbuzzClient
        from app.models.match import Match

        far_future = datetime.now(timezone.utc) + timedelta(hours=8)

        mock_match = MagicMock(spec=Match)
        mock_match.cricbuzz_id = "5002"
        mock_match.xi_confirmed_at = None
        mock_match.match_start_utc = far_future

        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_match)))

        client = AsyncMock(spec=CricbuzzClient)
        svc = DataSyncService(db, client)

        result = await svc.sync_match_playing_xi(5002)

        assert result.get("skipped") is True
        assert result.get("reason") == "too_early"
        client.get_match_squads.assert_not_called()


# ---------------------------------------------------------------------------
# 3. Budget protection
# ---------------------------------------------------------------------------

class TestBudgetProtection:

    @pytest.mark.asyncio
    async def test_budget_health_green_below_100(self):
        from app.services.cricbuzz_client import CricbuzzClient

        redis = _make_redis({"cricbuzz:usage:daily": "4", "cricbuzz:usage:monthly": "27"})
        client = CricbuzzClient()
        client._redis = redis

        with patch("app.services.cricbuzz_client.settings") as mock_settings:
            mock_settings.CRICBUZZ_MONTHLY_LIMIT = 200
            mock_settings.REDIS_URL = "redis://localhost:6379/0"
            status = await client.get_api_budget_status()

        assert status["budget_health"] == "green"
        assert status["calls_this_month"] == 27
        assert status["remaining"] == 173

    @pytest.mark.asyncio
    async def test_budget_health_amber_100_to_160(self):
        from app.services.cricbuzz_client import CricbuzzClient

        redis = _make_redis({"cricbuzz:usage:daily": "10", "cricbuzz:usage:monthly": "130"})
        client = CricbuzzClient()
        client._redis = redis

        with patch("app.services.cricbuzz_client.settings") as mock_settings:
            mock_settings.CRICBUZZ_MONTHLY_LIMIT = 200
            mock_settings.REDIS_URL = "redis://localhost:6379/0"
            status = await client.get_api_budget_status()

        assert status["budget_health"] == "amber"

    @pytest.mark.asyncio
    async def test_budget_health_red_above_160(self):
        from app.services.cricbuzz_client import CricbuzzClient

        redis = _make_redis({"cricbuzz:usage:daily": "20", "cricbuzz:usage:monthly": "165"})
        client = CricbuzzClient()
        client._redis = redis

        with patch("app.services.cricbuzz_client.settings") as mock_settings:
            mock_settings.CRICBUZZ_MONTHLY_LIMIT = 200
            mock_settings.REDIS_URL = "redis://localhost:6379/0"
            status = await client.get_api_budget_status()

        assert status["budget_health"] == "red"
        assert status["remaining"] == 35

    @pytest.mark.asyncio
    async def test_emergency_mode_disables_batch_sync(self):
        """budget_check_task sets emergency_mode Redis flag when red."""
        mock_redis = _make_redis()

        # Patch redis.asyncio.from_url wherever it is called inside _budget_check
        with patch("redis.asyncio.from_url", return_value=mock_redis):
            with patch("app.services.cricbuzz_client.CricbuzzClient") as MockClient:
                mock_client = AsyncMock()
                mock_client.get_api_budget_status = AsyncMock(return_value={
                    "calls_today": 20,
                    "calls_this_month": 170,
                    "monthly_limit": 200,
                    "remaining": 30,
                    "budget_health": "red",
                })
                mock_client.close = AsyncMock()
                MockClient.return_value = mock_client

                from app.tasks import scrape_tasks
                result = await scrape_tasks._budget_check()

        assert result["budget_health"] == "red"
        assert mock_redis._store.get("cricbuzz:budget:emergency_mode") in ("1", 1, True, "true")


# ---------------------------------------------------------------------------
# 4. Bootstrap script --dry-run
# ---------------------------------------------------------------------------

class TestBootstrapDryRun:

    def test_dry_run_prints_27_planned_calls(self, capsys):
        """--dry-run shows 27 planned calls without making any API calls."""
        from scripts.bootstrap_cricbuzz_data import bootstrap

        with patch("app.services.cricbuzz_client.CricbuzzClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.close = AsyncMock()
            MockClient.return_value = mock_client

            asyncio.get_event_loop().run_until_complete(bootstrap(dry_run=True))

        captured = capsys.readouterr()
        output = captured.out

        # Dry run header should be present
        assert "DRY RUN" in output or "dry run" in output.lower()

        # Should show estimated calls
        assert "27" in output

        # No real API calls made
        mock_client.get_ipl_schedule.assert_not_called()
        mock_client.get_team_players.assert_not_called()
        mock_client.get_venue_info.assert_not_called()

    def test_dry_run_shows_10_team_squads(self, capsys):
        """--dry-run output should reference all 10 IPL teams."""
        from scripts.bootstrap_cricbuzz_data import bootstrap
        from app.services.cricbuzz_client import IPL_2026_SQUADS

        with patch("app.services.cricbuzz_client.CricbuzzClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.close = AsyncMock()
            MockClient.return_value = mock_client

            asyncio.get_event_loop().run_until_complete(bootstrap(dry_run=True))

        captured = capsys.readouterr()
        output = captured.out

        for team_name in IPL_2026_SQUADS:
            assert team_name in output, f"Expected {team_name!r} in dry-run output"
