# Coding Agent

A RAG-powered code assistant. It indexes your codebase into a vector store, then answers
questions about it through a LangChain tool-calling agent that can search the code as it
reasons. It can also plan and build a project from a goal, and cache answers so repeat
questions skip the agent entirely.

```
$ cd /path/to/your/project
$ coding-agent
> /ask how does the retriever load its embedder?
> /plan build a Flask + React issue tracker
```

---

## What it does

- **Understands structure, not just text.** Code is split with tree-sitter, so each chunk is a
  whole function, method, or class with its real name and line range — not an arbitrary 50-line
  slice.
- **Cites its sources.** Answers reference specific files, symbol names, and line numbers.
- **Any LLM provider.** OpenAI, Anthropic, or Google — set it in the config, no code changes.
- **Swappable vector store.** ChromaDB on disk by default, or Qdrant (local container or hosted) —
  set `vector_store.provider` and nothing else changes.
- **Hybrid retrieval.** Vector search runs alongside a keyword (BM25) search and the two results
  are fused, so exact identifiers surface even when embeddings would rank them lower.
- **Live, incremental index.** The ChromaDB index is updated in place when files change — an mtime
  check skips unchanged files, and a background filesystem watcher re-indexes edits as you make
  them, so `/ask` reflects the current code without a restart.
- **Plans and builds.** `/plan <goal>` asks the LLM to decompose the goal into a task DAG, shows it
  to you for approval, then executes each task with a scoped sub-agent and verifies the result —
  see [Task planning & execution](#task-planning--execution).
- **Semantic answer cache.** With Redis Stack running, `/ask` answers are cached by meaning, so a
  repeated or rephrased question is served instantly without invoking the agent or its tools — see
  [Semantic cache](#semantic-cache).
- **Conversational memory.** Each project keeps persistent conversation threads in a local SQLite
  store, and long threads are summarized automatically so context survives across launches.
- **Skills.** Drop reusable instruction packages into a project and the agent discovers them and
  loads their full instructions only when a request matches — see [Skills](#skills).
- **Tools and MCP.** Beyond `search_codebase`, the agent can run shell commands and call external
  [MCP servers](#mcp-servers) (GitHub and a launch-directory-scoped filesystem server ship by
  default).
- **Runs mostly on your machine.** With the default ChromaDB store your code never leaves the disk
  index, and the embedder you configure is the only call needed for retrieval. The exceptions are
  Qdrant (chunks go wherever your Qdrant instance lives), the semantic cache (questions and answers
  go to your Redis instance), and the GitHub MCP server (see [MCP servers](#mcp-servers)). Note the
  agent can also execute shell commands.

---

## System Architecture

![System Architecture](./docs/coding_agent_architecture.png)

## Requirements

- Python `>=3.12,<4.0`
- [pipx](https://pipx.pypa.io/installation/) (recommended) or [Poetry](https://python-poetry.org/docs/#installation)
- [Node.js](https://nodejs.org/) (provides `npx`, used to launch the MCP servers on startup — see [MCP servers](#mcp-servers))
- An API key for whichever LLM provider you configure
- Docker (optional) — only to run [Redis Stack](https://redis.io/docs/latest/operate/oss_and_stack/install/install-stack/)
  for the [semantic cache](#semantic-cache). Without it, the cache simply stays disabled.

---

## Setup

**1. Install dependencies**

```bash
pipx install .
```

This puts `coding-agent` on your `PATH`, so you can run it from any directory on your machine.
Add `--editable .` if you plan to modify the source and want the changes picked up immediately.

<details>
<summary>Prefer Poetry? (repo-local development)</summary>

```bash
poetry install
```

Then invoke it as `poetry run coding-agent` from this directory. Note that without `--editable`,
the CLI runs a *copy* of the code inside the virtualenv, so source edits here won't be reflected
until you reinstall.

</details>

**2. Add your API key**

Create a `.env` file in the project root:

```bash
# Google (default)
GOOGLE_API_KEY=your-key-here

# or
OPENAI_API_KEY=your-key-here

# or
ANTHROPIC_API_KEY=your-key-here


# MCP — GitHub server (only needed for the github MCP server)
GITHUB_TOKEN=your-token-here


# Qdrant (only needed if vector_store.provider is qdrant)
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=your-key-here


# Langsmith
LANGSMITH_TRACING=false
LANGSMITH_API_KEY=your-key-here
```

Only the key for your configured provider is needed, plus `GITHUB_TOKEN` if you want the GitHub MCP
server to work. One `.env` in this repo's root is enough for every project — the path is resolved
from the installed package, not the working directory, so you can launch the agent from any
directory. See the note below the config section if you're using a non-editable install.

**3. (Optional) Start Redis Stack for the semantic cache**

The [semantic cache](#semantic-cache) needs a Redis server with the RediSearch module. With
`semantic_cache.auto_start: true` (the default) you don't have to do anything — the agent starts the
container for you the first time you launch it if Redis isn't already reachable (requires Docker).

You can still start it yourself with the same image the auto-start uses:

```bash
docker run -d --name redis-stack -p 6379:6379 redis/redis-stack-server:latest
```

Verify it's up:

```bash
docker exec redis-stack redis-cli ping   # -> PONG
```

If Redis can't be reached and Docker isn't available to start it, the agent starts normally and just
prints `Semantic cache: disabled`. Plain `redis-server` is **not** sufficient — it lacks RediSearch,
so the cache's index creation fails.

**4. Run it**

The agent indexes your **current working directory**, so `cd` into the repo you want to ask
questions about:

```bash
cd /path/to/your/project
coding-agent
```

With the default ChromaDB store, each project you run it in gets its own `.coding-agent/chromadb/`
index, so switching projects just means switching directories.

> **First run in a project takes a while.** The embedding model downloads on first use, and every
> chunk is embedded individually — indexing a mid-sized repo can take several minutes. The result
> is cached in that project's `.coding-agent/chromadb/`, and later runs only re-embed files whose
> contents changed.

> **Qdrant is not per-project.** With `vector_store.provider: qdrant` the collection is a single
> shared one named by `qdrant.collection_name` — it is not scoped to the directory you launched
> from. See the `qdrant` config section below before pointing it at more than one repo.

---

## Commands

| Command | What it does |
|---|---|
| `/ask <question>` | Search the codebase and answer the question (served from cache on a hit) |
| `/plan <goal>` | Generate a task plan for a goal, approve it, then execute it — see [Task planning & execution](#task-planning--execution) |
| `/task_status` | Show a table of task progress for the active project |
| `/reindex` | Re-index the current directory and invalidate the semantic cache for this repo |
| `/show_index` | Print every chunk in the index with its metadata and embedding |
| `/new_session` | Start a fresh conversation thread |
| `/switch <session_id>` | Resume a previous conversation thread by id |
| `/session` | Show the current session id |
| `/exit` or `/quit` | Quit |

Anything else prints the list of available commands.

---

## Task planning & execution

`/plan <goal>` turns a free-text goal into a reviewed, executed set of tasks. It runs in four
stages:

**1. Plan.** The LLM (`llm.model`, temperature `0`) is asked to return a structured `ExecutionPlan`:
a project name and summary, the tech stack and estimated effort, a list of tasks, and any risks and
assumptions. Each task carries a stable id (`task_001…`), a title and description, a `task_type`, the
ids it `depends_on`, the `output_files` it will write, and 3–5 `acceptance_criteria`. The planner is
constrained to 5–20 tasks ordered as a valid DAG (no cycles), roughly
`architecture → schema → config → core → tests → integration`.

> **Resuming.** If an approved project already exists in the task database, `/plan` skips planning
> and resumes that project instead.

**2. Approve.** The plan is rendered as a Rich table and you choose:

| Choice | Effect |
|---|---|
| `[A]pprove` | Persist and execute the plan as-is |
| `[M]odify task` | Edit a single task's description in place, then re-render the plan |
| `[R]eject` | Discard the plan and re-plan with feedback you type at the prompt |

**3. Persist.** The approved plan is written to a SQLite database at `tasks.db_path`
(`.coding-agent/tasks.db`). The project and every task are stored; task results are recorded back
as they complete.

**4. Execute.** A serial orchestrator (`max_concurrent = 1`) repeatedly finds tasks whose
dependencies have all completed, claims them atomically, and runs them one at a time. Each task is
handled by a **fresh sub-agent** built for that task:

- its system prompt includes the task description, the files to produce, the acceptance criteria,
  and the recorded outputs of its dependencies ("PRIOR TASK OUTPUTS");
- it is given a **minimal toolset scoped to the task type** — least privilege per task:

| Task type | Tools available |
|---|---|
| `design` | `read_file`, `write_file`, `list_directory` |
| `implement` | `read_file`, `write_file`, `append_file`, `list_directory` |
| `test` | `read_file`, `write_file`, `append_file`, `list_directory`, `run_command` |
| `review` | `read_file`, `write_file` |
| `integrate` | `read_file`, `write_file`, `append_file`, `list_directory`, `run_command` |
| `configure` | `read_file`, `write_file`, `list_directory`, `file_exists` |

These are the local tools in `tools/filesystem_tools.py` (see [Developer notes](#developer-notes)),
not the MCP filesystem server.

When the sub-agent finishes, an **LLM-as-judge** (`llm.judge_model`) scores the output against the
acceptance criteria and returns `passed` / `score` / `reason`. A score of 6 or more passes; anything
lower raises an error so the task is retried. Every task gets up to `max_retries` attempts (3 by
default): on failure the retry count increments and the task returns to `pending` until attempts are
exhausted, at which point it's marked `failed`.

Tasks move through this state machine:

```
pending ──claim──► in_progress ──success──► completed   (terminal)
                       │
                       ├── failure, retries left ──► pending
                       └── failure, retries gone ──► failed
```

The store also defines `blocked` and `skipped` states for display in `/task_status`, but the current
orchestrator only marks tasks `failed`. When a task fails, the run stops once nothing else is
runnable, and any tasks that depended on it stay `pending`; re-run `/plan` to resume.

**Recovery.** Any task left `in_progress` by a crashed process is detected on the next run and
reset to `pending` (incrementing its retry count) or marked `failed` if retries are exhausted, so
`/plan` can be re-run to continue where it stopped.

When all tasks reach a terminal state the orchestrator prints a summary
(`completed` / `failed` / `blocked` / `skipped`) and then re-indexes the directory so the files the
plan just generated are queryable with `/ask`.

Use `/task_status` at any time to see the active project, overall progress, and a per-task table
(id, type, status, retry count, error).

---

## Semantic cache

The semantic cache serves `/ask` answers from a vector cache instead of re-running the agent, so a
repeated or rephrased question returns instantly and skips every tool call the agent would have
made.

- **Backend:** Redis Stack (Redis + RediSearch) at `semantic_cache.redis_url`. Plain `redis-server`
  will not work, because the vector index needs RediSearch commands (`FT.CREATE` / `FT.SEARCH`).
- **Auto-start:** with `semantic_cache.auto_start: true` (default), the agent checks Redis on launch
  and, if it isn't reachable, starts the `redis-stack` container for you — `docker start` if it
  exists, otherwise `docker run` with `redis/redis-stack-server:latest`. It waits up to
  `semantic_cache.start_timeout` seconds for readiness. Requires Docker; if Docker isn't installed or
  the wait times out, the agent logs a warning and continues with the cache disabled. Set
  `auto_start: false` to manage Redis yourself.
- **How a lookup works:** the question is embedded with the configured embedder, then the nearest
  cached entry is found, filtered by:
  - **domain** — a hash of the working directory, so entries from one project never leak into
    another;
  - **model** — the configured `llm.model`, so an answer from one model isn't served under another.

  If the cosine similarity is at least `semantic_cache.threshold`, the cached answer is returned and
  the log shows `Semantic cache HIT - skipping agent/tool calls`. Otherwise the agent runs and the
  fresh answer is stored.
- **Invalidation:** entries are scoped per repo and dropped when the codebase changes — the
  [filesystem watcher](#developer-notes) invalidates the repo's domain after an indexed file
  changes, and `/reindex` invalidates it explicitly. A new conversation session does **not**
  invalidate the cache.
- **Disabling it:** set `semantic_cache.enabled: false`, or simply don't run Redis. If Redis is
  unreachable the cache is skipped and the agent runs normally.

---

## Configuration

All settings live in `coding_agent/config.yaml`. Environment variables cover credentials and
connection details only — provider API keys, `GITHUB_TOKEN` for the GitHub MCP server, and
`QDRANT_URL` / `QDRANT_API_KEY` when using Qdrant.

`config.yaml` is read from alongside the installed package. With an editable install
(`pipx install --editable .`) that means the copy in this repo — edit it and the change applies on
the next launch.

With a regular (non-editable) install, a copy is baked into the virtualenv and *that* one wins, so
edits here are silently ignored. Locate it with:

```bash
find ~/.local/share/pipx/venvs/coding-agent -name config.yaml
```

Changes to the installed copy are lost on reinstall, so keep this repo as the source of truth and
reinstall rather than editing in place.

```yaml
llm:
  provider: google_genai        # openai | anthropic | google_genai
  model: gemini-2.5-flash
  temperature: 0.0
  judge_model: gemini-3.5-flash-lite  # cheaper model used only for LLM-as-judge

rag:
  mode: hybrid           # semantic | hybrid

skills:
  skills_dir: .coding-agent/skills

tasks:
  db_path: .coding-agent/tasks.db

logging:
  logs_dir: .coding-agent/logs
  log_file: coding-agent.log

memory:
  db_path: .coding-agent/memory/memory.db
  summarize_at_tokens: 4000
  keep_last_messages: 20

embeddings:
  provider: huggingface
  model: sentence-transformers/all-MiniLM-L6-v2
  dims: 384

vector_store:
  provider: chromadb      # chromadb | qdrant
  retrieval_mode: hybrid  # dense | sparse | hybrid

semantic_cache:
  enabled: true
  redis_url: redis://localhost:6379
  threshold: 0.85
  ttl: 86400
  auto_start: true
  container_name: redis-stack
  start_timeout: 20

chromadb:
  persist_dir: .coding-agent/chromadb/
  collection_name: codebase

qdrant:
  collection_name: codebase
```

> `config.yaml` also contains an `elasticsearch` block (`url`, `index_name`) that isn't wired to any
> backend yet — `vector_store.provider` currently supports only `chromadb` and `qdrant`. It's
> reserved for a possible future backend and can be ignored.

> **The `.env` location follows the same rule as `config.yaml`.** It is resolved from the installed
> package, so with a non-editable install the agent looks for `.env` inside the virtualenv rather
> than this repo. Use `pipx install --editable .` if you want to keep keys here.

### `llm`

| Key | Accepts / Default |
|---|---|
| `provider` | `openai`, `anthropic`, `google_genai` |
| `model` | Any model name your provider supports |
| `temperature` | Float, `0.0` for deterministic answers |
| `judge_model` | Model used by the task-execution [LLM-as-judge](#task-planning--execution); must be a valid model ID for the same `provider` |

### `embeddings`

| Key | Accepts / Default |
|---|---|
| `provider` | `openai`, `anthropic`, `google`, `huggingface` |
| `model` | Provider-specific model name |
| `dims` | Output dimensions of `model`; sizes the [semantic cache](#semantic-cache) index. Must match the embedder, e.g. `384` for `all-MiniLM-L6-v2` |

> **The embedder must stay the same between runs.** Indexing and retrieval both call
> `get_embedder()`. If you change this model after indexing, existing chunks were embedded with
> the old model and search results will be nonsense — drop the existing index and re-index (for
> ChromaDB, delete `.coding-agent/chromadb/`; for Qdrant, delete the collection). Also update
> `dims` and drop the Redis cache index (see [Semantic cache](#semantic-cache)).

### `rag`

| Key | Default | Accepts | Purpose |
|---|---|---|---|
| `mode` | `hybrid` | `semantic`, `hybrid` | Use pure vector search, or vector + keyword search |

`semantic` always searches embeddings only. `hybrid` adds a keyword (BM25) leg — see
[Hybrid retrieval](#hybrid-retrieval) for how each backend implements it.

### `memory`

| Key | Default | Purpose |
|---|---|---|
| `db_path` | `.coding-agent/memory/memory.db` | SQLite file holding conversation threads (per project) |
| `summarize_at_tokens` | `4000` | Summarize a thread once it grows past this many tokens |
| `keep_last_messages` | `20` | How many recent messages to keep verbatim when summarizing |

Conversation history is persisted per thread so a session survives restarts. When a thread exceeds
`summarize_at_tokens`, older messages are summarized down to `keep_last_messages` before the next
turn, so long conversations don't keep growing the prompt.

### `tasks`

| Key | Default | Purpose |
|---|---|---|
| `db_path` | `.coding-agent/tasks.db` | SQLite file holding projects and tasks created by `/plan` |

### `semantic_cache`

| Key | Default | Purpose |
|---|---|---|
| `enabled` | `true` | Master switch for the [semantic cache](#semantic-cache) |
| `redis_url` | `redis://localhost:6379` | Redis Stack connection string |
| `threshold` | `0.85` | Minimum cosine similarity for a cache hit; higher = stricter |
| `ttl` | `86400` | Seconds a cached answer lives before expiring |
| `auto_start` | `true` | Start the Redis container automatically on launch when Redis is unreachable (needs Docker) |
| `container_name` | `redis-stack` | Docker container name used when auto-starting |
| `start_timeout` | `20` | Seconds to wait for Redis to become ready after auto-start |

### `skills`

| Key | Default | Purpose |
|---|---|---|
| `skills_dir` | `.coding-agent/skills` | Directory scanned for skill packages — see [Skills](#skills) |

### `vector_store`

| Key | Default | Purpose |
|---|---|---|
| `provider` | `chromadb` | Which backend to index into and search — `chromadb` or `qdrant` |
| `retrieval_mode` | `hybrid` | With `rag.mode: hybrid`, which legs to run — `dense`, `sparse`, or `hybrid` |

`provider` is the only switch that changes storage: the indexer and retriever are each resolved
through a factory at call time, so the rest of the app never imports a concrete backend directly.

`retrieval_mode` is read by whichever hybrid retriever `provider` selects, and does nothing when
`rag.mode` is `semantic`:

### `chromadb`

| Key | Default | Purpose |
|---|---|---|
| `persist_dir` | `.coding-agent/chromadb/` | Where the vector store is written |
| `collection_name` | `codebase` | ChromaDB collection holding the chunks |

Local, embedded, and per-directory — the default for everyday use. The ChromaDB index is updated
**incrementally**: on each run, files whose mtime hasn't changed are skipped, changed files are
re-embedded (old chunks removed first), and chunks for deleted files are removed.

### `qdrant`

| Key | Default | Purpose |
|---|---|---|
| `collection_name` | `codebase` | Qdrant collection holding the chunks |

Connection details come from the `QDRANT_URL` and `QDRANT_API_KEY` env vars, not from
`config.yaml`. Either point `QDRANT_URL` at a local container or a hosted instance; leave
`QDRANT_API_KEY` unset for local Docker without auth.

> **Qdrant collections are global, not per-directory.** The name in `config.yaml` is not scoped to
> the repo you launch from, so one collection cannot hold two projects side by side. Indexing also
> *skips* entirely when the collection already has points, which means running the agent in a
> second project against a collection you already populated will silently answer questions about
> the first project. Use a distinct `collection_name` per project, or stay on ChromaDB, which
> isolates itself under each directory's `.coding-agent/chromadb/`.

Unlike ChromaDB there is no local `persist_dir` — the index lives on the Qdrant server, and
"clearing" it means dropping the collection.

### `logging`

| Key | Default | Purpose |
|---|---|---|
| `logs_dir` | `.coding-agent/logs` | Directory for the log file (created if missing) |
| `log_file` | `coding-agent.log` | File name inside `logs_dir` |

Each project logs to its own `.coding-agent/logs/` directory, so switching projects switches logs.

---

## Skills

Skills are reusable instruction packages the agent loads only when a request matches. The agent sees
each skill's name and description in its system prompt; when one is relevant it calls the
`load_skill` tool to pull the full instructions into context for that turn.

A skill is a folder containing a `SKILL.md`, discovered under `skills.skills_dir`:

```
.coding-agent/skills/
    <name>/
        SKILL.md            # required
        scripts/            # optional support files
        templates/          # optional support files
        resources/          # optional support files
```

`SKILL.md` starts with YAML frontmatter followed by the instruction body:

```markdown
---
name: python_debug
description: Debug Python errors and tracebacks
when_to_use: error, traceback, exception
---

You are an expert Python debugger. Follow these steps...
```

`name` and `description` are the required fields; `when_to_use` is optional but helps the agent
decide when to load the skill. Any other files in the skill folder are listed to the agent so it can
read them on demand if the instructions reference them.

> **Each skill must live in its own `<name>/` subfolder.** A `SKILL.md` placed directly in the
> skills dir (`skills/SKILL.md`) is treated as a stray file and skipped silently — the agent simply
> won't see that skill.

---

## MCP servers

[MCP](https://modelcontextprotocol.io/) servers extend the agent with external tools. They are
declared in `mcp_servers.json` and connected on startup. Two ship by default:

| Server | What it provides | Needs |
|---|---|---|
| `github` | GitHub API tools (issues, PRs, repos) | `GITHUB_TOKEN` in `.env` |
| `filesystem` | File read/write/list tools scoped to the launch directory | — |

Each entry has a `command`, `args`, and `transport`. `${VAR}` placeholders are substituted from the
environment at load time, and `${CWD}` resolves to the directory the agent was launched from — which
is what scopes the `filesystem` server to the project you're querying.

> **The servers start via `npx`, so Node.js is required.** If a server fails to start (Node missing,
> or a bad command), the agent reports an error instead of coming up. See
> [Troubleshooting](#troubleshooting).

> **This is separate from the local filesystem tools used by `/plan`.** The MCP `filesystem` server
> is an extension tool for the interactive agent; the task sub-agents instead use the built-in
> `tools/filesystem_tools.py` tools (see [Task planning & execution](#task-planning--execution)).

---

## Hybrid retrieval

With `rag.mode: hybrid`, `search_codebase` runs a vector search alongside a keyword search. The
two backends implement it differently, because only Qdrant stores sparse vectors:

| | ChromaDB | Qdrant |
|---|---|---|
| **Dense leg** | `Collection.query` over the stored embeddings | `RetrievalMode.DENSE` |
| **Keyword leg** | `rank_bm25`'s `BM25Okapi`, computed in-process over the stored documents | `FastEmbedSparse("Qdrant/bm25")`, queried server-side |
| **Fusion** | Reciprocal rank fusion in-process | Server-side |
| **Extra dependency** | `rank-bm25` | `fastembed` |

`vector_store.retrieval_mode` chooses which legs run:

| Value | What runs |
|---|---|
| `dense` | The vector leg only. On ChromaDB this returns the same results as `rag.mode: semantic`. |
| `sparse` | The keyword leg only. |
| `hybrid` | Both, fused with reciprocal rank fusion (`score = Σ 1/(60 + rank)` across the two ranked lists), then cut to `k`. |

Notes:

- The ChromaDB keyword leg loads the whole index into memory and builds a `BM25Okapi` once per
  process, on the first query. The build is logged at `INFO` and takes a second or two on a
  large repo; later queries only score against it.
- Tokenization lowercases and splits on non-alphanumerics, then adds camelCase subtokens, so
  `get_retriever` also matches `retriever`, and `getRetriever` matches `get`.
- `sparse` returns nothing for a query with no alphanumeric characters, because BM25 has no terms
  to match. `hybrid` still falls back to the dense leg in that case.
- `distance` remains the ChromaDB cosine distance for every returned chunk, so *lower is more
  similar* holds in all three modes. Chunks the keyword leg found on its own get their distance
  from a follow-up lookup; if that lookup fails the value is `None`.
- The two backends will not rank identically. Qdrant's BM25 is a trained sparse encoder over BPE
  subtokens; ChromaDB's is lexical BM25 over the tokenizer described above. Expect overlap, not
  parity.

---

## How it works

```
source files
    │
    ├─ tree-sitter parse ──────► one chunk per function / method / class
    │                             (named, with line ranges)
    ├─ sliding window ────────► for text/config files, and AST fallback
    │
    ▼
incremental index ────────────► configured vector store
  (mtime: skip unchanged,          (ChromaDB on disk, or Qdrant)
   re-embed changed, remove
   deleted)  ▲
             │ live updates
     filesystem watcher ──► re-index changed file + invalidate cache

your question ──► semantic cache ──┬─ hit ──► answer (agent skipped)
   (embed + domain/model filter)   │
                                   └─ miss ─► agent ──┬─► search_codebase tool
                                                      │      │
                                                      │      ├─ dense leg ────► vector store
                                                      │      ├─ keyword leg ──► BM25 (ChromaDB) / sparse vectors (Qdrant)
                                                      │      ▼
                                                      │ reciprocal rank fusion
                                                      │      │
                                                      │      ▼
                                                      │  top-5 chunks
                                                      │
                                                      ├─► load_skill        (skills, on demand)
                                                      ├─► run_command / run_in_directory  (shell)
                                                      └─► MCP tools         (github, filesystem)
                                                             │
                                                             ▼
                                         answer ──► stored in semantic cache + conversation memory

/plan <goal> ──► planner ──► approval ([A]/[M]/[R]) ──► SQLite task store
                                                            │
                                                            ▼
                                   orchestrator ──► task sub-agent (scoped tools)
                                                            │
                                                            ▼
                                                    LLM-as-judge ──► pass / retry
                                                            │
                                                            ▼
                                               re-index generated files
```

The agent is required to call `search_codebase` before answering a codebase question, and is
instructed to say so explicitly if the answer isn't in the codebase. That tool resolves a retriever
through `context/retrievers/factory.py` on every call, so the backend and the search mode are both
chosen from config at query time rather than fixed at import. The other tool families above (skills,
shell, MCP) are registered on every agent build and available alongside it.

---

## Project layout

```
coding_agent/
├── main.py                          # REPL, bootstrap, index loading, command dispatch
├── config.py                        # loads config.yaml
├── config.yaml                      # all settings
├── mcp_servers.json                 # external MCP server definitions
├── agent/
│   ├── factory.py                   # builds the LangChain agent + system prompt
│   ├── orchestrator.py              # handle_query() entry point (cache + agent)
│   └── tools.py                     # search_codebase tool
├── cache/
│   ├── redis_manager.py             # auto-starts Redis Stack (Docker) on launch
│   └── semantic_cache.py            # Redis-backed semantic answer cache
├── context/
│   ├── indexers/
│   │   ├── code_parser.py           # tree-sitter parsing + chunking
│   │   ├── factory.py               # picks the indexer / inspector for the backend
│   │   ├── hybrid_qdrant.py         # dense + sparse vectors (Qdrant, hybrid mode)
│   │   ├── semantic_chroma.py       # incremental embed + store chunks (ChromaDB)
│   │   ├── semantic_qdrant.py       # embed + store chunks (Qdrant)
│   │   └── watcher.py               # watchdog observer → live index updates
│   └── retrievers/
│       ├── factory.py               # picks the retriever for backend + search mode
│       ├── hybrid_chroma.py         # dense + BM25 fused in-process (ChromaDB)
│       ├── hybrid_qdrant.py         # dense + sparse fused server-side (Qdrant)
│       ├── semantic_chroma.py       # embed query + top-k search (ChromaDB)
│       └── semantic_qdrant.py       # embed query + top-k search (Qdrant)
├── llm/
│   └── factory.py                   # provider switching for LLM and embedder
├── mcp/
│   ├── mcp_client.py                # connects to MCP servers, returns their tools
│   └── mcp_config.py                # loads mcp_servers.json + resolves ${VARS}
├── memory/
│   ├── session.py                   # current session id persistence
│   └── short_term.py                # SQLite checkpointer + summarization middleware
├── skills/
│   ├── registry.py                  # discovers + parses SKILL.md packages
│   └── skill_tools.py               # load_skill tool + skills prompt
├── tasks/
│   ├── planner.py                   # goal → ExecutionPlan (task DAG)
│   ├── approval.py                  # A/M/R approval loop + plan rendering
│   ├── task_store.py                # SQLite task/project store + state machine
│   ├── executor.py                  # per-task sub-agent + LLM-as-judge
│   ├── orchestrator.py              # /plan flow + dependency-ordered execution
│   ├── recovery.py                  # resets crashed in_progress tasks
│   └── status.py                    # /task_status table
├── tools/
│   ├── filesystem_tools.py          # scoped read/write/append/delete/list tools
│   └── terminal_tools.py            # run_command / run_in_directory
└── observability/
    └── logger.py                    # per-module loggers -> .coding-agent/logs/
```

---

## Developer notes

**Supported languages (15 grammars across 16 extensions, via tree-sitter):** Python, JavaScript
(`.js`/`.jsx`), TypeScript, TSX, Java, Go, Rust, C, C++, C#, Ruby, PHP, Swift, Kotlin, Bash.

**Text/config files** (`.md`, `.txt`, `.yaml`, `.yml`, `.json`, `.toml`) have no meaningful AST, so
they're chunked by a sliding window: 50 lines with a 10-line overlap so context isn't lost at
boundaries. The same fallback applies when a source file parses but yields no blocks (a file of
only imports, for example).

**Nested definitions are not indexed separately.** When the AST walker hits a class or function it
records it and stops descending, so methods live inside their class chunk rather than appearing as
duplicates.

**Chunk metadata** stored alongside each embedding:

| Field | Meaning |
|---|---|
| `source` | Absolute path to the file |
| `name` | Symbol name (`function_definition` name, or `chunk_N` for text windows) |
| `type` | `function`, `class`, or `block` |
| `start_line` / `end_line` | 1-based line range |
| `mtime` | File modified time when indexed (ChromaDB), used to skip unchanged files |

On ChromaDB, chunk IDs are `source::name::start_line`, so re-indexing updates existing chunks
instead of duplicating them. Qdrant relies on LangChain-generated IDs instead.

**ChromaDB indexing is incremental; Qdrant is not.** On each run, ChromaDB compares each file's
current mtime against the `mtime` stored in its chunks: unchanged files are skipped, changed files
have their old chunks deleted and are re-embedded, and chunks for files that no longer exist are
removed. Qdrant instead **skips entirely when the collection already has points**, so it does not
pick up edits — drop the collection to re-index.

**A filesystem watcher keeps the ChromaDB index live.** `context/indexers/watcher.py` runs a
`watchdog` observer in a background daemon thread over the launch directory. Filesystem events are
debounced (1.5s) and then routed to `index_single_file()` or `remove_file_from_index()`, so edits,
new files, and deletions are reflected in the index without a restart. After each update the watcher
also invalidates the [semantic cache](#semantic-cache) domain for the repo, so stale answers aren't
served after the code changes.

**Task sub-agents run with least privilege.** Each `/plan` task type only receives the tools it
needs (see the table in [Task planning & execution](#task-planning--execution)). These are the local
tools in `tools/filesystem_tools.py` — separate from the MCP `filesystem` server used by the
interactive agent.

**Hybrid retrieval is the shipped default.** `rag.mode: hybrid` means ChromaDB queries go through
`hybrid_chroma.retrieve`. Its BM25 index is built once per process, on the first query, and reused
for the rest of the session — safe because the stored documents only change through the indexer.
Note that the watcher can now change documents underneath a running session; the BM25 index is not
rebuilt when that happens, so a long-running session may keyword-search slightly stale text until
restart. Qdrant's hybrid path builds no local index; `fastembed` handles the sparse side.

**Skipped directories:** `.venv`, `venv`, `__pycache__`, `.git`, `node_modules`, `dist`, `build`.

**Logging.** Each module gets its own logger at `DEBUG`, writing to `.coding-agent/logs/` in the
project you launched from — so each project you query accumulates its own log. The root logger
stays at `WARNING` so third-party libraries (OpenAI, Google, httpcore) don't flood the file.

---

## Troubleshooting

**Search results look unrelated to the question.** The embedder changed since indexing — drop the
existing index and restart to rebuild (`.coding-agent/chromadb/`, or the Qdrant collection). If you
use the semantic cache, also update `embeddings.dims` and drop the cache index (see below).

**Answers are about the wrong project.** You're on Qdrant and reused a `collection_name` that was
already populated from a different repo. Because indexing skips non-empty collections, the first
project's index is being reused silently. Give each project its own collection name, or switch back
to ChromaDB.

**Qdrant errors on startup or `/ask`.** `QDRANT_URL` / `QDRANT_API_KEY` are missing or wrong. They
come from `.env`, not `config.yaml`, and the key is read the same way as your LLM key — see the note
above. Check the server is reachable at that URL; local Qdrant usually needs no API key.

**Qdrant reports a collection of 0 points but you expected an index.** The collection name in
`config.yaml` doesn't match what's on the server, so you queried an empty one. List the server's
collections and reconcile the name.

**`command not found: coding-agent`.** `~/.local/bin` isn't on your `PATH`. pipx prints the exact
`export PATH=...` line to run at install time.

**`ValueError: Unsupported LLM provider`** — `llm.provider` in `config.yaml` must be one of
`openai`, `anthropic`, `google_genai`.

**Config edits have no effect.** You're editing the repo's `config.yaml` but running a non-editable
install, which reads the copy inside the virtualenv. Reinstall with `pipx install --editable .`.

**Authentication error on startup.** Your `.env` key doesn't match the configured provider. The key
is read from this repo's root `.env` regardless of where you launched from.

**The agent fails to start, or MCP errors on startup.** The MCP servers launch via `npx`, so Node.js
must be installed and on your `PATH`; the `github` server also needs `GITHUB_TOKEN` set in `.env`.
Check `.coding-agent/logs/coding-agent.log` for the `Connecting to MCP servers` / `Loaded N tools`
lines to see how far it got.

**A skill isn't picked up.** The file must be `<skills_dir>/<name>/SKILL.md` — a `SKILL.md` placed
directly in the skills dir is skipped silently. Confirm the layout and reload.

**The conversation didn't reset.** Sessions resume from `.coding-agent/memory/current_session`.
Use `/new_session` to start fresh, or `/switch <session_id>` to return to a previous thread.

**I never get a semantic-cache hit.** Check, in order:
1. Is Redis Stack actually running? Look for `Semantic cache: enabled` at startup. If it says
   `disabled` and `auto_start: true`, check Docker is installed/running and that the launch log
   didn't time out; otherwise start it with `docker run -d --name redis-stack -p 6379:6379
   redis/redis-stack-server:latest` (plain `redis-server` won't do). Lookups that throw are logged as
   `Semantic cache lookup failed` in `.coding-agent/logs/coding-agent.log`.
2. Did the store succeed? A `Semantic cache store failed` warning means answers aren't being cached.
3. Does `embeddings.dims` match the embedder's real output size? On a mismatch, Redis stores the
   keys but RediSearch can't index them, so you always miss. Confirm with
   `docker exec redis-stack redis-cli FT.INFO semantic_cache` — a nonzero `hash_indexing_failures`
   with `num_docs 0` is the tell. Fix `dims`, then recreate the index:
   `docker exec redis-stack redis-cli FT.DROPINDEX semantic_cache DD`.
4. Was the cache just invalidated? Any indexed file change (via the watcher) or `/reindex` drops
   the repo's cached answers, so the next `/ask` legitimately misses.

**The semantic cache is disabled even though Redis is running.** The image must include RediSearch
(use `redis/redis-stack-server`), and `semantic_cache.enabled` must be `true` in `config.yaml`. Check
`redis_url` matches where Redis listens, and that `semantic_cache.auto_start` / Docker aren't
pointing auto-start at a different container.

**Indexing seems stuck.** Check `.coding-agent/logs/coding-agent.log` in the project you launched
from — every indexed chunk is logged at `DEBUG`.

**A project re-indexes every time.** ChromaDB found no existing index, or `.coding-agent/chromadb/`
is being cleaned up / written somewhere else. Confirm it exists in the directory you're running
from. (On Qdrant this would show up instead as an index that never gets written — see "Qdrant
errors" above.)

**Edits to indexed code are picked up, but only after a moment.** Expected on ChromaDB: the watcher
debounces filesystem events for 1.5s before re-indexing. On Qdrant, edits are *not* picked up at all
— indexing skips non-empty collections; drop the collection to re-index.

**The first `/ask` takes several seconds, the rest are fast.** The BM25 index over the whole
collection is built on the first hybrid query and cached for the session. The build is logged at
`INFO` in `.coding-agent/logs/coding-agent.log`.

**A term I know is in the code returns nothing.** With `vector_store.retrieval_mode: sparse` only
the keyword leg runs, and it needs alphanumeric query terms — a punctuation-only query matches
nothing. Switch to `hybrid` or rephrase.

**`/plan` finished but some tasks failed or were blocked.** Run `/task_status` to see per-task
status, retry count, and errors. A failed task blocks anything depending on it. Re-running `/plan`
with the same project resumes it and retries failed-or-crashed tasks (up to `max_retries`, 3 by
default).

**`/plan` never starts and instead resumes an old project.** There's an approved project in
`.coding-agent/tasks.db`. Finish or clear it (delete the DB) to plan something new.

**`/plan` tasks stall or fail the judge repeatedly.** The judge uses `llm.judge_model`, which must be
a valid model ID for the configured provider; a bad value makes every task fail verification. Also
raise `max_retries` only as a workaround — recurring judge failures usually mean the acceptance
criteria are unsatisfiable as written.
