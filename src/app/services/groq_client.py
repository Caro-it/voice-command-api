from groq import APIStatusError, Groq, GroqError

from src.app.core.config import get_settings


def get_groq_client() -> Groq:
    settings = get_settings()
    return Groq(
        api_key=settings.groq_api_key,
        timeout=settings.request_timeout_seconds,
    )


def groq_error_message(exc: GroqError) -> str:
    """Human-readable Groq error (status + message). Never includes the API key."""
    if isinstance(exc, APIStatusError):
        body = exc.body if isinstance(exc.body, dict) else {}
        error = body.get("error", {}) if isinstance(body.get("error"), dict) else {}
        return f"{exc.status_code} {error.get('message') or exc.__class__.__name__}"
    return exc.__class__.__name__
