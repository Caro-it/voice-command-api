from fastapi import APIRouter

from src.app.schemas.voice import InstructionPayload, InstructionRequest
from src.app.services import instruction_router

router = APIRouter(tags=["instruction"])


@router.post("/instruction", response_model=InstructionPayload)
def route_instruction(
    payload: InstructionRequest,
) -> InstructionPayload:
    # Routing only: the returned instruction is NOT executed here.
    return instruction_router.route_instruction(payload.transcription.strip())
