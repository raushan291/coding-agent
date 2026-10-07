# Coding Agent

A RAG-powered code assistant. It indexes your codebase into a vector store, then answers
questions about it through a LangChain tool-calling agent that can search the code as it
reasons.

```
> /ask how does the retriever load its embedder?
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
- **Runs on your machine.** With the default ChromaDB store your code never leaves the disk
  index; the only outbound call is the embedder you configure. Qdrant is the exception — it sends
  chunks wherever your Qdrant instance lives.

---

## Requirements

- Python `>=3.12,<4.0`
- [pipx](https://pipx.pypa.io/installation/) (recommended) or [Poetry](https://python-poetry.org/docs/#installation)
- An API key for whichever LLM provider you configure

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


# ChromaDB
CHROMA_PERSIST_DIR=.chromadb/
CHROMA_COLLECTION=codebase
EMBEDDING_MODEL=text-embedding-3-small


# Qdrant (only needed if vector_store.provider is qdrant)
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=your-key-here


# Langsmith
LANGSMITH_TRACING=false
LANGSMITH_API_KEY=your-key-here
```

Only the key for your configured provider is needed. One `.env` in this repo's root is enough for
every project — the path is resolved from the installed package, not the working directory, so you
can launch the agent from any directory. See the note below the config section if you're using a
non-editable install.

**3. Run it**

The agent indexes your **current working directory**, so `cd` into the repo you want to ask
questions about:

```bash
cd /path/to/your/project
coding-agent
```

With the default ChromaDB store, each project you run it in gets its own `.chromadb/` index, so
switching projects just means switching directories.

> **First run in a project takes a while.** The embedding model downloads on first use, and every
> chunk is embedded individually — indexing a mid-sized repo can take several minutes. The result
> is cached in that project's `.chromadb/`, so subsequent starts there are fast.

> **Qdrant is not per-project.** With `vector_store.provider: qdrant` the collection is a single
> shared one named by `qdrant.collection_name` — it is not scoped to the directory you launched
> from. See the `qdrant` config section below before pointing it at more than one repo.

---

## Commands

| Command | What it does |
|---|---|
| `/ask <question>` | Search the codebase and answer the question |
| `/show_semantic_index` | Print every chunk in the index with its metadata and embedding |
| `/exit` or `/quit` | Quit |

Anything else prints the list of available commands.

---

## Configuration

All settings live in `coding_agent/config.yaml`. Environment variables cover credentials and
connection details only — provider API keys, plus `QDRANT_URL` / `QDRANT_API_KEY` when using
Qdrant.

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
  provider: google        # openai | anthropic | google
  model: gemini-2.5-flash
  temperature: 0.0

rag:
  mode: hybrid           # semantic | hybrid

embeddings:
  provider: huggingface
  model: sentence-transformers/all-MiniLM-L6-v2

vector_store:
  provider: chromadb      # chromadb | qdrant
  retrieval_mode: hybrid  # dense | sparse | hybrid

chromadb:
  persist_dir: .chromadb/
  collection_name: codebase

qdrant:
  collection_name: codebase
```

> **The `.env` location follows the same rule as `config.yaml`.** It is resolved from the installed
> package, so with a non-editable install the agent looks for `.env` inside the virtualenv rather
> than this repo. Use `pipx install --editable .` if you want to keep keys here.

### `llm`

| Key | Accepts |
|---|---|
| `provider` | `openai`, `anthropic`, `google` |
| `model` | Any model name your provider supports |
| `temperature` | Float, `0.0` for deterministic answers |

### `embeddings`

| Key | Accepts |
|---|---|
| `provider` | `openai`, `anthropic`, `google`, `huggingface` |
| `model` | Provider-specific model name |

> **The embedder must stay the same between runs.** Indexing and retrieval both call
> `get_embedder()`. If you change this model after indexing, existing chunks were embedded with
> the old model and search results will be nonsense — drop the existing index and re-index (for
> ChromaDB, delete `.chromadb/`; for Qdrant, delete the collection).

### `rag`

| Key | Default | Accepts | Purpose |
|---|---|---|---|
| `mode` | `hybrid` | `semantic`, `hybrid` | Use pure vector search, or vector + keyword search |

`semantic` always searches embeddings only. `hybrid` adds a keyword (BM25) leg — see
[Hybrid retrieval](#hybrid-retrieval) for how each backend implements it.

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
| `persist_dir` | `.chromadb/` | Where the vector store is written |
| `collection_name` | `codebase` | ChromaDB collection holding the chunks |

Local, embedded, and per-directory — the default for everyday use.

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
> isolates itself under each directory's `.chromadb/`.

Unlike ChromaDB there is no local `persist_dir` — the index lives on the Qdrant server, and
"clearing" it means dropping the collection.

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
embed each chunk ─────────────► configured vector store
                                 (ChromaDB on disk, or Qdrant)

your question ──► agent ──► search_codebase tool
                               │
                               ├─ dense leg ────► vector store
                               ├─ keyword leg ──► BM25 (ChromaDB) / sparse vectors (Qdrant)
                               ▼
                          reciprocal rank fusion
                               │
                               ▼
                        top-5 chunks ──► answer
```

The agent is required to call `search_codebase` before answering, and is instructed to say so
explicitly if the answer isn't in the codebase. That tool resolves a retriever through
`context/retrievers/factory.py` on every call, so the backend and the search mode are both chosen
from config at query time rather than fixed at import.

---

## Project layout

```
coding_agent/
├── main.py                          # REPL, bootstrap, index loading
├── config.py                        # loads config.yaml
├── config.yaml                      # all settings
├── agent/
│   ├── factory.py                   # builds the LangChain agent + system prompt
│   ├── orchestrator.py              # handle_query() entry point
│   └── tools.py                     # search_codebase tool
├── context/
│   ├── indexers/
│   │   ├── code_parser.py           # tree-sitter parsing + chunking
│   │   ├── factory.py               # picks the indexer / inspector for the backend
│   │   ├── hybrid_qdrant.py         # dense + sparse vectors (Qdrant, hybrid mode)
│   │   ├── semantic_chroma.py       # embed + store chunks (ChromaDB)
│   │   └── semantic_qdrant.py       # embed + store chunks (Qdrant)
│   └── retrievers/
│       ├── factory.py               # picks the retriever for backend + search mode
│       ├── hybrid_chroma.py         # dense + BM25 fused in-process (ChromaDB)
│       ├── hybrid_qdrant.py         # dense + sparse fused server-side (Qdrant)
│       ├── semantic_chroma.py       # embed query + top-k search (ChromaDB)
│       └── semantic_qdrant.py       # embed query + top-k search (Qdrant)
├── llm/
│   └── factory.py                   # provider switching for LLM and embedder
└── observability/
    └── logger.py                    # per-module loggers -> coding-agent.log
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

On ChromaDB, chunk IDs are `source::name::start_line`, so re-indexing updates existing chunks
instead of duplicating them. Qdrant relies on LangChain-generated IDs instead.

**Both indexers skip work when the store already has data** — ChromaDB checks `collection.count()`,
Qdrant checks the collection's point count. This avoids duplicate chunks on a second run, but it
also means neither picks up edits to code you've already indexed. To re-index after changing code,
drop the index: delete `.chromadb/`, or delete the Qdrant collection.

**Hybrid retrieval is the shipped default.** `rag.mode: hybrid` means ChromaDB queries go through
`hybrid_chroma.retrieve`. Its BM25 index is built once per process, on the first query, and reused
for the rest of the session — safe because indexing only runs at startup, so the stored documents
cannot change underneath it. Rebuilding `.chromadb/` while the CLI is running therefore isn't seen
until you restart. Qdrant's hybrid path builds no local index; `fastembed` handles the sparse side.

**Skipped directories:** `.venv`, `venv`, `__pycache__`, `.git`, `node_modules`, `dist`, `build`.

**Logging.** Each module gets its own logger at `DEBUG`, writing to `coding-agent.log` in the
current working directory — so each project you query accumulates its own log. The root logger
stays at `WARNING` so third-party libraries (OpenAI, Google, httpcore) don't flood the file.

---

## Troubleshooting

**Search results look unrelated to the question.** The embedder changed since indexing — drop the
existing index and restart to rebuild (`.chromadb/`, or the Qdrant collection).

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
`openai`, `anthropic`, `google`.

**Config edits have no effect.** You're editing the repo's `config.yaml` but running a non-editable
install, which reads the copy inside the virtualenv. Reinstall with `pipx install --editable .`.

**Authentication error on startup.** Your `.env` key doesn't match the configured provider. The key
is read from this repo's root `.env` regardless of where you launched from.

**Indexing seems stuck.** Check `coding-agent.log` in the directory you launched from — every
indexed chunk is logged at `DEBUG`.

**A project re-indexes every time.** ChromaDB found no existing index. Confirm `.chromadb/` exists
in the directory you're running from and isn't being cleaned up. (On Qdrant this would show up
instead as an index that never gets written — see "Qdrant errors" above.)

**Edits to indexed code are ignored.** Expected: both indexers skip when the store already holds
data. Drop the index to pick up your changes.

**The first `/ask` takes several seconds, the rest are fast.** The BM25 index over the whole
collection is built on the first hybrid query and cached for the session. The build is logged at
`INFO` in `coding-agent.log`.

**A term I know is in the code returns nothing.** With `vector_store.retrieval_mode: sparse` only
the keyword leg runs, and it needs alphanumeric query terms — a punctuation-only query matches
nothing. Switch to `hybrid` or rephrase. If it's already `hybrid`, check the chunk is actually
indexed; both indexers skip when the store already holds data.
