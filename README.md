# AutoFlow

Record a task once in the browser, get back a reusable, parameterised workflow that replays it.

A Chrome extension records what you do as **semantic** events (element role, label, text, form context; never screen coordinates). The backend turns the event stream into higher-level actions and an executable workflow, which a Playwright-based engine replays with your own variable values.

```
Chrome extension ──events──► FastAPI ──► Postgres
 (MV3, TypeScript)              │
                                ├─► HSAE pipeline: preprocess → recognise actions → infer intent → synthesise workflow
                                │
React dashboard ◄──REST/WS──────┤
 (Vite, React Flow)             └─► Celery worker ──► WorkflowEngine ──► Playwright (Chromium)
```

## How it works

**1. Recording.** `extension/src/content/recorder.ts` captures clicks, inputs, selects, submits, copy/paste and navigation. Password and card-like fields are redacted in the browser. The MV3 service worker batches events to `POST /api/v1/recordings/{id}/events`. Session state is persisted so recording survives Chrome killing the idle worker.

**2. HSAE: Hierarchical Semantic Action Extraction** (`backend/src/autoflow/recordings/hsae_pipeline.py`):

| Layer | Module | What it does |
|---|---|---|
| L1 | `preprocessor.py` | drops noise (mousemove/scroll), clusters events in time, infers ARIA roles and form context |
| L2 | `action_recognizer.py` | rule-based recognition of navigation, form fills, searches, downloads and clicks |
| L3 | `ai/intent_extractor.py` | LLM intent and variable detection, with a heuristic fallback when no model is configured |
| L4 | `synthesizer.py` | emits a `WorkflowDefinition` with parameterised `{{variables}}`, detected loops and priority-ordered selectors |

`POST /api/v1/recordings/{id}/extract` runs all four layers over a stored recording.

**3. Replay.** `workflows/engine.py` executes steps in order (or along explicit `next_step_key` branches). It resolves `{{variables.x}}` and `{{outputs.step.y}}`, retries and applies `on_error` policies, and pauses at approval checkpoints. Browser steps share one Playwright page per run (`execution/browser.py`). Elements are located by accessible label → role + name → placeholder → text → CSS. Step conditions use a small AST evaluator, not `eval`, so user-authored workflows can't run code.

## Running it

```bash
cp .env.example .env
docker compose up --build            # postgres, redis, api (runs migrations), worker, flower
docker compose --profile dev-frontend up frontend   # dashboard on :5173
```

Without Docker (Postgres 16, Redis and [uv](https://docs.astral.sh/uv/) installed):

```bash
./start.sh
```

Load the extension: `cd extension && pnpm install && pnpm build`, then go to `chrome://extensions` → Developer mode → **Load unpacked** → `extension/dist`.

API docs: <http://localhost:8000/docs>

## Development

```bash
# backend (Python 3.13)
cd backend
uv sync --extra dev
uv run pytest                     # 34 tests; SQLite in-memory, real Chromium if installed
uv run ruff check src tests
uv run alembic upgrade head       # migrations live in alembic/versions

# frontend
cd frontend && pnpm install
pnpm dev | pnpm build | pnpm lint | pnpm type-check

# extension
cd extension && pnpm install && pnpm build && pnpm type-check
```

The test suite covers the recording and workflow APIs, the HSAE pipeline end to end, migration/model drift (`alembic check`), the engine's step ordering, error policies and browser replay (against a fake Playwright page), and the condition evaluator's sandboxing.

## Project layout

```
backend/src/autoflow/
  recordings/   capture API, HSAE layers 1, 2 and 4
  ai/           LLM client (OpenAI-compatible: Ollama, OpenAI, Anthropic, Gemini, Groq), intent extraction
  workflows/    workflow CRUD, execution engine, run history
  execution/    Celery tasks, Playwright browser session, offline element locator
  core/         settings, async SQLAlchemy, structured logging, API-key auth
frontend/src/   dashboard: recordings, workflows (React Flow editor), run history
extension/      MV3 recorder (TypeScript, bundled with esbuild)
paper/          write-up of the HSAE approach
```

## License

MIT, see [LICENSE](LICENSE).
