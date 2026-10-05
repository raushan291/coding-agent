import chromadb

from coding_agent.config import config
from coding_agent.context.indexers.code_parser import get_source_files, parse_file
from coding_agent.llm.factory import get_embedder
from coding_agent.observability.logger import get_logger

logger = get_logger(__name__)


def index_codebase(repo_path: str) -> chromadb.Collection:
    """
    Parse all Python files in repo_path, embed each chunk and store in ChromaDB.
    Returns the ChromaDB collection for use by the retriever.
    """
    embedder = get_embedder()
    chroma_client = chromadb.PersistentClient(path=config["chromadb"]["persist_dir"])
    collection = chroma_client.get_or_create_collection(
        name=config["chromadb"]["collection_name"]
    )

    logger.info(f"Starting semantic indexing of {repo_path}")

    files = get_source_files(repo_path)

    for filepath in files:
        try:
            chunks = parse_file(filepath)
        except (SyntaxError, ValueError) as e:
            logger.error(f"Skipping {filepath}: {e}")
            continue

        for chunk in chunks:
            embedding = embedder.embed_query(chunk.content)

            # Unique ID for each chunk -> source + name + line prevents duplicates on re-index
            doc_id = f"{chunk.source}::{chunk.name}::{chunk.start_line}"

            collection.upsert(
                ids=[doc_id],
                embeddings=[embedding],
                documents=[chunk.content],
                metadatas=[
                    {
                        "source": chunk.source,
                        "name": chunk.name,
                        "type": chunk.type,
                        "start_line": chunk.start_line,
                        "end_line": chunk.end_line,
                    }
                ],
            )
            logger.debug(f"  Indexed {chunk.type} '{chunk.name}' from {filepath}")

    logger.info(f"Semantic indexing complete. Total chunks: {collection.count()}")
    return collection
