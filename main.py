"""
Sawa — AI-Powered WhatsApp HR Platform for Nigerian Businesses
Thin webhook handler; logic lives in conversation.py, hiring.py, ai.py
"""
import logging

from fastapi import FastAPI, Form, Depends, Request, HTTPException
from fastapi.responses import Response, JSONResponse
from typing import Optional
from contextlib import asynccontextmanager

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from config import settings
from sqlalchemy import text
from db import engine, async_session, Base
from auth import validate_twilio_request
from utils import twiml_response, sanitize_input
from conversation import handle_message, show_menu

# ── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}',
)
logger = logging.getLogger("sawa")

# ── App Lifecycle ───────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Sawa starting up")
    yield
    await engine.dispose()
    logger.info("Sawa shut down")

app = FastAPI(title="Sawa HR", lifespan=lifespan)

# ── Rate Limiting ───────────────────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return twiml_response("Too many requests. Please wait a moment and try again.")


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Return TwiML for webhook errors so Twilio doesn't report retrieval failure."""
    if "/whatsapp/" in str(request.url):
        return twiml_response("Request denied.")
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


# ── Webhook ─────────────────────────────────────────────────────────────────

@app.post("/whatsapp/webhook")
@limiter.limit("30/minute")
async def whatsapp_webhook(
    request: Request,
    From: str = Form(...),
    Body: str = Form(...),
    MessageSid: Optional[str] = Form(None),
    _twilio=Depends(validate_twilio_request),
):
    phone = From.replace("whatsapp:", "")
    text = sanitize_input(Body)

    try:
        async with async_session() as session:
            async with session.begin():
                response_text = await handle_message(session, phone, text)
                return twiml_response(response_text)
    except Exception as e:
        import traceback
        err = traceback.format_exc()
        logger.exception("Webhook error for phone=%s", phone[:4] + "****")
        # Temporary: include error in response for debugging
        return twiml_response(f"Error: {type(e).__name__}: {str(e)[:200]}")


# ── Health & Root ───────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"status": "Sawa HR is running!", "version": "2.0.0"}


@app.get("/health")
async def health():
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected"}
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "database": "disconnected"},
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
