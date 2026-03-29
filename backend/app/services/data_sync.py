"""
DataSyncService — knows WHAT to fetch, WHEN to fetch it, and HOW to store it.

Every method checks DB/Redis state before making API calls.
This is the primary budget-conservation layer.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.cricbuzz_client import CricbuzzClient, IPL_2026_SQUADS, ALL_SQUAD_IDS

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _hours_ago(hours: float) -> datetime:
    return _now_utc() - timedelta(hours=hours)


def _days_ago(days: float) -> datetime:
    return _now_utc() - timedelta(days=days)


class DataSyncService:
    def __init__(self, db: AsyncSession, client: CricbuzzClient | None = None):
        self.db = db
        self.client = client or CricbuzzClient()
        self._redis: aioredis.Redis | None = None

    def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        return self._redis

    async def _get_flag(self, key: str) -> str | None:
        try:
            return await self._get_redis().get(key)
        except Exception:
            return None

    async def _set_flag(self, key: str, ttl: int) -> None:
        try:
            await self._get_redis().setex(key, ttl, "1")
        except Exception as e:
            logger.warning(f"Redis set flag failed {key}: {e}")

    # -----------------------------------------------------------------------
    # sync_ipl_schedule
    # -----------------------------------------------------------------------

    async def sync_ipl_schedule(self) -> dict:
        """Sync IPL 2026 schedule. Skips if synced within 6 hours."""
        flag = await self._get_flag("cricbuzz:sync:schedule:last_run")
        if flag:
            logger.info("sync_ipl_schedule: skipped — synced within 6 hours")
            return {"new": 0, "updated": 0, "unchanged": 0, "skipped": True}

        data = await self.client.get_ipl_schedule()
        new_count = updated_count = unchanged_count = 0

        try:
            from app.models.match import Match, MatchFormat, MatchStatus

            matches_raw = self._extract_matches_from_schedule(data)
            for m in matches_raw:
                cricbuzz_id = str(m.get("matchId", ""))
                if not cricbuzz_id:
                    continue

                result = await self.db.execute(
                    select(Match).where(Match.cricbuzz_id == cricbuzz_id)
                )
                existing = result.scalar_one_or_none()

                match_date = self._parse_match_date(m)
                team1 = m.get("team1", {}).get("teamName", "TBD")
                team2 = m.get("team2", {}).get("teamName", "TBD")
                team1_short = m.get("team1", {}).get("teamSName", "")
                team2_short = m.get("team2", {}).get("teamSName", "")
                venue_cb_id = m.get("venueInfo", {}).get("id")
                match_desc = m.get("matchDesc", "")
                match_number = None
                try:
                    import re as _re
                    mn = _re.search(r"(\d+)", match_desc or "")
                    if mn:
                        match_number = int(mn.group(1))
                except Exception:
                    pass
                state = m.get("state", "upcoming").lower()
                from app.models.match import MatchStatus as _MS
                status_map = {"complete": _MS.COMPLETED, "live": _MS.LIVE, "upcoming": _MS.UPCOMING, "abandoned": _MS.ABANDONED}
                status = status_map.get(state, _MS.UPCOMING)
                match_start_utc = None
                try:
                    ts_ms = m.get("startDate")
                    if ts_ms:
                        match_start_utc = datetime.fromtimestamp(int(ts_ms)/1000, tz=timezone.utc)
                except Exception:
                    pass

                if existing is None:
                    match = Match(
                        cricbuzz_id=cricbuzz_id,
                        cricbuzz_series_id=settings.IPL_2026_SERIES_ID,
                        team1=team1,
                        team2=team2,
                        team1_short=team1_short or None,
                        team2_short=team2_short or None,
                        date=match_date,
                        match_number=match_number,
                        match_start_utc=match_start_utc,
                        format=MatchFormat.T20,
                        status=status,
                        competition="IPL 2026",
                        series_name="Indian Premier League 2026",
                        venue_cricbuzz_id=venue_cb_id,
                    )
                    self.db.add(match)
                    new_count += 1
                else:
                    changed = False
                    if match_date and existing.date != match_date:
                        existing.date = match_date
                        changed = True
                    if venue_cb_id and existing.venue_cricbuzz_id != venue_cb_id:
                        existing.venue_cricbuzz_id = venue_cb_id
                        changed = True
                    if changed:
                        updated_count += 1
                    else:
                        unchanged_count += 1

            await self.db.commit()
        except Exception as e:
            await self.db.rollback()
            logger.error(f"sync_ipl_schedule DB error: {e}")
            raise

        await self._set_flag("cricbuzz:sync:schedule:last_run", 6 * 3600)
        logger.info(f"sync_ipl_schedule: new={new_count} updated={updated_count} unchanged={unchanged_count}")
        return {"new": new_count, "updated": updated_count, "unchanged": unchanged_count}

    def _extract_matches_from_schedule(self, data: Any) -> list[dict]:
        """
        Parse actual Cricbuzz series/v1/{id} response.

        Response structure:
          { matchDetails: [
              { matchDetailsMap: { key: "Sat, 28 Mar 2026",
                                   match: [{ matchInfo: {...}, matchScore: {...} }] } },
              ...
          ]}
        Each matchInfo contains: matchId, team1, team2, venueInfo, startDate, state, status
        """
        matches = []
        if not isinstance(data, dict):
            return matches
        for day in data.get("matchDetails", []):
            dm = day.get("matchDetailsMap", {})
            for m in dm.get("match", []):
                mi = m.get("matchInfo", {})
                if mi.get("matchId"):
                    matches.append(mi)
        return matches

    def _parse_match_date(self, match_info: dict):
        """Parse startDate (milliseconds epoch string) to date."""
        try:
            ts_ms = match_info.get("startDate")
            if ts_ms:
                return datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc).date()
        except Exception:
            pass
        return None

    # -----------------------------------------------------------------------
    # sync_all_ipl_players
    # -----------------------------------------------------------------------

    async def sync_all_ipl_players(self) -> dict:
        """Sync all 10 IPL team squads. Max 10 API calls, once per 24h."""
        flag = await self._get_flag("cricbuzz:sync:players:last_run")
        if flag:
            logger.info("sync_all_ipl_players: skipped — synced within 24 hours")
            from app.models.player import Player
            result = await self.db.execute(select(Player))
            count = len(result.scalars().all())
            return {"total": count, "skipped": True}

        total_synced = 0
        for team_name, squad_info in IPL_2026_SQUADS.items():
            squad_id = squad_info["squadId"]
            try:
                data = await self.client.get_team_players(squad_id)
                players_data = self._extract_players(data)
                synced = await self._upsert_players(players_data, team_name, squad_id)
                total_synced += synced
                logger.info(f"sync_all_ipl_players: {team_name} — {synced} players synced")
            except Exception as e:
                logger.error(f"sync_all_ipl_players: failed for {team_name} squad {squad_id}: {e}")

        await self._set_flag("cricbuzz:sync:players:last_run", 24 * 3600)
        logger.info(f"sync_all_ipl_players: total={total_synced}")
        return {"total": total_synced, "skipped": False}

    def _extract_players(self, data: Any) -> list[dict]:
        """
        Extract player list from series/v1/{id}/squads/{squadId} response.

        Response: { player: [
          { "name": "BATTERS", "isHeader": true },   ← skip these
          { "id": "11813", "name": "Ruturaj Gaikwad", "role": "Batsman",
            "battingStyle": "Right-hand bat", "bowlingStyle": "Right-arm offbreak" },
          ...
        ]}
        """
        players = []
        if not isinstance(data, dict):
            return players
        for p in data.get("player", []):
            if p.get("isHeader"):
                continue
            if p.get("id"):
                players.append(p)
        return players

    async def _upsert_players(self, players_data: list[dict], team_name: str, squad_id: int) -> int:
        from app.models.player import Player, PlayerRole

        count = 0
        for p in players_data:
            cricbuzz_id = str(p.get("id", p.get("playerId", "")))
            if not cricbuzz_id:
                continue

            result = await self.db.execute(
                select(Player).where(Player.cricbuzz_id == cricbuzz_id)
            )
            existing = result.scalar_one_or_none()

            name = p.get("name", p.get("fullName", "Unknown"))
            role_str = p.get("role", "BAT").upper()
            role_map = {
                "BATSMAN": PlayerRole.BATSMAN,
                "BAT": PlayerRole.BATSMAN,
                "BOWLER": PlayerRole.BOWLER,
                "BOWL": PlayerRole.BOWLER,
                "ALL-ROUNDER": PlayerRole.ALL_ROUNDER,
                "ALL ROUNDER": PlayerRole.ALL_ROUNDER,
                "AR": PlayerRole.ALL_ROUNDER,
                "WICKET-KEEPER": PlayerRole.WICKET_KEEPER,
                "WICKET KEEPER": PlayerRole.WICKET_KEEPER,
                "WK": PlayerRole.WICKET_KEEPER,
                "WK-BATSMAN": PlayerRole.WICKET_KEEPER,
            }
            role = role_map.get(role_str, PlayerRole.BATSMAN)

            batting_style = p.get("battingStyle", p.get("battingStyleId", ""))
            bowling_style = p.get("bowlingStyle", p.get("bowlingStyleId", ""))

            if existing is None:
                player = Player(
                    cricbuzz_id=cricbuzz_id,
                    name=name,
                    role=role,
                    batting_style=batting_style or None,
                    bowling_style=bowling_style or None,
                    ipl_team=team_name,
                    ipl_squad_id=squad_id,
                    country="India",
                )
                self.db.add(player)
            else:
                existing.ipl_team = team_name
                existing.ipl_squad_id = squad_id
                if batting_style:
                    existing.batting_style = batting_style
                if bowling_style:
                    existing.bowling_style = bowling_style

            count += 1

        await self.db.commit()
        return count

    # -----------------------------------------------------------------------
    # sync_player_stats
    # -----------------------------------------------------------------------

    async def sync_player_stats(self, player_id: int, force: bool = False) -> dict:
        """Sync batting + bowling stats for a single player. 2 API calls."""
        from app.models.player import Player
        from app.models.player_format_stats import PlayerFormatStats, CricketFormat

        result = await self.db.execute(
            select(Player).where(Player.cricbuzz_id == str(player_id))
        )
        player = result.scalar_one_or_none()
        if not player:
            logger.warning(f"sync_player_stats: player cricbuzz_id={player_id} not found in DB")
            return {"skipped": True, "reason": "not_found"}

        if not force and player.stats_last_synced:
            age = (_now_utc() - player.stats_last_synced.replace(tzinfo=timezone.utc)).total_seconds()
            if age < 12 * 3600:
                return {"skipped": True, "reason": "fresh"}

        batting_data = await self.client.get_player_batting(player_id)
        bowling_data = await self.client.get_player_bowling(player_id)

        await self._upsert_format_stats(player, batting_data, bowling_data)
        player.stats_last_synced = _now_utc()
        await self.db.commit()

        return {"skipped": False, "player_id": str(player.id)}

    async def _upsert_format_stats(self, player, batting_data: Any, bowling_data: Any) -> None:
        from app.models.player_format_stats import PlayerFormatStats, CricketFormat

        batting_by_format = self._parse_batting_stats(batting_data)
        bowling_by_format = self._parse_bowling_stats(bowling_data)

        for fmt in (CricketFormat.T20, CricketFormat.ODI, CricketFormat.TEST):
            b = batting_by_format.get(fmt.value, {})
            w = bowling_by_format.get(fmt.value, {})
            if not b and not w:
                continue

            result = await self.db.execute(
                select(PlayerFormatStats)
                .where(PlayerFormatStats.player_id == player.id)
                .where(PlayerFormatStats.format == fmt)
            )
            existing = result.scalar_one_or_none()

            if existing is None:
                stat = PlayerFormatStats(
                    player_id=player.id,
                    format=fmt,
                    innings=b.get("innings", 0),
                    runs=b.get("runs", 0),
                    avg=b.get("avg", 0.0),
                    strike_rate=b.get("sr", 0.0),
                    hundreds=b.get("hundreds", 0),
                    fifties=b.get("fifties", 0),
                    wickets=w.get("wickets", 0),
                    bowling_avg=w.get("avg", 0.0),
                    economy=w.get("economy", 0.0),
                    best_bowling=w.get("best", None),
                    last_synced=_now_utc(),
                )
                self.db.add(stat)
            else:
                existing.innings = b.get("innings", existing.innings)
                existing.runs = b.get("runs", existing.runs)
                existing.avg = b.get("avg", existing.avg)
                existing.strike_rate = b.get("sr", existing.strike_rate)
                existing.hundreds = b.get("hundreds", existing.hundreds)
                existing.fifties = b.get("fifties", existing.fifties)
                existing.wickets = w.get("wickets", existing.wickets)
                existing.bowling_avg = w.get("avg", existing.bowling_avg)
                existing.economy = w.get("economy", existing.economy)
                if w.get("best"):
                    existing.best_bowling = w["best"]
                existing.last_synced = _now_utc()

    def _parse_stats_columnar(self, data: Any) -> dict[str, dict[str, str]]:
        """
        Parse the actual Cricbuzz stats/v1/player/{id}/batting|bowling response.

        Response format:
          { "headers": ["ROWHEADER", "Test", "ODI", "T20", "IPL"],
            "values": [
              { "values": ["Matches", "0", "9", "23", "71"] },
              { "values": ["Innings", "0", "8", "20", "70"] },
              ...
            ]}

        Returns: { "Test": { "Matches": "0", ... }, "ODI": {...}, "T20": {...}, "IPL": {...} }
        """
        result: dict[str, dict[str, str]] = {}
        if not isinstance(data, dict):
            return result

        headers = data.get("headers", [])
        values_rows = data.get("values", [])

        # Build col_index: {"Test": 1, "ODI": 2, "T20": 3, "IPL": 4}
        col_index: dict[str, int] = {}
        for i, h in enumerate(headers):
            if h != "ROWHEADER":
                col_index[h] = i

        for fmt_name in col_index:
            result[fmt_name] = {}

        for row in values_rows:
            vals = row.get("values", [])
            if not vals:
                continue
            stat_name = vals[0]
            for fmt_name, col_i in col_index.items():
                if col_i < len(vals):
                    result.setdefault(fmt_name, {})[stat_name] = vals[col_i]

        return result

    def _parse_batting_stats(self, data: Any) -> dict:
        """
        Parse batting stats into format-keyed dict for player_format_stats.
        Uses T20 column for international T20, IPL column for IPL.
        We store T20 using the IPL column (more relevant for fantasy).
        """
        out: dict = {}
        columnar = self._parse_stats_columnar(data)
        if not columnar:
            return out

        # Map: T20 key uses IPL stats (most relevant), ODI and TEST use their columns
        format_col_map = {"T20": "IPL", "ODI": "ODI", "TEST": "Test"}

        for fmt, col in format_col_map.items():
            col_data = columnar.get(col, {})
            if not col_data:
                continue
            out[fmt] = {
                "innings": self._safe_int(col_data.get("Innings")),
                "runs": self._safe_int(col_data.get("Runs")),
                "avg": self._safe_float(col_data.get("Average")),
                "sr": self._safe_float(col_data.get("SR")),
                "hundreds": self._safe_int(col_data.get("100s")),
                "fifties": self._safe_int(col_data.get("50s")),
            }

        return out

    def _parse_bowling_stats(self, data: Any) -> dict:
        """Parse bowling stats into format-keyed dict."""
        out: dict = {}
        columnar = self._parse_stats_columnar(data)
        if not columnar:
            return out

        format_col_map = {"T20": "IPL", "ODI": "ODI", "TEST": "Test"}

        for fmt, col in format_col_map.items():
            col_data = columnar.get(col, {})
            if not col_data:
                continue
            wickets = self._safe_int(col_data.get("Wickets"))
            if wickets == 0 and not col_data.get("Wickets"):
                continue
            out[fmt] = {
                "wickets": wickets,
                "avg": self._safe_float(col_data.get("Average")),
                "economy": self._safe_float(col_data.get("Economy")),
                "best": col_data.get("Best") or col_data.get("BBI"),
            }

        return out

    @staticmethod
    def _safe_int(val) -> int:
        try:
            return int(str(val).replace(",", "").replace("-", "0").strip() or 0)
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _safe_float(val) -> float:
        try:
            return float(str(val).replace("-", "0").strip() or 0.0)
        except (ValueError, TypeError):
            return 0.0

    # -----------------------------------------------------------------------
    # sync_venue_data
    # -----------------------------------------------------------------------

    async def sync_venue_data(self, venue_id: int) -> dict:
        """Sync venue info + stats. 2 API calls, skips if synced within 7 days."""
        from app.models.venue import Venue

        result = await self.db.execute(
            select(Venue).where(Venue.cricbuzz_venue_id == venue_id)
        )
        venue = result.scalar_one_or_none()

        if venue and venue.stats_last_synced:
            age = (_now_utc() - venue.stats_last_synced.replace(tzinfo=timezone.utc)).total_seconds()
            if age < 7 * 24 * 3600:
                return {"skipped": True, "venue_id": venue_id}

        # Venue info (name/city) comes from the schedule response (no separate info endpoint)
        # Pull from schedule cache — free, no API call
        name, city = await self._get_venue_name_city_from_schedule(venue_id)
        if not name:
            name = f"Venue {venue_id}"

        # Venue stats: stats/v1/venue/{id}
        stats_data = await self.client.get_venue_stats(venue_id)

        # Parse stats from { venueStats: [{ key, value }] }
        avg_1st, avg_2nd = self._parse_venue_innings_avgs(stats_data)
        capacity = None

        if venue is None:
            venue = Venue(
                cricbuzz_venue_id=venue_id,
                name=name,
                city=city,
                country="India",
                avg_first_innings_score_t20=avg_1st or None,
                avg_second_innings_score_t20=avg_2nd or None,
                stats_last_synced=_now_utc(),
            )
            self.db.add(venue)
        else:
            if name:
                venue.name = name
            if city:
                venue.city = city
            if avg_1st:
                venue.avg_first_innings_score_t20 = avg_1st
            if avg_2nd:
                venue.avg_second_innings_score_t20 = avg_2nd
            venue.stats_last_synced = _now_utc()

        await self.db.commit()
        return {"skipped": False, "venue_id": venue_id, "name": name}

    async def _get_venue_name_city_from_schedule(self, venue_id: int) -> tuple[str, str]:
        """Pull venue name/city from cached schedule response (no API call)."""
        try:
            import json
            import redis.asyncio as aioredis
            r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            raw = await r.get("cricbuzz:ipl:schedule")
            await r.aclose()
            if raw:
                schedule = json.loads(raw)
                for day in schedule.get("matchDetails", []):
                    for m in day.get("matchDetailsMap", {}).get("match", []):
                        vi = m.get("matchInfo", {}).get("venueInfo", {})
                        if vi.get("id") == venue_id:
                            return vi.get("ground", ""), vi.get("city", "")
        except Exception:
            pass
        return "", ""

    def _parse_venue_innings_avgs(self, stats_data: dict) -> tuple[float | None, float | None]:
        """
        Parse venue stats response to extract T20 first/second innings averages.

        Response: { venueStats: [{ key: "Avg. scores recorded",
                                   value: "1st inns-342\n2nd inns-308\n..." }] }
        """
        avg_1st: float | None = None
        avg_2nd: float | None = None
        try:
            for item in stats_data.get("venueStats", []):
                if item.get("key") == "Avg. scores recorded":
                    val = item.get("value", "")
                    import re as _re
                    m1 = _re.search(r"1st inns[- ]+(\d+)", val)
                    m2 = _re.search(r"2nd inns[- ]+(\d+)", val)
                    if m1:
                        avg_1st = float(m1.group(1))
                    if m2:
                        avg_2nd = float(m2.group(1))
        except Exception:
            pass
        return avg_1st, avg_2nd

    # -----------------------------------------------------------------------
    # sync_match_scorecard — extract actual XI from scorecard for completed matches
    # -----------------------------------------------------------------------

    async def sync_match_scorecard(self, cricbuzz_match_id: int) -> dict:
        """
        Pull scorecard for a completed match and populate playing_xi_team1/2
        with actual UUIDs from our players table (matched by cricbuzz_id).
        1 API call (cached 24h).
        """
        from app.models.match import Match
        from app.models.player import Player

        result = await self.db.execute(
            select(Match).where(Match.cricbuzz_id == str(cricbuzz_match_id))
        )
        match = result.scalar_one_or_none()
        if not match:
            return {"skipped": True, "reason": "match_not_found"}

        scorecard = await self.client.get_match_scorecard(cricbuzz_match_id)
        innings_list = scorecard.get("scorecard", [])
        if not innings_list:
            return {"skipped": True, "reason": "no_scorecard"}

        # Collect all cricbuzz player IDs per innings
        innings_player_ids: list[set[int]] = []
        for innings in innings_list:
            ids: set[int] = set()
            for group in ("batsman", "bowler"):
                for p in innings.get(group, []):
                    if p.get("id"):
                        ids.add(int(p["id"]))
            innings_player_ids.append(ids)

        # Innings 1 = team1's batting, innings 2 = team2's batting
        # Union both innings per team to get full XI (batters + bowlers)
        team1_cb_ids = innings_player_ids[0] if len(innings_player_ids) > 0 else set()
        team2_cb_ids = innings_player_ids[1] if len(innings_player_ids) > 1 else set()
        # Players who appeared in both innings are shared (e.g. bowled for team1 AND batted)
        # team1 batted in inn1 and bowled in inn2, vice versa
        # Correct: inn1 batsmen = team1, inn2 batsmen = team2; bowlers are opposing team
        team1_bat_ids = {p["id"] for p in innings_list[0].get("batsman", [])} if innings_list else set()
        team2_bat_ids = {p["id"] for p in innings_list[1].get("batsman", [])} if len(innings_list) > 1 else set()
        team1_bowl_ids = {p["id"] for p in innings_list[1].get("bowler", [])} if len(innings_list) > 1 else set()
        team2_bowl_ids = {p["id"] for p in innings_list[0].get("bowler", [])} if innings_list else set()
        team1_all = team1_bat_ids | team1_bowl_ids
        team2_all = team2_bat_ids | team2_bowl_ids

        # Map cricbuzz IDs → our player UUIDs
        async def resolve_uuids(cb_ids: set[int]) -> list[str]:
            if not cb_ids:
                return []
            rows = await self.db.execute(
                select(Player).where(Player.cricbuzz_id.in_([str(i) for i in cb_ids]))
            )
            return [str(p.id) for p in rows.scalars().all()]

        xi_team1 = await resolve_uuids(team1_all)
        xi_team2 = await resolve_uuids(team2_all)

        match.playing_xi_team1 = xi_team1
        match.playing_xi_team2 = xi_team2
        match.xi_confirmed_at = _now_utc()
        await self.db.commit()

        logger.info(f"sync_match_scorecard {cricbuzz_match_id}: team1={len(xi_team1)}, team2={len(xi_team2)}")
        return {"synced": True, "team1_players": len(xi_team1), "team2_players": len(xi_team2)}

    # -----------------------------------------------------------------------
    # sync_match_results — pull completed match winners from recent endpoint
    # -----------------------------------------------------------------------

    async def sync_match_results(self) -> dict:
        """
        Update winner/result for COMPLETED matches using matches/v1/recent.
        1 API call, skips if synced within 30 min (cache-hit = 0 calls).
        """
        from app.models.match import Match

        data = await self.client.get_recent_matches()
        updated = 0
        skipped = 0

        for type_match in data.get("typeMatches", []):
            for sm in type_match.get("seriesMatches", []):
                saw = sm.get("seriesAdWrapper", {})
                if not saw:
                    continue
                for m in saw.get("matches", []):
                    mi = m.get("matchInfo", {})
                    if mi.get("state") != "Complete":
                        continue
                    match_id = str(mi.get("matchId", ""))
                    status_text = mi.get("status", "")  # e.g. "Mumbai Indians won by 6 wkts"
                    if not match_id or not status_text:
                        continue

                    # Determine winner from status text
                    winner = ""
                    for team_key in ("team1", "team2"):
                        team_name = mi.get(team_key, {}).get("teamName", "")
                        if team_name and team_name in status_text:
                            winner = team_name
                            break

                    result = await self.db.execute(
                        select(Match).where(Match.cricbuzz_id == match_id)
                    )
                    match = result.scalar_one_or_none()
                    if match is None:
                        skipped += 1
                        continue

                    if match.winner and match.result and match.xi_confirmed_at:
                        skipped += 1
                        continue

                    match.winner = winner
                    match.result = status_text
                    match.status = "COMPLETED"
                    updated += 1

                    # Sync scorecard (actual XI) if not yet captured
                    if not match.xi_confirmed_at:
                        try:
                            await self.sync_match_scorecard(int(match_id))
                        except Exception as e:
                            logger.warning(f"scorecard sync failed for {match_id}: {e}")

        await self.db.commit()
        logger.info(f"sync_match_results: {updated} updated, {skipped} skipped")
        return {"updated": updated, "skipped": skipped}

    # -----------------------------------------------------------------------
    # sync_match_playing_xi
    # -----------------------------------------------------------------------

    async def sync_match_playing_xi(self, match_id: int) -> dict:
        """
        Check for confirmed playing XI for a match.
        Burns 0 calls if XI already confirmed or match is > 4 hours away.
        """
        from app.models.match import Match
        import json

        result = await self.db.execute(
            select(Match).where(Match.cricbuzz_id == str(match_id))
        )
        match = result.scalar_one_or_none()

        if match is None:
            return {"skipped": True, "reason": "match_not_found"}

        # Already confirmed — zero API calls
        if match.xi_confirmed_at:
            return {"skipped": True, "reason": "already_confirmed"}

        # Too early — more than 4 hours away
        if match.match_start_utc:
            time_to_match = (
                match.match_start_utc.replace(tzinfo=timezone.utc) - _now_utc()
            ).total_seconds()
            if time_to_match > 4 * 3600:
                return {"skipped": True, "reason": "too_early", "hours_to_match": round(time_to_match / 3600, 1)}

        data = await self.client.get_match_squads(match_id)
        xi_team1, xi_team2 = self._extract_playing_xi(data)

        if xi_team1 or xi_team2:
            match.playing_xi_team1 = xi_team1
            match.playing_xi_team2 = xi_team2
            match.xi_confirmed_at = _now_utc()
            await self.db.commit()
            await self._broadcast_xi(str(match_id))
            return {"confirmed": True, "match_id": match_id}

        return {"confirmed": False, "match_id": match_id}

    def _extract_playing_xi(self, data: Any) -> tuple[dict, dict]:
        """Extract playing XI from match squads response."""
        team1: dict = {}
        team2: dict = {}
        if isinstance(data, dict):
            teams = data.get("teams", data.get("teamSquads", []))
            if isinstance(teams, list) and len(teams) >= 2:
                team1 = self._parse_xi_players(teams[0])
                team2 = self._parse_xi_players(teams[1])
        return team1, team2

    def _parse_xi_players(self, team_data: dict) -> dict:
        players = team_data.get("playingXI", team_data.get("players", []))
        if not isinstance(players, list) or not players:
            return {}
        return {
            "team": team_data.get("teamName", team_data.get("name", "")),
            "players": [
                {
                    "id": str(p.get("id", p.get("playerId", ""))),
                    "name": p.get("name", p.get("fullName", "")),
                    "role": p.get("role", ""),
                }
                for p in players
            ],
        }

    async def _broadcast_xi(self, match_id: str) -> None:
        """Publish XI update to Redis pubsub."""
        import json
        try:
            r = self._get_redis()
            payload = json.dumps({"match_id": match_id, "event": "xi_confirmed"})
            await r.publish("xi_updates", payload)
        except Exception as e:
            logger.warning(f"XI broadcast failed for match {match_id}: {e}")

    # -----------------------------------------------------------------------
    # get_player_stats_for_match — called by intelligence engine
    # -----------------------------------------------------------------------

    async def get_player_stats_for_match(self, player_id: int, match_id: int) -> dict:
        """
        Returns player stats + venue context for a match.
        0 API calls if data is fresh.
        """
        from app.models.player import Player
        from app.models.player_format_stats import PlayerFormatStats, CricketFormat
        from app.models.match import Match

        # Sync player stats if stale
        player_result = await self.db.execute(
            select(Player).where(Player.cricbuzz_id == str(player_id))
        )
        player = player_result.scalar_one_or_none()

        if player:
            stale = (
                not player.stats_last_synced
                or (_now_utc() - player.stats_last_synced.replace(tzinfo=timezone.utc)).total_seconds() > 12 * 3600
            )
            if stale:
                await self.sync_player_stats(player_id)
                # Re-fetch after sync
                player_result = await self.db.execute(
                    select(Player).where(Player.cricbuzz_id == str(player_id))
                )
                player = player_result.scalar_one_or_none()

        # Get T20 format stats
        t20_stats = None
        if player:
            stat_result = await self.db.execute(
                select(PlayerFormatStats)
                .where(PlayerFormatStats.player_id == player.id)
                .where(PlayerFormatStats.format == CricketFormat.T20)
            )
            t20_stats = stat_result.scalar_one_or_none()

        # Get venue data for match
        match_result = await self.db.execute(
            select(Match).where(Match.cricbuzz_id == str(match_id))
        )
        match = match_result.scalar_one_or_none()

        venue_context = {}
        if match and match.venue_cricbuzz_id:
            await self.sync_venue_data(match.venue_cricbuzz_id)
            from app.models.venue import Venue
            venue_result = await self.db.execute(
                select(Venue).where(Venue.cricbuzz_venue_id == match.venue_cricbuzz_id)
            )
            venue = venue_result.scalar_one_or_none()
            if venue:
                venue_context = {
                    "name": venue.name,
                    "pace_wickets_pct": venue.pace_wickets_pct,
                    "spin_wickets_pct": venue.spin_wickets_pct,
                    "avg_first_innings_t20": venue.avg_first_innings_score_t20,
                    "avg_second_innings_t20": venue.avg_second_innings_score_t20,
                }

        return {
            "player_id": player_id,
            "t20_stats": {
                "innings": t20_stats.innings if t20_stats else None,
                "runs": t20_stats.runs if t20_stats else None,
                "avg": t20_stats.avg if t20_stats else None,
                "strike_rate": t20_stats.strike_rate if t20_stats else None,
                "wickets": t20_stats.wickets if t20_stats else None,
                "economy": t20_stats.economy if t20_stats else None,
            } if t20_stats else None,
            "venue": venue_context,
        }
