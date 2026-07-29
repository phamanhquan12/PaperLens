# Engineering controls for the PaperLens unified research agent

This document maps **what the backend actually implements today** for context
engineering, agent harness engineering, and safety controls. It is intentionally
honest: these controls are **deterministic guardrails**, not content moderation,
not a trust-and-safety classifier, and not a prompt-injection panacea.

## Scope

| In scope | Out of scope |
| --- | --- |
| Backend Python (`app/`), tests, `pyproject.toml`, this doc | Frontend UI files |
| Unified agent (`/agent`, `/agent/stream`, conversation GET) | Paper QA in-memory `_CONV` (still module memory) |
| SQLAlchemy persistence for agent turns | Long-term vector memory / user auth |

## Exact files

| Concern | Files |
| --- | --- |
| Agent harness (LangChain `create_agent`, tools, SSE stream) | `app/agent.py` |
| Symbolic math + plot artifacts | `app/math_tools.py` |
| Input/output guardrails | `app/guardrails.py` |
| HTTP surface | `app/routes.py` |
| Request/response schemas | `app/schemas.py` |
| Runtime limits | `app/config.py`, `.env.example` |
| SQLAlchemy models | `app/db/models.py` (`AgentConversation`, `AgentMessage`) |
| Conversation repository | `app/db/agent_repository.py` |
| Schema bootstrap (`create_all`) | `app/db/session.py` → `init_db`, called from `app/main.py` startup |
| Dependency | `pyproject.toml` (`sympy`) |
| Tests | `tests/test_agent.py` |

## Context engineering

What we do today:

1. **System prompt** in `app/agent.py` `_create_graph` — role, tool-routing rules,
   Markdown/math formatting, and the current selected paper IDs injected as text.
2. **Tool-shaped context** — paper QA/read/compare/research/discovery return
   structured JSON + artifacts; the model sees tool results, not a raw vector dump.
3. **Bounded history** — last `AGENT_HISTORY_LIMIT` (default 24) serializable
   messages are replayed into the next turn from SQLAlchemy.
4. **Multimodal user turn** — optional image is attached only as LangChain
   `HumanMessage` multimodal content for the live call; restored history is
   **text-only** (metadata records that an image existed).

What we do **not** do:

- No automatic summarization / compaction of long threads.
- No retrieval-augmented memory beyond tool calls the model chooses to make.
- No per-user profiles or ACL on conversations.

## Agent harness engineering

| Piece | Behavior |
| --- | --- |
| Framework | LangChain `create_agent` over `ChatOpenAI` (Luna-compatible when model name contains `luna`) |
| Sync path | `POST /agent` → `run_agent` → `invoke` |
| Streaming path | `POST /agent/stream` → `stream_agent` → native `.stream(..., stream_mode=["messages","values"])` yielding SSE `token` / `tool` / `done` |
| Tools | `ask_paper`, `read_paper`, `discover_research`, `compare_paper_set`, `run_research_workflow`, `analyze_math`, `plot_function` |
| Persistence | SQLAlchemy tables created via `Base.metadata.create_all` on startup; works with SQLite and Postgres URLs |
| Conversation restore | `GET /agent/conversations/{conversation_id}` returns user/assistant turns for UI restore |

### Persistence contract

- Stored roles: `human`, `ai`, `tool` (full enough to replay tool loops).
- Chat restore endpoint filters to **user/assistant** text turns.
- **Raw base64 image bytes are never written** to the database. Only
  `has_image`, `image_mime`, and decoded size metadata may be stored.
- On DB errors, load/save logs and degrades (empty history / skipped persist)
  rather than crashing the process mid-stream when possible.

### Math / plot tools

- Parser: SymPy with an **allowlisted** local dict and empty `global_dict`
  (not unrestricted `eval`).
- `analyze_math`: simplify / expand / factor / diff / integrate / solve / latex.
- `plot_function`: returns a `kind: "plot"` artifact with finite `x`/`y` point
  arrays plus expression/LaTeX for **frontend SVG rendering**. It does **not**
  write public image files.
- Hard limits: expression length, x-range bounds, point count, univariate `x` only.

## Guardrail layers

Call these **guardrails** or **safety filters**, not “moderation.”

### Layer A — Input validation (`validate_agent_input`)

Applied to both `/agent` and `/agent/stream` before the model runs:

| Check | Failure code (examples) |
| --- | --- |
| Empty message (and no image) | `empty_message` |
| Message length | `message_too_long` |
| Control characters | `control_characters` |
| Selected paper count | `too_many_papers` |
| Heuristic prompt/secret exfiltration patterns | `exfiltration_pattern` |
| Pasted configured secret substring | `secret_in_input` |
| Image data-URL MIME allowlist | `invalid_image_mime` |
| Image base64 / decoded size | `invalid_image_base64`, `image_too_large` |

Safe client errors: HTTP 400 with `{"error": "<code>", "message": "<safe text>"}`.
Streaming also emits `{type:"error", error, message}` if a guardrail trips later.

### Layer B — Output controls (`apply_output_guardrails` / `guardrail_token`)

| Check | Behavior |
| --- | --- |
| Secret redaction | Replaces configured secret values (API keys, DB URLs) with `[REDACTED]` |
| Dangerous active HTML/JS | Strips/neutralizes `<script>`, `javascript:`, common event handlers, etc. |
| Grounded integrity | If `grounded=true` but no citations and no grounded artifact kinds, demote to `grounded=false` and note `grounded_flag_cleared_missing_evidence` |
| Streaming tokens | Light redaction/sanitize per token (best-effort; final `done` is authoritative) |

### Layer C — Tool sandboxing

Math tools reject banned substrings and non-allowlisted symbols. Plot sampling
coerces non-finite / complex values to `null` points instead of crashing.

## Limitations (technical honesty)

1. **Not moderation** — no toxicity, NSFW, or policy classifier.
2. **Exfiltration patterns are heuristics** — paraphrases and encoding tricks can
   bypass them; do not treat this as prompt-injection immunity.
3. **HTML sanitization is not a full XSS sanitizer** — it targets common active
   constructs in Markdown/HTML-ish answers for API consumers.
4. **Streaming redaction can split secrets across tokens** — final payload is the
   stronger scrub; clients should prefer `done.answer` for display when possible.
5. **Image history is lossy** — subsequent turns do not re-send prior images to
   the model unless the client re-attaches them.
6. **Conversation IDs are unauthenticated** — knowing the UUID is currently
   sufficient to fetch turns; add auth before multi-tenant production use.
7. **`create_all` is bootstrap, not a migration framework** — schema evolution
   for production Postgres should move to Alembic/managed migrations when needed.

## Configuration knobs

| Env / setting | Default | Purpose |
| --- | --- | --- |
| `AGENT_MAX_MESSAGE_CHARS` | 8000 | Input length |
| `AGENT_MAX_SELECTED_PAPERS` | 8 | Selected library papers |
| `AGENT_MAX_IMAGE_BYTES` | 2097152 | Decoded image size |
| `AGENT_HISTORY_LIMIT` | 24 | Persisted/replayed messages |

## Quick verification

```bash
pytest tests/test_agent.py -q
```
