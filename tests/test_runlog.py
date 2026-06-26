# tests/test_runlog.py
import logging

from compresearch.runlog import job_log, remediation_hint


def test_job_log_writes_messages_to_run_log(tmp_path):
    with job_log(tmp_path):
        logging.getLogger("compresearch.test").warning("something happened")
    text = (tmp_path / "run.log").read_text(encoding="utf-8")
    assert "something happened" in text
    assert "WARNING" in text


def test_job_log_restores_logging_state(tmp_path):
    root = logging.getLogger()
    handlers_before = list(root.handlers)
    level_before = root.level
    with job_log(tmp_path):
        pass
    assert list(root.handlers) == handlers_before   # handler removed on exit
    assert root.level == level_before               # level restored


def test_job_log_is_idempotent_when_nested(tmp_path):
    root = logging.getLogger()
    with job_log(tmp_path):
        count_after_first = sum(
            1 for h in root.handlers
            if isinstance(h, logging.FileHandler)
            and getattr(h, "baseFilename", "").endswith("run.log")
        )
        with job_log(tmp_path):   # nested -> must not add a second handler
            count_after_nested = sum(
                1 for h in root.handlers
                if isinstance(h, logging.FileHandler)
                and getattr(h, "baseFilename", "").endswith("run.log")
            )
    assert count_after_first == 1
    assert count_after_nested == 1


def test_remediation_hint_maps_known_errors():
    assert "ANTHROPIC_API_KEY" in remediation_hint("ANTHROPIC_API_KEY must be set ...")
    assert "DATAFORSEO" in remediation_hint("DATAFORSEO_LOGIN missing")
    assert "Shared Drive" in remediation_hint("GOOGLE_SHARED_DRIVE_ID not configured")
    assert "playwright install" in remediation_hint("playwright is not installed")


def test_remediation_hint_none_for_unknown_or_empty():
    assert remediation_hint(None) is None
    assert remediation_hint("some unrelated failure") is None
