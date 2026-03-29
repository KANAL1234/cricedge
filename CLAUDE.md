# CricEdge Terminal — Project Context

## What this is
A fantasy cricket intelligence platform for Indian users. Helps Dream11/My11Circle players make data-driven team selections using player form, venue stats, ownership prediction, and captain recommendations.

## Tech Stack
- **Backend**: FastAPI (Python 3.11), SQLAlchemy async, PostgreSQL, Redis, Celery
- **Frontend**: Next.js 14 (App Router), TypeScript, Tailwind CSS, Zustand, Recharts
- **Infra**: Docker Compose for local dev, Railway for prod
- **Payments**: Razorpay (UPI subscriptions)
- **Alerts**: WhatsApp Business API

## Key Domain Concepts
- **Ownership %**: Estimated % of Dream11 contest participants selecting a player. High ownership = safe, low ownership = differential. This is the core value prop.
- **Form Engine**: Scores players on last N innings filtered by format (T20/ODI/Test), venue, opponent, conditions
- **Expected Value (EV)**: Weighted score combining form, matchup, conditions, and ownership inverse
- **Playing XI Window**: Official lineups drop 30 mins before match lock. Critical real-time feature.
- **Contest Type**: Small league (head-to-head) = safe picks. Mega contest (lakh+ entries) = need differentials.

## Database Schema Conventions
- All tables use UUID primary keys
- Timestamps: created_at, updated_at (auto-managed)
- Player stats stored as JSONB for flexibility
- Ball-by-ball data from Cricsheet (CSV → PostgreSQL ingestion)

## API Conventions
- All routes prefixed with /api/v1/
- Auth via Supabase JWT (Bearer token in header)
- Paginated responses: { data: [], total: int, page: int, limit: int }
- Error format: { error: string, detail: string, code: int }

## Frontend Conventions
- Dark terminal aesthetic — background #080C10, accent #00FF88 (green)
- Font: IBM Plex Mono for data/numbers, IBM Plex Sans for body text
- All data displays refresh on 30-second intervals during live match window
- Mobile-first: optimised for 390px width (iPhone)

## Running the Project
```bash
# Start all services
docker-compose up -d

# Backend only
cd backend && uvicorn app.main:app --reload --port 8000

# Frontend only
cd frontend && npm run dev

# Run scrapers manually
cd backend && celery -A app.tasks.celery_app worker --loglevel=info

# Run tests
cd backend && pytest
cd frontend && npm run test
```

## Environment Variables
See backend/.env.example and frontend/.env.example for all required vars.
Never commit .env files.

## Do NOT
- Use sync SQLAlchemy (always async)
- Use class components in React (always functional + hooks)
- Skip error handling on scraper calls (sites block without warning)
- Hardcode any API keys
- Generate migrations manually — use `alembic revision --autogenerate`
