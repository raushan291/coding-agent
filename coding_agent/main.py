import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from rich.console import Console
from rich.prompt import Prompt

from coding_agent.agent.factory import build_agent
from coding_agent.agent.orchestrator import handle_query
from coding_agent.config import config
from coding_agent.context.indexers.factory import get_index_inspector, get_indexer
from coding_agent.llm.factory import get_embedder, get_llm
from coding_agent.memory.session import get_current_session, new_session, switch_session
from coding_agent.memory.short_term import get_checkpointer_db_path
from coding_agent.observability.logger import get_logger

load_dotenv(Path(__file__).parent.parent / ".env")

console = Console()
logger = get_logger(__name__)

logging.getLogger("langchain_google_genai._function_utils").setLevel(logging.ERROR)


def get_or_create_index():
    repo_path = str(Path.cwd())
    logger.info(f"Checking index for: {repo_path}")
    console.print(f"[dim]Checking index for {repo_path}...[/dim]")
    return get_indexer()(repo_path)


async def initialize(checkpointer):
    """Bootstrap LLM, embedder, and index before the REPL starts."""
    llm = get_llm()
    embedder = get_embedder()
    console.print(
        f"[dim]LLM: {config['llm']['provider']} / {config['llm']['model']}[/dim]"
    )
    console.print(
        f"[dim]Embedder: {config['embeddings']['provider']} / {config['embeddings']['model']}[/dim]"
    )

    index = get_or_create_index()
    agent = await build_agent(checkpointer)
    session_id = get_current_session()
    console.print(f"[dim]Session: {session_id}[/dim]")
    console.print("[green]✓ Ready[/green]\n")
    return llm, embedder, index, agent, session_id


async def _run_async():
    logger.info("Starting Coding Agent")
    console.print("\n[bold blue]Coding Agent[/bold blue] — RAG-powered code assistant")

    async with AsyncSqliteSaver.from_conn_string(
        get_checkpointer_db_path()
    ) as checkpointer:
        llm, embedder, index, agent, session_id = await initialize(checkpointer)

        console.print("Type [bold]'/exit'[/bold] or [bold]'/quit'[/bold] to quit\n")

        while True:
            user_input = Prompt.ask("[bold green]>[/bold green]")

            if not user_input.strip():
                continue
            if user_input.lower() in ("/exit", "/quit"):
                logger.info("Shutting down")
                console.print("[dim]Goodbye![/dim]")
                break
            elif user_input.startswith("/ask "):
                question = user_input.removeprefix("/ask ").strip()
                logger.info(f"Ask command received: {question}")
                console.print(f"[dim]Searching for: {question}...[/dim]")
                response = await handle_query(agent, question, session_id)
                console.print(response)
            elif user_input == "/new_session":
                session_id = new_session()
                console.print(f"[green]New session started: {session_id}[/green]")
            elif user_input.startswith("/switch "):
                target = user_input.removeprefix("/switch ").strip()
                session_id = switch_session(target)
                console.print(f"[green]Switched to session: {session_id}[/green]")
            elif user_input == "/session":
                console.print(f"[dim]Current session: {session_id}[/dim]")
            elif user_input == "/show_index":
                logger.info("Showing index")
                get_index_inspector()(index)
            else:
                logger.warning(f"Unknown command received: {user_input}")
                console.print("[yellow]Unknown command. Try:[/yellow]")
                console.print(
                    "  [bold]/ask <question>[/bold]          — ask a question about the codebase"
                )
                console.print(
                    "  [bold]/show_index[/bold]              — show all chunks in the index"
                )
                console.print(
                    "  [bold]/new_session[/bold]             — start a fresh conversation"
                )
                console.print(
                    "  [bold]/switch <session_id>[/bold]     — resume a past session"
                )
                console.print(
                    "  [bold]/session[/bold]                 — show current session id"
                )


def run():
    asyncio.run(_run_async())


if __name__ == "__main__":
    run()
