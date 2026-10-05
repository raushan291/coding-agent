import logging

# Set root logger to WARNING -> suppresses noisy third-party library logs (OpenAI, Google, httpcore etc.)
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

file_handler = logging.FileHandler("coding-agent.log")
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(
    logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
)


def get_logger(name: str) -> logging.Logger:
    # Our own loggers run at DEBUG -> only third-party libraries are suppressed
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    if not any(isinstance(h, logging.FileHandler) for h in logger.handlers):
        logger.addHandler(file_handler)

    return logger
