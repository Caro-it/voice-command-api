from fastapi import APIRouter, HTTPException, Request, status
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from src.app.schemas.voice import InstructionRequest, TranscribeFlowResponse
from src.app.services.executor import execute_instruction
from src.app.services.instruction_router import route_instruction
from src.app.services.transcription import transcribe_audio
from src.app.utils.language import normalize_transcription_language

router = APIRouter(tags=["transcribe"])


@router.get("/")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/transcribe", response_model=TranscribeFlowResponse)
async def transcribe_and_run_flow(request: Request) -> TranscribeFlowResponse:
    content_type = request.headers.get("content-type", "").lower()

    if content_type.startswith("multipart/form-data"):
        transcription = await _transcription_from_audio(request)
    elif content_type.startswith("application/json"):
        transcription = await _transcription_from_json(request)
    else:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Send multipart/form-data with an audio 'file' or application/json with 'transcription'.",
        )

    instruction = await run_in_threadpool(route_instruction, transcription)
    result = await run_in_threadpool(execute_instruction, instruction)
    return TranscribeFlowResponse(
        transcription=transcription,
        instruction=instruction,
        result=result,
    )


async def _transcription_from_audio(request: Request) -> str:
    form = await request.form()
    upload = form.get("file")
    if not isinstance(upload, UploadFile):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing audio 'file' field in multipart form.",
        )

    content = await upload.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded audio file is empty.",
        )

    language = normalize_transcription_language(form.get("language"))
    return await run_in_threadpool(
        transcribe_audio, content, upload.filename or "command.webm", language
    )


async def _transcription_from_json(request: Request) -> str:
    try:
        body = await request.json()
        payload = InstructionRequest.model_validate(body)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="JSON body must be {\"transcription\": \"<non-empty text>\"}.",
        ) from exc

    transcription = payload.transcription.strip()
    if not transcription:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="'transcription' must not be blank.",
        )
    return transcription
