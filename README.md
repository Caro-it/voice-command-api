## Solución

🎥 **Demo en vídeo:** [docs/demo.mp4](docs/demo.mp4) — grabación de voz, transcripción y ejecución de la acción.

Implementación del backend del flujo **voz → transcripción → enrutamiento con LLM → acción sobre tareas**, usando FastAPI y Groq (Whisper para STT y un modelo de chat para el enrutamiento).

### 1. Configurar `.env`

Copia `.env.example` a `.env` y rellena tu clave de Groq:

```env
GROQ_API_KEY=tu_clave_de_groq
GROQ_MODEL=openai/gpt-oss-20b
GROQ_TRANSCRIPTION_MODEL=whisper-large-v3-turbo
REQUEST_TIMEOUT_SECONDS=45
ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

> `openai/gpt-oss-20b` es el valor por defecto (en `.env.example` y en `config.py`); el antiguo `llama-3.1-8b-instant` ya no está disponible en Groq y devolvía `404 model_not_found`. Si recibes `502 ... model ... does not exist`, consulta los modelos disponibles en la consola de Groq y cambia `GROQ_MODEL`. Tras editar `.env` hay que **reiniciar uvicorn**: `--reload` solo vigila el código y la configuración se cachea al arrancar. La clave solo se lee desde `src/app/core/config.py` (`get_settings()`); nunca se escribe en el código ni se muestra en logs.

Copia también `frontend/.env.example` a `frontend/.env` (`VITE_API_BASE_URL=http://127.0.0.1:8000`).

### 2. Arrancar

```bash
# Backend (http://127.0.0.1:8000, docs en /docs)
uv sync
uv run uvicorn src.main:app --reload

# Frontend (http://localhost:5173)
cd frontend
npm install
npm run dev
```

### 3. Endpoints

| Método   | Ruta           | Body                                                                       | Éxito                                                        | Errores                                                                                                                                                        |
| -------- | -------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET`    | `/`            | —                                                                          | `200` `{"status":"ok"}`                                      | —                                                                                                                                                              |
| `GET`    | `/tasks`       | —                                                                          | `200` lista de tareas                                        | —                                                                                                                                                              |
| `POST`   | `/tasks`       | `{"title", "done"?}`                                                       | `201` tarea creada                                           | `422` datos inválidos                                                                                                                                          |
| `PUT`    | `/tasks/{id}`  | `{"title", "done"}`                                                        | `200` tarea                                                  | `404` no existe, `422`                                                                                                                                         |
| `PATCH`  | `/tasks/{id}`  | `{"title"?, "done"?}`                                                      | `200` tarea                                                  | `404` no existe, `422`                                                                                                                                         |
| `DELETE` | `/tasks/{id}`  | —                                                                          | `200` `{"message": "Task <id> deleted"}`                     | `404` no existe                                                                                                                                                |
| `POST`   | `/instruction` | `{"transcription"}`                                                        | `200` `{"endpoint","method","params"}` (**no ejecuta nada**) | `422`, `502` fallo/respuesta inválida del LLM                                                                                                                  |
| `POST`   | `/transcribe`  | `multipart/form-data` (`file`, `language`?) **o** JSON `{"transcription"}` | `200` `{"transcription","instruction","result"}`             | `400` sin audio / idioma inválido, `404` tarea no existe, `415` content-type no soportado, `422` transcripción vacía o params incompletos, `502` fallo de Groq |

### 4. Arquitectura

```text
src/app/services/
|-- task_store.py          # lista `tasks` en memoria + contador de ids (nunca reutiliza ids)
|-- groq_client.py         # cliente groq.Groq con api_key y timeout desde settings
|-- transcription.py       # audio -> texto (Whisper)
|-- instruction_router.py  # texto -> {"endpoint","method","params"} (LLM + validación)
`-- executor.py            # ejecuta la instrucción ya decidida contra task_store
```

`POST /transcribe` = `transcribe_audio` (o el texto del JSON) → `route_instruction` (la misma lógica que `POST /instruction`) → `execute_instruction`. Las llamadas síncronas a Groq se ejecutan con `run_in_threadpool` para no bloquear el event loop.

### 5. Decisiones de diseño

- **Se pasa la lista de tareas al LLM.** El mensaje de usuario incluye la transcripción y las tareas actuales (`id`, `title`, `done`) en JSON. Así el modelo puede resolver referencias por título: _"marca comprar leche como hecha"_ → `PATCH /tasks/1 {"done": true}`. Sin esa lista, el modelo tendría que inventarse el id.
- **La salida del LLM se valida antes de usarla.** Se pide `response_format={"type": "json_object"}` con `temperature=0`, y además se comprueba que: el JSON es parseable, encaja con `InstructionPayload`, el método (normalizado a mayúsculas) es uno de `GET/POST/PUT/PATCH/DELETE`, el endpoint cumple `^/tasks(/\d+)?$` y la combinación es coherente (`GET`/`POST` sobre `/tasks`; `PUT`/`PATCH`/`DELETE` sobre `/tasks/{id}`). Si algo falla se responde `502` con un mensaje claro en lugar de ejecutar algo incorrecto. Después, `executor.py` valida los `params` con `TaskCreate`/`TaskReplace`/`TaskUpdate` (`422` si faltan datos).
- **No hay reglas manuales.** Ninguna decisión depende de buscar palabras como `"añade"` o `"add"`: eso falla con sinónimos, otros idiomas o errores de transcripción. Toda la intención la decide el LLM con un _system prompt_ bilingüe que describe las 5 operaciones y trae ejemplos _few-shot_ en español e inglés. El executor solo despacha el método y el endpoint que eligió el modelo. Si el comando es ambiguo o no trata de tareas, el prompt pide devolver un `GET /tasks`, que es inofensivo.
- **Almacenamiento solo en memoria.** Una lista a nivel de módulo protegida con un `Lock` y un contador `itertools.count` (un id borrado nunca se reutiliza). Los datos se pierden al reiniciar el servidor.

### 6. Ejemplos de prueba (PowerShell)

```powershell
$b = 'http://127.0.0.1:8000'
Invoke-RestMethod "$b/tasks" -Method Post -ContentType 'application/json' -Body '{"title":"Comprar leche"}'
Invoke-RestMethod "$b/tasks"
Invoke-RestMethod "$b/tasks/1" -Method Patch -ContentType 'application/json' -Body '{"done":true}'
Invoke-RestMethod "$b/tasks/1" -Method Put -ContentType 'application/json' -Body '{"title":"Comprar pan","done":false}'
Invoke-RestMethod "$b/tasks/1" -Method Delete

# Solo enrutamiento (no modifica las tareas)
Invoke-RestMethod "$b/instruction" -Method Post -ContentType 'application/json' -Body '{"transcription":"add buy groceries to my list"}'

# Flujo completo en modo JSON (fallback manual del frontend)
Invoke-RestMethod "$b/transcribe" -Method Post -ContentType 'application/json' -Body '{"transcription":"add buy groceries to my list"}'
Invoke-RestMethod "$b/transcribe" -Method Post -ContentType 'application/json' -Body '{"transcription":"mark buy groceries as done"}'
# Nota: Windows PowerShell 5.1 decodifica la respuesta como Latin-1 y muestra "Ã±" en vez de "ñ";
# el servidor devuelve UTF-8 correcto (compruébalo con curl.exe o desde el navegador).

# Flujo completo con audio
curl.exe -F "file=@command.webm" -F "language=es" "$b/transcribe"
```

---

# Voice Command API at 4Geeks Academy

<!-- hide -->

By [@ehiber](https://github.com/ehiber) and [other contributors](https://github.com/4GeeksAcademy/voice-command-api/graphs/contributors) at [4Geeks Academy](https://4geeksacademy.com/)

[![build by developers](https://img.shields.io/badge/build_by-Developers-blue)](https://4geeks.com)
[![4Geeks Academy](https://img.shields.io/twitter/follow/4geeksacademy?style=social&logo=x)](https://x.com/4geeksacademy)

_Estas instrucciones tambien estan disponibles en [espanol](./README.es.md)._

**Before you start**: Read the [how to start a coding project](https://4geeks.com/lesson/how-to-start-a-project) guide before writing code.

> We need you! These exercises are built and maintained in collaboration with people like you. If you find any bug 🐞 or typo, please contribute and/or report it.

<!-- endhide -->

---

## 🎯 Your challenge

This repository is the starter template for the **Voice Command API** project.

The frontend is already built. It records up to **20 seconds** of audio in the browser, sends that audio to your backend, and shows:

- the transcription returned by the API
- the final task response returned by the API

Your job is to implement the backend so the full voice-to-action flow works end to end.

---

## How the project works

The frontend uses a single public entry point:

- `POST /transcribe`

The frontend does **not** resolve intents with the Web Speech API. It only captures audio (up to 20 seconds), sends the file to `POST /transcribe`, and shows the backend transcription to make debugging easier.

That endpoint must:

1. receive recorded audio from the frontend
2. transcribe it to text
3. reuse the same routing logic as `POST /instruction`
4. execute the corresponding task action in memory
5. return the transcription, the instruction payload, and the final result

Your backend must also expose:

- `POST /instruction`
- `GET /tasks`
- `POST /tasks`
- `PUT /tasks/{task_id}`
- `PATCH /tasks/{task_id}`
- `DELETE /tasks/{task_id}`

Important:

- Use **in-memory storage only**. No database and no files.
- The frontend is provided and should not be modified as part of the exercise.
- The backend included in this repository is only a template. You must implement the missing logic.

---

## Repository structure

```text
voice-command-api/
|-- .devcontainer/           # Codespaces setup
|-- frontend/                # Ready-made frontend
|   |-- public/
|   `-- src/
|-- src/
|   `-- app/
|       |-- api/routes/      # /transcribe, /instruction, /tasks
|       |-- core/            # Settings and config
|       |-- schemas/         # Request and response contracts
|       |-- services/        # Your implementation goes here
|       `-- utils/
|-- pyproject.toml
|-- README.md
`-- README.es.md
```

---

## 🌱 How to start the project

You can open this project in [GitHub Codespaces](https://codespaces.new/4GeeksAcademy/voice-command-api) or clone it locally.

If you use Codespaces, the repository already includes a `.devcontainer` prepared for Python, Node, FastAPI, and Vite.

### Option A: GitHub Codespaces

1. Open the repository in Codespaces.
2. Wait for the dev container to finish installing dependencies.
3. Create `.env` from `.env.example`.
4. Create `frontend/.env` from `frontend/.env.example`.
5. Run the backend and frontend from the terminal tabs.

### Option B: Local setup

```bash
git clone https://github.com/4GeeksAcademy/voice-command-api
cd voice-command-api
```

Create your own repository and update the remote:

```bash
git remote set-url origin https://github.com/YOUR_USERNAME/YOUR_REPOSITORY
```

### Backend setup

Create a `.env` file from `.env.example` and fill in your Groq credentials.

Install dependencies and run the API:

```bash
uv sync
uv run uvicorn src.main:app --reload
```

### Frontend setup

Create `frontend/.env` from `frontend/.env.example`.

Run the frontend:

```bash
cd frontend
npm install
npm run dev
```

---

## 💻 What you need to do

- [ ] Create a module-level `tasks` list with `id`, `title`, and `done`, using unique incremental IDs.
- [ ] Implement `GET /tasks`, `POST /tasks`, `PUT /tasks/{task_id}`, `PATCH /tasks/{task_id}`, and `DELETE /tasks/{task_id}` using in-memory state.
- [ ] Implement `POST /instruction` to receive `{ "transcription": "..." }`, call Groq, and return **only** routing JSON (no task execution):

```json
{
  "endpoint": "/tasks",
  "method": "POST",
  "params": { "title": "Buy groceries" }
}
```

- [ ] Implement `POST /transcribe` to accept `multipart/form-data`, convert audio to text, reuse `/instruction` logic, execute the selected action, and return `transcription`, `instruction`, and `result`.
- [ ] Do not hardcode intent matching with manual rules such as `if "add" in text`.

⚠️ **IMPORTANT:** The frontend does not resolve intents with Web Speech API. It only captures audio (up to 20 seconds), sends it to `POST /transcribe`, and shows backend transcription to debug STT vs. routing issues.

```json
{
  "transcription": "add buy groceries to my list",
  "instruction": {
    "endpoint": "/tasks",
    "method": "POST",
    "params": {
      "title": "Buy groceries"
    }
  },
  "result": {
    "id": 1,
    "title": "Buy groceries",
    "done": false
  }
}
```

---

## Debugging tip

If the transcription shown in the frontend is already wrong, the problem is in the audio capture or speech-to-text step.

If the transcription is correct but the action is wrong, the problem is in `/instruction`.

---

## ✅ What we will evaluate

- [ ] `POST /transcribe` accepts audio, transcribes it, and reuses `/instruction` routing logic.
- [ ] `POST /instruction` receives plain text and returns only routing JSON (no action execution).
- [ ] `GET /tasks`, `POST /tasks`, `PUT /tasks/{task_id}`, `PATCH /tasks/{task_id}`, and `DELETE /tasks/{task_id}` work correctly with in-memory state.
- [ ] The frontend displays the transcription returned by the backend to help distinguish STT errors from routing errors.

---

## 📦 How to submit this project

1. Push your solution to your GitHub repository.
2. Make sure backend and frontend are included and runnable locally.
3. Share the repository URL and a short video/GIF showing:
   - audio recording (20 seconds max),
   - transcription visible in the frontend,
   - correct task action execution.

---

This and many other projects are built by students as part of the [Coding Bootcamps](https://4geeksacademy.com/) at 4Geeks Academy. Learn more about the [Full-Stack Software Developer](https://4geeksacademy.com/en/career-programs/full-stack), [Data Science & Machine Learning](https://4geeksacademy.com/en/career-programs/data-science-ml), [Cybersecurity](https://4geeksacademy.com/en/career-programs/cybersecurity), and [AI Engineering](https://4geeksacademy.com/en/career-programs/ai-engineering) programs.
