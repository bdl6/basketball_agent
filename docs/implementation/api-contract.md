# Shared API and worker contract (P0)

This is the binding v0.4 MVP contract. JSON uses snake_case; timestamps are UTC ISO 8601. API and Vite should share an origin through a development proxy. No task credentials enter application/access logs.

## Configuration

`GET /api/config` (public, 200):
```json
{"allowed_extensions":[".mp4",".mov",".mkv"],"max_upload_bytes":104857600,"max_duration_seconds":300,"retention_hours":24}
```
Values above are defaults; frontend displays actual server values. Configuration is server-controlled.

## Upload

`POST /api/jobs`, multipart form field `file`, responds 202 immediately after validation and durable queueing:
```json
{"id":"job-example","token":"opaque-random-secret","status":"queued"}
```
A session has one video. Starting another upload requires frontend reset notice. The client saves id/token in localStorage to restore this browser session. Store only token hash server-side.

## Authorization and errors

All job JSON requests require `X-Task-Token: <token>`. Missing, wrong, expired or another task's token returns the same 404 response. Errors use `{"detail":"human-readable message"}`. Invalid input is 422, upload too large 413, unsupported type 415, busy modification 409. Browser playback/download cannot attach custom headers: only `GET /api/jobs/{id}/result` additionally accepts `?token=<token>`. Result URLs must not be logged; redact query strings in server/proxy access logs, send `Referrer-Policy: no-referrer` and `Cache-Control: private, no-store`, and set page referrer policy to no-referrer. Do not expose a static task directory. Token header is also accepted on the result endpoint.

## Status and current result

`GET /api/jobs/{id}` (200):
```json
{"id":"job-example","status":"completed","events":[{"id":"event-1","time":12.5,"label":"made","evidence":{"reason":"trajectory_and_rim_agree"}},{"id":"event-2","time":25.0,"label":"made","evidence":{}}],"displayed_event_ids":["event-1","event-2"],"plan":{"before_seconds":5.0,"after_seconds":2.0,"excluded_event_ids":[]},"result":{"url":"/api/jobs/job-example/result?revision=r1","download_url":"/api/jobs/job-example/result?revision=r1&download=1","revision":"r1"},"error":null}
```
Statuses: queued, analyzing, rendering, completed, failed, interrupted. events contains all original analysis events in source-time order; IDs are stable strings. displayed_event_ids is the time-sorted made subset excluding current exclusions, and defines one-based ordinals in the current chat result. Preserve last successful result and displayed list during a render or failure. Result URLs omit the credential in JSON; the client appends URL-encoded token for video/download. revision prevents browser cache confusion, not version browsing. On successful replacement update result and displayed list together.

## Messages

`GET /api/jobs/{id}/messages` (200):
```json
{"messages":[{"id":"msg-1","role":"assistant","text":"已收到，正在检查视频","created_at":"2026-11-26T08:00:00Z","request_id":null}]}
```
Roles: user, assistant, status. `POST /api/jobs/{id}/messages` JSON:
```json
{"request_id":"client-generated-uuid","text":"去掉第二球，每球前面多留三秒"}
```
Response 202 (also replayed identically for a duplicate request_id):
```json
{"request_id":"client-generated-uuid","status":"queued"}
```
Progress-only query responds 200 with `{"request_id":"client-generated-uuid","status":"completed"}` and adds a real status message without calling an LLM. Clarification/unavailable operations finish without rendering and add an assistant message. request_id is unique per task; persist deduplication before queueing. A duplicate request checks deduplication before busy rejection. New modifications while active return 409; progress remains available. No HTTP request waits for recognition or rendering. Client polls both GET routes until settled.

## Playback and download

`GET /api/jobs/{id}/result?revision=r1&token=...` streams the current verified H.264/AAC MP4 with `Content-Type: video/mp4`, byte Range support (206/416), and inline disposition. `download=1` changes disposition to attachment. Return 404 when no valid current result. A stale revision may return 404; retain previous valid file/reference until replacement succeeds. Frontend uses result URLs from status, never guesses filenames.

## Structured operations

```json
[{"op":"exclude","ordinal":2},{"op":"add_before","value":3.0}]
```
Supported ops: set_before, add_before, set_after, add_after (value in seconds, nonnegative), exclude (ordinal >= 1). Unused optional fields may be omitted or null. Resolve every ordinal against the same pre-request displayed_event_ids snapshot, validate the complete resulting plan (each timing 0..60), then apply atomically. Exclusions become stable event IDs. Event lists do not count merged clips. Defaults: before=5, after=2. Uncertain and missed never render. Empty selected events gives a clear assistant error, no empty MP4.

## Video adapter signatures

Implement these public synchronous callables; worker calls them directly, with trusted task-owned paths only:
```python
from pathlib import Path
from collections.abc import Sequence
from contracts.models import Analysis, EditPlan, Event, RenderResult

# video_engine/analyzer.py
# Original engine raw judgments/evidence retained in each Event.evidence.
def analyze_video(video_path: Path, work_dir: Path, *, model_path: Path) -> Analysis: ...

# video_engine/highlights.py
# Write a new unique output_path, verify before returning; never replace prior result.
def render_highlights(video_path: Path, events: Sequence[Event], plan: EditPlan,
                      output_path: Path) -> RenderResult: ...
```
Analyzer stable IDs must survive persistence/re-render. Analysis includes source duration and metadata. Renderer clips to source bounds, merges overlaps, retains source audio if present, produces browser-playable MP4 and returns selected event_ids. Raise ValueError for invalid plan/no selected made events, RuntimeError for detector/FFmpeg failures. No backend dependency is imported by these adapters. Model path is server configuration and is never supplied by the LLM.

`contracts/models.py` provides shared validation types. Backend owns durable jobs/messages; agent receives persisted events, plan and displayed IDs, updates the plan and invokes renderer without re-analysis for modifications. No checkpoint/version service is implied.


## Server-pushed progress (SSE)

`GET /api/jobs/{id}/events` requires `X-Task-Token` (never a query token). The client uses streaming fetch so credentials remain in the header. Response is `text/event-stream` with buffering disabled and no cache. `event: snapshot` data contains `{job: <status response>, messages: [...]}`; the initial snapshot includes durable history, and subsequent changes are pushed automatically. Heartbeat comments keep idle connections alive. Expiration sends `event: expired` and closes; clients reconnect after transient disconnects and may use existing GET endpoints as fallback.

Recognition publishes stage start/completion messages: 1/6 locate hoop, 2/6 scan tracks, 3/6 select candidates, 4/6 refine candidates, 5/6 verify crossing; rendering is 6/6. Conditional stages only run when candidates exist; no fabricated percentage or ETA. The detector accepts an optional on_progress callback, passed through the production analyzer and graph to the existing acknowledged worker IPC. Each message is committed before the child continues, so completed stages survive refresh. SSE reads task-owned persisted state across API/worker processes.


## User selection

Event labels include made (model-confirmed), probable (high-evidence possible goal), uncertain and missed. POST /api/jobs/{id}/selection takes {request_id,event_ids:[...]} with X-Task-Token. It validates nonempty task-owned non-missed IDs, deduplicates and serializes rendering. No LLM/new detection runs. Ordinary uncertain events render only after explicit user selection; label remains unchanged, evidence.user_selected records intent. Selection flags and exclusions commit with verified output; failures preserve the previous result.

GET /api/jobs/{id}/source provides private source video with Range support and X-Task-Token or query-token protection as on result files. Existing no-access-log/no-referrer/no-store rules apply. Preview depends on browser source codec support; failures show a visible message.
