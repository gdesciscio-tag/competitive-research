# compresearch/job_store.py
from __future__ import annotations

import re
from pathlib import Path

import yaml

from compresearch.models import JobConfig, JobData

DEFAULT_JOBS_DIR = Path("jobs")


def slugify(name: str) -> str:
    """Turn a client name into a filesystem-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug


def create_job(config: JobConfig, jobs_dir: Path = DEFAULT_JOBS_DIR) -> Path:
    """Create jobs/<slug>/ with job.yaml, data.json, and outputs/. Returns the job dir."""
    job_dir = Path(jobs_dir) / slugify(config.client_name)
    (job_dir / "outputs").mkdir(parents=True, exist_ok=True)
    (job_dir / "job.yaml").write_text(
        yaml.safe_dump(config.model_dump(), sort_keys=False), encoding="utf-8"
    )
    save_data(job_dir, JobData(config=config))
    return job_dir


def load_config(job_dir: Path) -> JobConfig:
    raw = yaml.safe_load((Path(job_dir) / "job.yaml").read_text(encoding="utf-8"))
    return JobConfig.model_validate(raw)


def load_data(job_dir: Path) -> JobData:
    text = (Path(job_dir) / "data.json").read_text(encoding="utf-8")
    return JobData.model_validate_json(text)


def save_data(job_dir: Path, data: JobData) -> None:
    (Path(job_dir) / "data.json").write_text(
        data.model_dump_json(indent=2), encoding="utf-8"
    )
