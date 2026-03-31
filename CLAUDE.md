# CricEdge Terminal — Project Context

## What this is
A fantasy cricket intelligence platform for Indian users. Helps Dream11/My11Circle players make data-driven team selections using player form, venue stats, ownership prediction, and captain recommendations. Currently tracking IPL 2026. Free platform — no auth/payment gates on data.

## Tech Stack
- **Backend**: FastAPI (Python 3.11), SQLAlchemy async, PostgreSQL, Redis, Celery + Celery Beat
- **Frontend**: Next.js 14 (App Router), TypeScript, Tailwind CSS, Zustand, SWR, Recharts
- **Infra**: Docker Compose on VPS, host nginx with Let's Encrypt SSL
- **Real-time**: Socket.io (python-socketio) — XI confirmation broadcasts via Redis pubsub
- **Scraping**: Cricbuzz via RapidAPI (`cricbuzz-cricket.p.rapidapi.com`)
- **Metrics**: Prometheus + prometheus-fastapi-instrumentator
- **Payments**: Razorpay (UPI subscriptions) — do not modify
- **Alerts**: WhatsApp Business API — do not modify

## Deployment (VPS only — Railway no longer used)
- All services run via `docker compose` on the VPS
- Host nginx proxies: `cricedge.veraxiss.me` → containers on localhost
  - Frontend → `127.0.0.1:3020`
  - Backend/API → `127.0.0.1:8100`
- SSL via Let's Encrypt (`/etc/letsencrypt/live/cricedge.veraxiss.me/`)
- **To deploy**: `cd /home/kanal/cricedge && ./deploy.sh`
  - Pulls latest code, rebuilds images, restarts services, runs migrations

## Running the Project
```bash
# Start all services (production)
docker compose up -d

# Rebuild and restart everything
./deploy.sh

# Backend dev (local, no Docker)
cd backend && uvicorn app.main:socket_app --reload --port 8000

# Frontend dev (local, no Docker)
cd frontend && npm run dev

# Celery worker
cd backend && celery -A app.tasks.celery_app worker --loglevel=info

# Run tests
cd backend && pytest
cd frontend && npm test
```

## Backend Entry Point
- `app.main:socket_app` — FastAPI wrapped with Socket.io ASGI app. Always use `socket_app`, never `app`, in production start commands.
- Socket.io events: `subscribe` / `unsubscribe` (client joins match room for XI updates)
- Redis pubsub channel: `xi_updates` — backend publishes `{match_id, team}` when XI is confirmed

## API Routes (`/api/v1/`)
| Prefix | File | Key endpoints |
|--------|------|---------------|
| `/matches` | `api/matches.py` | list, search, `/{id}`, `/{id}/playing-xi`, `/{id}/freshness` |
| `/players` | `api/players.py` | list, search, `/{id}` |
| `/venues` | `api/venues.py` | list, `/{id}` |
| `/predictions` | `api/predictions.py` | form, ownership, captain, differential, projection, ev |
| `/admin` | `api/admin.py` | sync triggers, budget status, cricsheet ingest |

Admin endpoints (no auth currently — internal use):
- `POST /admin/sync/schedule` — force IPL schedule sync
- `POST /admin/sync/players` — force player roster sync
- `POST /admin/sync/xi/{match_id}` — force XI sync for a match
- `POST /admin/sync/results` — force match results sync
- `GET /admin/api-budget` — check RapidAPI call budget
- `POST /admin/ingest/cricsheet` — ingest a Cricsheet CSV file

## Intelligence Layer (`app/intelligence/`)
- `form_engine.py` — `PlayerFormEngine`: scores players on last N innings (format/venue/opponent filters)
- `ownership_model.py` — `OwnershipPredictor`: predicts ownership % and differential flags
- `captain_picker.py` — `CaptainPicker`: C/VC recommendations for mega/small contests
- `points_simulator.py` — `MonteCarloSimulator`: Monte Carlo points projection (mean, p25, p75, p90, boom/bust probability)

## Celery Beat Schedule
All times UTC. IST = UTC+5:30.

| Task | Schedule | Purpose |
|------|----------|---------|
| `sync_ipl_schedule_task` | Every 6h | IPL fixture list from Cricbuzz |
| `sync_ipl_players_task` | Daily 00:30 UTC (6 AM IST) | Player rosters |
| `sync_match_xi_task` | Every 5 min, 08:00–17:59 UTC | Playing XI (covers 1:30 PM–11:30 PM IST) |
| `sync_match_results_task` | Every 5 min, 08:00–19:59 UTC | Match results + status |
| `sync_player_stats_batch_task` | Daily 01:30 UTC (7 AM IST) | Player stats batch |
| `update_weather_task` | Every 3h | Venue weather forecasts |
| `budget_check_task` | Every 1h | RapidAPI call budget guard |

## Data Sync Key Behaviours
- `cricbuzz_client.get_match_playing11()` hits `mcenter/v1/{matchId}/playing11` (10-min Redis TTL)
- `cricbuzz_client.get_recent_matches()` hits `matches/v1/recent` (10-min Redis TTL)
- Match status uses `MatchStatus` enum: `upcoming`, `live`, `completed`, `abandoned` (lowercase)
- Playing XI stored as JSON list of UUID strings in `Match.playing_xi_team1/team2`
- `_enrich_xi(xi, db)` in `api/matches.py` resolves UUID strings → `{id, name, short_name, role}` dicts. Requires explicit `uuid.UUID` coercion before `Player.id.in_()` query (SQLAlchemy `Uuid(as_uuid=True)` requires UUID objects, not strings)

## Predictions Caching
All prediction endpoints cache results in Redis for 5 minutes (`CACHE_TTL = 300`). Cache keys: `form:{match_id}`, `ownership:{match_id}`, `captain:{match_id}:{contest_type}`, `differential:{match_id}`, `projection:{player_id}:{match_id}`.

## Database Schema Conventions
- All tables use UUID primary keys (`Uuid(as_uuid=True, native_uuid=False)`)
- Timestamps: `created_at`, `updated_at` (auto-managed)
- Player stats stored as JSONB for flexibility
- Ball-by-ball data from Cricsheet (CSV → PostgreSQL via `scripts/ingest_cricsheet.py`)
- Always use `alembic revision --autogenerate` — never write migrations manually

## Frontend Conventions
- Dark terminal aesthetic — background `#080C10`, accent `#00FF88` (green)
- Font: IBM Plex Mono for data/numbers, IBM Plex Sans for body text
- All data displays refresh every 30 seconds (`setInterval(fetchMatches, 30_000)`)
- Mobile-first: optimised for 390px width (iPhone)
- State management: Zustand (`lib/store.ts`) — `useMatchStore`, `usePlayerStore`, `useUIStore`, `useAuthStore`
- Data fetching: SWR for predictions/detail endpoints, Zustand store for match list
- Socket.io client in layout for real-time XI broadcast → `markXIConfirmed()` in store
- `ErrorBoundary` component wraps match detail page

## Frontend Pages & Components
| Path | Purpose |
|------|---------|
| `app/page.tsx` | Dashboard: today's matches, top differentials, ticker |
| `app/matches/` | Match list + `[id]` detail with XI, ownership, C/VC, weather |
| `app/players/` | Player list + `[id]` detail with form, projections |
| `app/venues/` | Venue list + `[id]` stats |
| `components/CaptainPicker.tsx` | C/VC tabs with ranked recommendations |
| `components/OwnershipBar.tsx` | Visual ownership % bar |
| `components/PlayerFormCard.tsx` | Form score breakdown |
| `components/VenueStats.tsx` | Pitch type, avg scores, pace/spin split |
| `components/WeatherWidget.tsx` | Weather + dew factor |
| `components/Sidebar.tsx` | Upcoming matches sidebar nav |
| `components/ErrorBoundary.tsx` | Catches JS crashes on detail pages |

## Environment Variables
See `backend/.env.example` and `frontend/.env.example`.
Never commit `.env` files.

Key vars:
- `RAPIDAPI_KEY` — Cricbuzz RapidAPI key
- `DATABASE_URL` — `postgresql+asyncpg://...`
- `REDIS_URL` — `redis://...`
- `NEXT_PUBLIC_API_URL` — set to `https://cricedge.veraxiss.me` in production

## Do NOT
- Use sync SQLAlchemy (always async — `AsyncSession`, `await db.execute(...)`)
- Use class components in React (always functional + hooks)
- Skip error handling on scraper calls (Cricbuzz blocks without warning)
- Hardcode any API keys
- Generate migrations manually — use `alembic revision --autogenerate`
- Run `uvicorn app.main:app` — always use `app.main:socket_app`
- Mount `./frontend:/app` volume in production (breaks standalone build)
- Use `--reload` flag in production uvicorn
- Modify auth (Supabase JWT) or Razorpay integration
