import logging
from pathlib import Path

from coding_agent.config import config

# Set root logger to WARNING -> suppresses noisy third-party library logs (OpenAI, Google, httpcore etc.)
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

_file_handler: logging.FileHandler | None = None


def _resolve_log_file() -> Path:
    """Resolve the log path from config and ensure its directory exists."""
    logging_cfg = config.get("logging", {})
    logs_dir = Path(logging_cfg.get("logs_dir", ".coding-agent/logs"))
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir / logging_cfg.get("log_file", "coding-agent.log")


def _get_file_handler() -> logging.FileHandler:
    # Built lazily on first use so Path.cwd() resolves to the launched project,
    # not the package install location.
    global _file_handler
    if _file_handler is None:
        handler = logging.FileHandler(_resolve_log_file())
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
        )
        _file_handler = handler
    return _file_handler


def get_logger(name: str) -> logging.Logger:
    # Our own loggers run at DEBUG -> only third-party libraries are suppressed
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    handler = _get_file_handler()
    if handler not in logger.handlers:
        logger.addHandler(handler)

    return logger
