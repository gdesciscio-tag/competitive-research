# compresearch/branding.py
from __future__ import annotations

import json
from pathlib import Path

from compresearch.models import Branding

DEFAULT_BRANDING_PATH = Path(__file__).parent / "branding.json"


def load_branding(path: Path | None = None) -> Branding:
    """Load the branding config, merging an optional JSON override over the defaults.

    If `path` is None, looks for compresearch/branding.json; if that's absent, returns
    the built-in defaults. Unknown keys in the override are ignored by pydantic.
    """
    path = Path(path) if path is not None else DEFAULT_BRANDING_PATH
    if not path.exists():
        return Branding()
    override = json.loads(path.read_text(encoding="utf-8"))
    return Branding(**{**Branding().model_dump(), **override})
