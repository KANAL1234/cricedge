import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine, Base, AsyncSessionLocal
from app.api import matches, players, venues, predictions

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Socket.io setup
# ---------------------------------------------------------------------------

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")


@sio.on("subscribe")
async def handle_subscribe(sid, data):
    """Client subscribes to a match room to receive real-time XI updates."""
    match_id = data.get("match_id") if isinstance(data, dict) else None
    if match_id:
        await sio.enter_room(sid, match_id)
        logger.debug(f"Socket {sid} subscribed to match room {match_id}")
    else:
        logger.warning(f"Socket {sid} sent subscribe without match_id: {data}")


@sio.on("unsubscribe")
async def handle_unsubscribe(sid, data):
    """Client unsubscribes from a match room."""
    match_id = data.get("match_id") if isinstance(data, dict) else None
    if match_id:
        await sio.leave_room(sid, match_id)
        logger.debug(f"Socket {sid} unsubscribed from match room {match_id}")


async def _redis_xi_listener(sio_server: socketio.AsyncServer):
    """
    Background coroutine that subscribes to Redis 'xi_updates' pubsub channel
    and emits 'xi_confirmed' events to the relevant Socket.io match rooms.

    Handles Redis disconnects gracefully with exponential backoff reconnect.
    """
    backoff = 1
    max_backoff = 60

    while True:
        redis_client = None
        pubsub = None
        try:
            redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            pubsub = redis_client.pubsub()
            await pubsub.subscribe("xi_updates")
            logger.info("_redis_xi_listener: subscribed to xi_updates channel")
            backoff = 1  # reset backoff on successful connection

            async for message in pubsub.listen():
                if message is None:
                    continue
                if message.get("type") != "message":
                    continue
                try:
                    payload = json.loads(message["data"])
                    match_id = payload.get("match_id")
                    team = payload.get("team")
                    if match_id:
                        await sio_server.emit(
                            "xi_confirmed",
                            {"match_id": match_id, "team": team},
                            room=match_id,
                        )
                        logger.info(
                            f"_redis_xi_listener: emitted xi_confirmed for match {match_id}, team {team}"
                        )
                except json.JSONDecodeError as e:
                    logger.warning(f"_redis_xi_listener: invalid JSON in message: {e}")
                except Exception as e:
                    logger.warning(f"_redis_xi_listener: error processing message: {e}")

        except asyncio.CancelledError:
            logger.info("_redis_xi_listener: shutting down")
            break
        except Exception as e:
            logger.error(f"_redis_xi_listener: connection error: {e}. Reconnecting in {backoff}s")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
        finally:
            try:
                if pubsub:
                    await pubsub.unsubscribe("xi_updates")
                    await pubsub.close()
            except Exception:
                pass
            try:
                if redis_client:
                    await redis_client.aclose()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# FastAPI app with lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Start background Redis → Socket.io relay
    xi_listener_task = asyncio.create_task(_redis_xi_listener(sio))

    yield

    # Shutdown
    xi_listener_task.cancel()
    try:
        await xi_listener_task
    except asyncio.CancelledError:
        pass

    await engine.dispose()


_start_time = time.time()

app = FastAPI(
    title="CricEdge Terminal API",
    description="Fantasy cricket intelligence platform",
    version="0.1.0",
    lifespan=lifespan,
)

# Prometheus auto-instrumentation — exposes GET /metrics
Instrumentator().instrument(app).expose(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(matches.router, prefix="/api/v1/matches", tags=["matches"])
app.include_router(players.router, prefix="/api/v1/players", tags=["players"])
app.include_router(venues.router, prefix="/api/v1/venues", tags=["venues"])
app.include_router(predictions.router, prefix="/api/v1/predictions", tags=["predictions"])

# Admin routes
from app.api import admin  # noqa: E402
app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])


@app.get("/health")
async def health_check():
    """
    Health check endpoint — Railway polls this to determine liveness.
    Always returns HTTP 200; status field indicates degraded vs ok.
    """
    checks: dict = {}
    overall = "ok"

    # Database check
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "connected"
    except Exception as exc:
        logger.warning(f"health_check: DB unreachable — {exc}")
        checks["database"] = "unreachable"
        overall = "degraded"

    # Redis check
    try:
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        await r.ping()
        await r.aclose()
        checks["redis"] = "connected"
    except Exception as exc:
        logger.warning(f"health_check: Redis unreachable — {exc}")
        checks["redis"] = "unreachable"
        overall = "degraded"

    # Match + player counts (best-effort)
    try:
        from sqlalchemy import func as sqlfunc
        from app.models.match import Match
        from app.models.player import Player
        async with AsyncSessionLocal() as session:
            match_count = (await session.execute(sqlfunc.count(Match.id).select())).scalar_one()
            player_count = (await session.execute(sqlfunc.count(Player.id).select())).scalar_one()
        checks["matches_in_db"] = match_count
        checks["players_in_db"] = player_count
    except Exception:
        checks["matches_in_db"] = None
        checks["players_in_db"] = None

    # Last scrape timestamp from Redis (best-effort)
    try:
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        last_scrape = await r.get("cricedge:last_scrape_at")
        await r.aclose()
        checks["last_scrape_at"] = last_scrape
    except Exception:
        checks["last_scrape_at"] = None

    return JSONResponse(
        status_code=200,
        content={
            "status": overall,
            "version": "0.1.0",
            "environment": settings.APP_ENV,
            "checks": checks,
            "uptime_seconds": int(time.time() - _start_time),
        },
    )


# ---------------------------------------------------------------------------
# ASGI app — Socket.io wraps FastAPI
# Must be at module level so uvicorn can load: app.main:socket_app
# ---------------------------------------------------------------------------

socket_app = socketio.ASGIApp(sio, app)
