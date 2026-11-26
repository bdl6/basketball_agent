# Development progress

## Scope and integration ruling

2026-11-26: task-plan v0.4 remains the sole MVP scope. The initial P0 copies of both plans were byte-for-byte copies of E:/vibe_code; the integration copies now record implementation progress. Original main checkout E:/vibe_code and its uncommitted plan documents remain untouched. Explicit user authorization for parallel isolated worktrees overrides any sequential skill default. Implementation is on codex branches; no merge into main or push has been performed.

## Actual worktrees

| Branch | Directory | Responsibility |
|---|---|---|
| main | E:/vibe_code | Original checkout; unchanged by integration work |
| codex/integration | C:/Users/lenovo/.codex/worktrees/integration/vibe_code | Shared contracts, integration, verification and docs |
| codex/frontend | C:/Users/lenovo/.codex/worktrees/frontend/vibe_code | Chat UI |
| codex/backend | C:/Users/lenovo/.codex/worktrees/backend/vibe_code | API, SQLite and serial worker |
| codex/video-engine | C:/Users/lenovo/.codex/worktrees/video-engine/vibe_code | Detection adapter and highlights |
| codex/agent | C:/Users/lenovo/.codex/worktrees/agent/vibe_code | LangGraph and structured commands |
| baketball_detect | C:/Users/lenovo/.codex/worktrees/baketball-detect/vibe_code | Retained original detector baseline |

Native tools created and registered the worktrees. Each is a full repository checkout; these folders are not duplicated module directories inside main.

## P0 completed

Baseline commit 3331057 integrated baketball_detect 6598f8e, retaining detector tests, vendor scripts, attribution and MIT license. The sole .gitignore conflict retained useful rules from both sides. Inspection found no wechat_service, exclusive WeChat tests/dependencies/configuration/deployment entrypoints in either main b59497d or detection 6598f8e, so no recursive deletion was necessary. Historical planning references do not represent runnable services.

Shared contracts and exact HTTP examples are in api-contract.md and contracts/models.py. Unified pyproject declares API/LangGraph dependencies and optional detection/dev groups, discovering all five owned module roots. Vendored detector scripts require a source checkout. The P0 detector regression passed all 45 tests in 5.52 seconds using the original detection worktree virtualenv. Initial missing runs/ parent setup errors were corrected; detector implementation was unchanged. Contract imports/defaults, invalid-operation rejection, TOML parse and callable CLI entrypoint were verified.

## P1 and P2 integrated

Integration at 13850c7 contains the frontend, backend, video-engine and agent implementations. Frontend provides fixed welcome, upload/config limits, messages, status, result playback/download controls and session restoration. It read the public [frontend-design source](https://raw.githubusercontent.com/anthropics/skills/main/skills/frontend-design/SKILL.md); frontend/DESIGN.md records layout, color and typography tokens. This records reading a public source, not installing a global skill.

Backend provides authenticated task/message/result routes, SQLite persistence, durable serial queueing and worker invocation. Video adapters retain original judgments/evidence and produce verified MP4 highlights with overlap/boundary/audio handling. LangGraph handles initial analysis/rendering and structured absolute/relative timing and ordinal exclusions; modifications reuse stored events. Deduplication, parameter validation, clarification and preserving a prior valid result on failure are covered by automated checks.

P1 frontend mocks consume the same API contract as backend. Video wrappers import contracts models and never backend. Worker invokes the graph and rendering synchronously; rendering does not recursively enqueue another task. Model configuration uses a server-side OpenAI-compatible adapter; credentials are never frontend configuration.

## Verification evidence before final fixes

These are observed or root-agent-reported integration results before the current final fix wave; they are not a claim that final fixes already passed:

- Full Python suite: 97 passed.
- Frontend: 18 tests passed and production build passed.
- Integration E2E: 2 tests passed using a short temporary path, mocked recognition and LLM, with actual FFmpeg and LangGraph execution. This verifies synthetic orchestration/render behavior rather than real recognition or a live model.
- Actual HTTP smoke: synthetic no-hoop video upload returned 202; worker produced a safe failure and no empty successful result.
- Browser/CUA: welcome, server config and pre-upload instruction prompt verified. Browser file chooser timed out, so successful browser upload, resulting video playback and combined-edit download were not accepted end to end.

## Final implementation verification

Worker lifetime locking, pre-render explanation persistence with acknowledgement, POSIX descendant process termination and Windows extended-path publishing are implemented. The controller inspected the fix paths and regression tests after the independent whole-branch review identified these issues. The final independent scoped re-review could not run because the delegated agents reached their usage limit; this is a review limitation, not a test failure.

Final command: `.venv/Scripts/python.exe -m pytest -q --basetemp=runs/final-verification` — 106 passed, one installed Starlette/httpx deprecation warning, 18.23 seconds. This included nested-path cross-module tests and the explicit >280-character Windows publication regression. Frontend was independently rerun after its last code change: 18 tests passed; production build passed. `git diff --check` passed.

Cross-module verification exercised initial two-event highlights, combined removal/relative adjustment, analysis call count of one, real H.264/AAC output, authenticated Range downloads, prospective explanation persisted before rendering, and preserving the previous movie/plan when a later render fails. Recognition and LLM HTTP responses in this success test were simulated. A real worker subprocess also reported missing-model failure correctly. No live model or real basketball success is claimed.

## Remaining acceptance and evidence boundaries

No live LLM key has been supplied and no real authorized basketball acceptance sample is available. The identified source media is a demonstration screen recording. Recognition precision/recall, real sample/device processing time, live model behavior/cost and full successful browser upload → highlight → combined edit → playback/download remain outstanding. Synthetic tests cannot establish recognition accuracy. External model weights remain server-provisioned and undistributed; GPU and VFR/rotation are not validated. Using a borrowed detector virtualenv is not evidence of a clean installation of all application dependencies.

P3 is only partially verified. Local usage instructions are complete in README; do not treat the integrated code or checked P0/P1/P2 implementation items as completion of v0.4 S4 real-browser acceptance. No production deployment or scope extension is included.


## Stage progress delivery

Implemented task-protected SSE snapshots plus reconnection/polling fallback in the chat. Each recognition stage emits a start and completion message, forwarded through analyzer/graph/runner and committed by worker before continuation. Current status displays the latest detailed stage. Validation: 111 Python tests passed (one existing Starlette/httpx warning), 20 frontend tests passed, production build passed. Live HTTP smoke through port5173 confirmed SSE snapshots and actual worker messages for synthetic hoop localization start/completion, followed by the expected no-hoop failure. This is transport validation, not recognition-quality evidence. Active local servers now use integration worktree for API8000, Web5173 and the serial worker.
