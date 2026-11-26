# Development progress

## Scope and integration ruling

2026-11-26: v0.4 task plan and parallel development plan copied byte-for-byte from E:/vibe_code; originals remain untouched. Explicit user authorization for parallel isolated worktrees overrides any sequential skill default. Work is on codex/integration only; no merge into main and no push is authorized or performed.

## P0 baseline

Integrated baketball_detect 6598f8e, retaining all detector tests, vendor scripts, attribution and MIT license. The only merge conflict was .gitignore; both useful sets of rules were retained. Inspection before changes found no wechat_service, exclusive WeChat tests, dependencies, configuration or deployment entrypoints in either main b59497d or detection 6598f8e. No recursive deletion was needed. Historical planning documents mentioning the old direction remain historical references, not runnable services.

Shared contracts and exact HTTP examples are in api-contract.md and contracts/models.py. Analysis and rendering remain synchronous worker adapters; new modules follow these contracts. API/config defaults are a 100 MiB upload, 300 second clip and 24 hour retention; deployment may override them.

Unified pyproject declares API/LangGraph dependencies and optional detection/dev groups with package discovery for the five owned module roots. Source checkout is required for vendored algorithm scripts. P0 does not implement API, worker, frontend, LLM or clip export.

## Verification

Current integration run: `C:/Users/lenovo/.codex/worktrees/baketball-detect/vibe_code/.venv/Scripts/python.exe -m pytest -q --basetemp=runs/test-baseline` passed all 45 tests in 5.52 seconds. First run had 31 passes and 14 setup errors because runs/ did not exist; creating that ignored parent resolved every setup error. No detector implementation changes were needed. Contract model imports/default serialization and TOML parse also passed. CLI entrypoint resolves to basketball_detect.__main__:main. No clean dependency installation was performed.

## Evidence boundaries

No real authorized basketball video supplied; synthetic detector and media tests do not establish recognition accuracy. External model path in config.example.json must be provisioned; model weights are not distributed. GPU, VFR/rotation, end-to-end browser playback and real LLM behavior remain to be verified by subsequent delivery work. The borrowed detector virtualenv is not evidence of a clean install of the new API dependencies.

## Parallel preflight rulings

P1 frontend mocks consume the same API contract as backend. P1 video wrappers import contracts models and never backend. P2 worker invokes the graph and rendering synchronously; rendering must not recursively enqueue another task. Original main checkout and its uncommitted v0.4 plans are preserved. Source media currently identified is a demonstration screen recording; real basketball acceptance remains uncertain. User confirmed OpenAI-compatible LLM integration: server-only LLM_BASE_URL, LLM_API_KEY and LLM_MODEL configure that adapter; no credentials enter frontend or tracked files.
