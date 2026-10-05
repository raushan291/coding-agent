from pathlib import Path

import yaml


def load_config() -> dict:
    """Load settings from config.yaml at the project root."""
    return yaml.safe_load((Path(__file__).parent / "config.yaml").read_text())


config = load_config()
