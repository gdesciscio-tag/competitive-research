from compresearch.models import DashboardResult, JobData, JobConfig


def test_dashboard_result_defaults():
    r = DashboardResult()
    assert r.html_path is None
    assert r.error is None


def test_jobdata_has_dashboard_field_defaulting_none():
    data = JobData(config=JobConfig(client_name="Acme Co", client_url="https://acme.com"))
    assert data.dashboard is None
