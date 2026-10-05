from coding_agent.config import config
from coding_agent.observability.logger import get_logger

logger = get_logger(__name__)


def get_llm():
    """Return the right LangChain LLM based on config."""
    provider = config["llm"]["provider"]
    model = config["llm"]["model"]
    logger.info(f"Using LLM provider: {provider}, model: {model}")

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model, temperature=config["llm"].get("temperature", 0.0)
        )

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model, temperature=config["llm"].get("temperature", 0.0)
        )

    if provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model, temperature=config["llm"].get("temperature", 0.0)
        )

    else:
        raise ValueError(
            f"Unsupported LLM provider: {provider}\nSupported providers: 'anthropic', 'openai', 'google'."
        )


def get_embedder():
    """Return the right LangChain embedder based on config."""
    provider = config["embeddings"]["provider"]
    model = config["embeddings"]["model"]

    logger.info(f"Using embeddings provider: {provider}, model: {model}")

    if provider == "anthropic":
        from langchain_anthropic import AnthropicEmbeddings

        return AnthropicEmbeddings(model=model)

    if provider == "openai":
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(model=model)

    if provider == "google":
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        return GoogleGenerativeAIEmbeddings(model=model)

    if provider == "huggingface":
        from langchain_huggingface import HuggingFaceEmbeddings

        return HuggingFaceEmbeddings(model_name=model)
    else:
        raise ValueError(
            f"Unsupported embeddings provider: {provider}\nSupported providers: 'openai', 'huggingface', 'anthropic', 'google'."
        )
