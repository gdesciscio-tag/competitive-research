# compresearch/settings.py
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()  # loads .env from the working directory if present


def get_secret(key: str) -> str | None:
    """Return a secret/config value from the environment, or None if unset."""
    return os.environ.get(key)
