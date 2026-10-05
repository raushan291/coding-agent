from coding_agent.config import config
from coding_agent.observability.logger import get_logger

logger = get_logger(__name__)


def get_retriever():
    """Return the right retrieve function based on vector_store in config."""
    vector_store = config["vector_store"]["provider"]
    logger.info(f"Using vector store for retrieval: {vector_store}")

    if vector_store == "qdrant":
        from .semantic_qdrant import retrieve
    else:
        from .semantic_chroma import retrieve

    return retrieve
