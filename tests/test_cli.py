# tests/test_cli.py
from compresearch.cli import run_from_args
from compresearch.job_store import load_data

CLIENT_MAP = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://acme.com/blog/a</loc></url>
</urlset>"""


def make_fetch(pages):
    def fetch(url):
        if url not in pages:
            raise FileNotFoundError(url)
        return pages[url]
    return fetch


def test_run_from_args_creates_job_and_runs_sitemap(tmp_path):
    fetch = make_fetch({
        "https://acme.com/robots.txt": b"Sitemap: https://acme.com/sitemap.xml\n",
        "https://acme.com/sitemap.xml": CLIENT_MAP,
    })
    job_dir = run_from_args(
        [
            "sitemap",
            "--client-name", "Acme Co",
            "--client-url", "https://acme.com",
            "--competitors", "",
            "--jobs-dir", str(tmp_path),
        ],
        fetch=fetch,
    )
    assert job_dir == tmp_path / "acme-co"
    data = load_data(job_dir)
    assert data.sitemap.client.total_urls == 1
