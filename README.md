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
- **Runs on your machine.** The vector store is local (ChromaDB on disk); your code is never sent
  anywhere except as embeddings to the embedder you configure.

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


#Langsmith
LANGSMITH_TRACING=false
LANGSMITH_API_KEY=your-key-here
```

Only the key for your configured provider is needed. One `.env` in this repo's root is enough for
every project — `load_dotenv()` resolves relative to the package, not the working directory.

**3. Run it**

The agent indexes your **current working directory**, so `cd` into the repo you want to ask
questions about:

```bash
cd /path/to/your/project
coding-agent
```

Each project you run it in gets its own `.chromadb/` index, so switching projects just means
switching directories.

> **First run in a project takes a while.** The embedding model downloads on first use, and every
> chunk is embedded individually — indexing a mid-sized repo can take several minutes. The result
> is cached in that project's `.chromadb/`, so subsequent starts there are fast.

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

All settings live in `coding_agent/config.yaml`. Environment variables are used only for API keys.

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

embeddings:
  provider: huggingface
  model: sentence-transformers/all-MiniLM-L6-v2

chromadb:
  persist_dir: .chromadb/
  collection_name: codebase
```

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
> the old model and search results will be nonsense — delete `.chromadb/` and re-index.

### `chromadb`

| Key | Default | Purpose |
|---|---|---|
| `persist_dir` | `.chromadb/` | Where the vector store is written |
| `collection_name` | `codebase` | ChromaDB collection holding the chunks |

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
embed each chunk ─────────────► ChromaDB (persistent, on disk)
    │
    ▼
your question ──► agent ──► search_codebase tool ──► top-5 chunks ──► answer
```

The agent is required to call `search_codebase` before answering, and is instructed to say so
explicitly if the answer isn't in the codebase.

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
│   │   └── semantic_chroma.py       # embed + store chunks
│   └── retrievers/
│       └── semantic_chroma.py       # embed query + top-k search
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

Chunk IDs are `source::name::start_line`, so re-indexing updates existing chunks instead of
duplicating them.

**Skipped directories:** `.venv`, `venv`, `__pycache__`, `.git`, `node_modules`, `dist`, `build`.

**Logging.** Each module gets its own logger at `DEBUG`, writing to `coding-agent.log` in the
current working directory — so each project you query accumulates its own log. The root logger
stays at `WARNING` so third-party libraries (OpenAI, Google, httpcore) don't flood the file.

---

## Troubleshooting

**Search results look unrelated to the question.** The embedder changed since indexing — delete
that project's `.chromadb/` and restart to rebuild.

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
in the directory you're running from and isn't being cleaned up.
