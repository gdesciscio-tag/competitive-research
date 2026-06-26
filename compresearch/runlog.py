# compresearch/runlog.py
from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path

# Plain-language fixes for the credential/setup errors operators hit most often. Each
# entry is (substring to look for in the error, what the operator should do about it).
REMEDIATIONS: list[tuple[str, str]] = [
    ("ANTHROPIC_API_KEY", "set ANTHROPIC_API_KEY in .env"),
    ("DATAFORSEO", "set DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD in .env"),
    ("GOOGLE_SERVICE_ACCOUNT_JSON", "set GOOGLE_SERVICE_ACCOUNT_JSON in .env to your service-account JSON path"),
    ("GOOGLE_SHARE_EMAIL", "set GOOGLE_SHARE_EMAIL in .env"),
    ("GOOGLE_SHARED_DRIVE_ID", "set GOOGLE_SHARED_DRIVE_ID in .env (service accounts need a Shared Drive)"),
    ("playwright", "run once: .venv\\Scripts\\python -m playwright install chromium"),
]


def remediation_hint(error: str | None) -> str | None:
    """Map a step error to a one-line fix, or None if we have no specific advice."""
    if not error:
        return None
    lowered = error.lower()
    for marker, hint in REMEDIATIONS:
        if marker.lower() in lowered:
            return hint
    return None


@contextmanager
def job_log(job_dir: Path, level: int = logging.INFO):
    """Tee the existing `logging` output to jobs/<slug>/run.log for the duration of a run.

    Idempotent: if a handler for the same file is already attached (e.g. a per-step run
    nested inside run_job), this is a no-op so logs are not duplicated. Restores the prior
    root-logger level on exit so it doesn't leak into the rest of the process or the tests.
    """
    path = Path(job_dir) / "run.log"
    root = logging.getLogger()
    target = str(path.resolve())
    already = any(
        isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", None) == target
        for h in root.handlers
    )
    if already:
        yield path
        return

    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    prev_level = root.level
    if root.level == logging.NOTSET or root.level > level:
        root.setLevel(level)
    root.addHandler(handler)
    try:
        yield path
    finally:
        root.removeHandler(handler)
        handler.close()
        root.setLevel(prev_level)
