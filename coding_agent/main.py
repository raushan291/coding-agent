from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.prompt import Prompt

from coding_agent.agent.orchestrator import handle_query
from coding_agent.config import config
from coding_agent.context.indexers.factory import get_index_inspector, get_indexer
from coding_agent.llm.factory import get_embedder, get_llm
from coding_agent.observability.logger import get_logger

load_dotenv(Path(__file__).parent.parent / ".env")

console = Console()
logger = get_logger(__name__)


def get_or_create_index():
    repo_path = str(Path.cwd())
    logger.info(f"Checking index for: {repo_path}")
    console.print(f"[dim]Checking index for {repo_path}...[/dim]")
    return get_indexer()(repo_path)


def initialize():
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
    console.print("[green]✓ Ready[/green]\n")
    return llm, embedder, index


def run():
    logger.info("Starting Coding Agent")
    console.print("\n[bold blue]Coding Agent[/bold blue] — RAG-powered code assistant")

    llm, embedder, index = initialize()

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
            response = handle_query(question)
            console.print(response)
        elif user_input == "/show_semantic_index":
            logger.info("Showing semantic index")
            get_index_inspector()(index)
        else:
            logger.warning(f"Unknown command received: {user_input}")
            console.print("[yellow]Unknown command. Try:[/yellow]")
            console.print("  [bold]ask <question>[/bold] — ask a question")
            console.print(
                "  [bold]show_semantic_index[/bold]  — show all chunks in the semantic index"
            )


if __name__ == "__main__":
    run()
