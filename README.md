# CricEdge Terminal

> Fantasy cricket intelligence platform for Indian players.
> Bloomberg-style data terminal for Dream11 and My11Circle.

## What it does

CricEdge Terminal gives fantasy cricket players a data-driven edge. It aggregates historical ball-by-ball match data, predicts ownership percentages, recommends captain picks, and surfaces differential players — all in a Bloomberg-inspired dark terminal UI optimised for mobile.

## Screenshots

_Coming soon — add screenshots after production deploy._

## Architecture

```
Browser → Nginx → FastAPI (Socket.io) → PostgreSQL
                        ↓
                     Redis ← Celery workers (beat + worker)
                        ↓
           Cricbuzz / ESPNcricinfo / Twitter / OpenWeather
```

| Layer         | Technology                            |
|---------------|---------------------------------------|
| Backend API   | FastAPI + SQLAlchemy async + Socket.io |
| Database      | PostgreSQL 16                         |
| Cache / Queue | Redis 7 + Celery                      |
| Frontend      | Next.js 14 (App Router) + TypeScript  |
| Styling       | Tailwind CSS + IBM Plex Mono/Sans     |
| Auth          | Supabase JWT                          |
| Payments      | Razorpay UPI subscriptions            |
| Metrics       | Prometheus + prometheus-fastapi-instrumentator |
| Analytics     | PostHog                               |
| Proxy         | Nginx (local) / Railway (prod)        |

## Prerequisites

- Python 3.11+
- Node.js 20+
- Docker + Docker Compose
- PostgreSQL 16 (or use Docker)
- Redis 7 (or use Docker)

## Quick Start (5 commands)

```bash
git clone https://github.com/yourname/cricedge
cd cricedge
cp backend/.env.example backend/.env      # fill in your API keys
docker-compose up -d                       # starts postgres + redis + backend + frontend
python backend/scripts/seed_dev_data.py   # loads IPL 2023-2025 + 2026 fixtures
```

Visit http://localhost:3000

## Environment Variables

| Variable | Description | Required |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string (asyncpg) | Yes |
| `REDIS_URL` | Redis connection string | Yes |
| `CELERY_BROKER_URL` | Celery broker (same as REDIS_URL) | Yes |
| `CELERY_RESULT_BACKEND` | Celery result backend (Redis db 1) | Yes |
| `APP_ENV` | `development` or `production` | Yes |
| `SECRET_KEY` | JWT signing secret | Yes |
| `SUPABASE_URL` | Supabase project URL | Yes (auth) |
| `SUPABASE_ANON_KEY` | Supabase anon key | Yes (auth) |
| `SUPABASE_SERVICE_KEY` | Supabase service key | Yes (auth) |
| `RAZORPAY_KEY_ID` | Razorpay API key | Yes (payments) |
| `RAZORPAY_KEY_SECRET` | Razorpay secret | Yes (payments) |
| `OPENWEATHER_API_KEY` | OpenWeatherMap API key | Optional |
| `TWITTER_BEARER_TOKEN` | Twitter v2 Bearer token | Optional |
| `NEXT_PUBLIC_POSTHOG_KEY` | PostHog project key | Optional |
| `NEXT_PUBLIC_API_URL` | Backend base URL for the frontend | Yes |
| `ALLOWED_ORIGINS` | Comma-separated CORS origins | Yes |

See `.railway.env.example` for a full annotated list.

## Ingesting Cricsheet Data

```bash
# Download + unzip IPL 2025 manually (or use seed script)
wget https://cricsheet.org/downloads/ipl_2025_json.zip
unzip ipl_2025_json.zip -d backend/data/cricsheet/ipl/2025/

# Run the ingester
cd backend
python app/scripts/ingest_cricsheet.py --dir data/cricsheet/ipl/2025/ --format T20

# Or use the all-in-one seed script (downloads all 3 seasons automatically)
python scripts/seed_dev_data.py
```

## Running Tests

```bash
# Backend
cd backend && pytest

# Frontend
cd frontend && npm test
```

## Deployment (Railway)

1. Create a new Railway project
2. Add a Postgres plugin and a Redis plugin — Railway injects `DATABASE_URL` and `REDIS_URL` automatically
3. Create four services from the repo: `backend`, `frontend`, `worker`, `beat`
4. Set environment variables from `.railway.env.example` in each service
5. Deploy — Railway uses `railway.toml` to determine Dockerfile paths and start commands
6. Run the seed script once via Railway's shell to load IPL data

## API Documentation

Auto-generated Swagger UI available at `/docs` and ReDoc at `/redoc` when running locally.

## Tech Stack

- **Backend**: FastAPI (Python 3.11), SQLAlchemy async, PostgreSQL, Redis, Celery
- **Frontend**: Next.js 14 (App Router), TypeScript, Tailwind CSS, Zustand, Recharts
- **Infra**: Docker Compose (local), Railway (prod), Nginx
- **Payments**: Razorpay (UPI subscriptions)
- **Monitoring**: Prometheus metrics + PostHog analytics

## Roadmap

- [ ] WhatsApp playing XI alerts
- [ ] ML-based ownership model (V2)
- [ ] Live match points tracker
- [ ] My11Circle / MPL support
- [ ] Multi-team generator

## License

MIT
