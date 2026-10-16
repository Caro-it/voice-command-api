"""Turns a free-text command into a routing payload using the LLM.

All intent detection happens in the model; this module only builds the prompt
and validates that the model's answer is a well-formed, executable route.
"""

import json
import re

from fastapi import HTTPException, status
from groq import GroqError
from pydantic import ValidationError

from src.app.core.config import get_settings
from src.app.schemas.voice import InstructionPayload
from src.app.services import task_store
from src.app.services.groq_client import get_groq_client, groq_error_message

ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
_ENDPOINT_RE = re.compile(r"^/tasks(/\d+)?$")
# Methods that act on the collection vs. on a single task.
_COLLECTION_METHODS = {"GET", "POST"}
_ITEM_METHODS = {"PUT", "PATCH", "DELETE"}

SYSTEM_PROMPT = """\
Eres un enrutador de comandos para una API de tareas (to-do list).
You are a command router for a to-do list REST API.

Recibirás la transcripción de un comando de voz (en español o inglés) y la lista
actual de tareas en JSON. Debes decidir qué llamada a la API ejecuta el comando.
You will receive a voice command transcription (Spanish or English) and the
current task list as JSON. Decide which API call fulfils the command.

RESPONDE ÚNICAMENTE con un objeto JSON, sin texto adicional, con esta forma exacta:
RESPOND ONLY with a JSON object, no extra text, with exactly this shape:
{"endpoint": "<path>", "method": "<HTTP METHOD>", "params": {<body>}}

Operaciones disponibles / Available operations:
1. GET    /tasks        params: {}                              -> listar tareas / list tasks
2. POST   /tasks        params: {"title": str}                  -> crear tarea / create task
3. PUT    /tasks/{id}   params: {"title": str, "done": bool}    -> reemplazar tarea completa / replace whole task
4. PATCH  /tasks/{id}   params: {"title"?: str, "done"?: bool}  -> modificar parcialmente (completar, renombrar) / partial update (complete, rename)
5. DELETE /tasks/{id}   params: {}                              -> borrar tarea / delete task

Reglas / Rules:
- "endpoint" debe contener el id REAL de la tarea, p. ej. "/tasks/3". Nunca uses "{id}" literal.
  "endpoint" must contain the REAL task id, e.g. "/tasks/3". Never output a literal "{id}".
- Resuelve referencias por título usando la lista de tareas actual (coincidencia aproximada).
  Resolve references by title using the current task list (fuzzy match).
- "method" siempre en MAYÚSCULAS. "method" always UPPERCASE.
- Para completar / marcar como hecha usa PATCH con {"done": true}; para desmarcar {"done": false}.
  To complete / mark done use PATCH with {"done": true}; to un-complete {"done": false}.
- Para renombrar usa PATCH con {"title": "<nuevo título>"}. To rename use PATCH with {"title": "<new title>"}.
- Usa PUT solo si el usuario da título y estado completos. Use PUT only when both title and done are given.
- El título de una tarea nueva debe ser conciso, sin verbos de comando ("añade", "add", "a mi lista").
  New task titles must be concise, without command words ("añade", "add", "to my list").
  Conserva el idioma del usuario. Keep the user's language.
- Si el comando es ambiguo, no es sobre tareas, o la tarea mencionada no existe en la lista,
  responde con {"endpoint": "/tasks", "method": "GET", "params": {}}.
  If the command is ambiguous, unrelated to tasks, or the referenced task is not in the list,
  respond with {"endpoint": "/tasks", "method": "GET", "params": {}}.

Ejemplos / Examples (lista de tareas / task list:
[{"id": 1, "title": "Comprar leche", "done": false}, {"id": 2, "title": "Call mom", "done": false}, {"id": 3, "title": "Pagar la luz", "done": true}]):

"añade comprar pan a mi lista"
{"endpoint": "/tasks", "method": "POST", "params": {"title": "Comprar pan"}}

"add buy groceries to my list"
{"endpoint": "/tasks", "method": "POST", "params": {"title": "Buy groceries"}}

"¿qué tareas tengo?"
{"endpoint": "/tasks", "method": "GET", "params": {}}

"show me my tasks"
{"endpoint": "/tasks", "method": "GET", "params": {}}

"marca comprar leche como hecha"
{"endpoint": "/tasks/1", "method": "PATCH", "params": {"done": true}}

"I already called mom"
{"endpoint": "/tasks/2", "method": "PATCH", "params": {"done": true}}

"cambia el nombre de pagar la luz a pagar la factura de luz"
{"endpoint": "/tasks/3", "method": "PATCH", "params": {"title": "Pagar la factura de luz"}}

"rename call mom to call grandma"
{"endpoint": "/tasks/2", "method": "PATCH", "params": {"title": "Call grandma"}}

"reemplaza la tarea 1 por comprar café, sin completar"
{"endpoint": "/tasks/1", "method": "PUT", "params": {"title": "Comprar café", "done": false}}

"borra la tarea de comprar leche"
{"endpoint": "/tasks/1", "method": "DELETE", "params": {}}

"delete call mom"
{"endpoint": "/tasks/2", "method": "DELETE", "params": {}}
"""


def _bad_gateway(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)


def _build_user_message(transcription: str) -> str:
    current_tasks = [
        {"id": t["id"], "title": t["title"], "done": t["done"]}
        for t in task_store.list_tasks()
    ]
    return json.dumps(
        {"transcription": transcription, "current_tasks": current_tasks},
        ensure_ascii=False,
    )


def _validate(raw_content: str | None) -> InstructionPayload:
    if not raw_content:
        raise _bad_gateway("The LLM returned an empty response.")

    try:
        data = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise _bad_gateway("The LLM response is not valid JSON.") from exc

    try:
        payload = InstructionPayload.model_validate(data)
    except ValidationError as exc:
        raise _bad_gateway(
            "The LLM response does not match {endpoint, method, params}."
        ) from exc

    method = payload.method.strip().upper()
    endpoint = payload.endpoint.strip()

    if method not in ALLOWED_METHODS:
        raise _bad_gateway(f"The LLM returned an unsupported method: {payload.method!r}.")
    match = _ENDPOINT_RE.fullmatch(endpoint)
    if not match:
        raise _bad_gateway(f"The LLM returned an invalid endpoint: {payload.endpoint!r}.")

    has_id = match.group(1) is not None
    if (method in _COLLECTION_METHODS and has_id) or (method in _ITEM_METHODS and not has_id):
        raise _bad_gateway(
            f"The LLM returned an invalid method/endpoint combination: {method} {endpoint}."
        )

    params = {} if method in {"GET", "DELETE"} else payload.params
    return InstructionPayload(endpoint=endpoint, method=method, params=params)


def route_instruction(transcription: str) -> InstructionPayload:
    settings = get_settings()
    try:
        completion = get_groq_client().chat.completions.create(
            model=settings.groq_model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_message(transcription)},
            ],
        )
    except GroqError as exc:
        raise _bad_gateway(f"Groq routing request failed: {groq_error_message(exc)}") from exc

    return _validate(completion.choices[0].message.content)
