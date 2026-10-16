from typing import Any

from fastapi import HTTPException, status
from groq import GroqError

from src.app.core.config import get_settings
from src.app.services.groq_client import get_groq_client, groq_error_message


def transcribe_audio(content: bytes, filename: str, language: str | None) -> str:
    settings = get_settings()
    kwargs: dict[str, Any] = {
        "file": (filename, content),
        "model": settings.groq_transcription_model,
    }
    if language:
        kwargs["language"] = language

    try:
        response = get_groq_client().audio.transcriptions.create(**kwargs)
    except GroqError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Groq transcription failed: {groq_error_message(exc)}",
        ) from exc

    text = (getattr(response, "text", "") or "").strip()
    if not text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The audio produced an empty transcription. Try speaking closer to the mic.",
        )
    return text
