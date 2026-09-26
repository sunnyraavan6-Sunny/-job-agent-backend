"""
Tests the normalization logic of each adapter against mocked responses shaped
exactly like each API's real documented payload. This validates the parsing
code without needing outbound network access (which this sandbox doesn't have
to adzuna.com / greenhouse.io / lever.co / remoteok.com anyway).
"""
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, ".")

from app.services.job_sources import adzuna, greenhouse, lever, remoteok  # noqa: E402


def _mock_response(json_data, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


print("== adzuna adapter ==")
with patch("app.config.settings.adzuna_app_id", "test_id"), \
     patch("app.config.settings.adzuna_app_key", "test_key"), \
     patch("app.services.job_sources.adzuna.requests.get") as mock_get:
    mock_get.return_value = _mock_response({
        "results": [
            {
                "id": "1234567",
                "title": "Backend Engineer",
                "company": {"display_name": "Acme Corp"},
                "location": {"display_name": "Remote"},
                "description": "Build APIs...",
                "redirect_url": "https://adzuna.com/jobs/1234567",
                "salary_min": 90000.0,
                "salary_max": 130000.0,
            }
        ]
    })
    jobs, err = adzuna.search(["Backend Engineer"], ["Remote"])
    assert err is None, err
    assert len(jobs) == 1
    j = jobs[0]
    assert j.source == "adzuna" and j.external_id == "1234567"
    assert j.company == "Acme Corp" and j.salary_min == 90000 and j.salary_max == 130000
    print("OK  adzuna: parsed", j)

# not configured case
with patch("app.config.settings.adzuna_app_id", ""), patch("app.config.settings.adzuna_app_key", ""):
    jobs, err = adzuna.search(["Backend Engineer"], [])
    assert jobs == [] and err is not None
    print("OK  adzuna: correctly reports not-configured ->", err)


print("\n== remoteok adapter ==")
with patch("app.services.job_sources.remoteok.requests.get") as mock_get:
    mock_get.return_value = _mock_response([
        {"legal": "metadata row, should be skipped"},
        {
            "id": "999",
            "position": "Remote Backend Engineer",
            "company": "Beta Inc",
            "location": "Worldwide",
            "description": "...",
            "url": "https://remoteok.com/remote-jobs/999",
            "salary_min": 80000,
            "salary_max": 120000,
        },
        {
            "id": "1000",
            "position": "Marketing Manager",
            "company": "Gamma LLC",
        },
    ])
    jobs, err = remoteok.search(["backend engineer"])
    assert err is None
    assert len(jobs) == 1, f"expected filtering to keep only the matching title, got {jobs}"
    assert jobs[0].external_id == "999" and jobs[0].work_mode == "remote"
    print("OK  remoteok: filtered correctly ->", jobs[0])


print("\n== greenhouse adapter ==")
with patch("app.services.job_sources.greenhouse.requests.get") as mock_get:
    mock_get.return_value = _mock_response({
        "jobs": [
            {
                "id": 555,
                "title": "Senior Backend Engineer",
                "location": {"name": "Remote - US"},
                "content": "<p>Job description html</p>",
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/555",
            }
        ]
    })
    jobs, err = greenhouse.fetch_company_jobs("acme")
    assert err is None and len(jobs) == 1
    j = jobs[0]
    assert j.source == "greenhouse" and j.company == "acme" and j.work_mode == "remote"
    print("OK  greenhouse: parsed", j)


print("\n== lever adapter ==")
with patch("app.services.job_sources.lever.requests.get") as mock_get:
    mock_get.return_value = _mock_response([
        {
            "id": "abc-123",
            "text": "Platform Engineer",
            "categories": {"location": "Remote"},
            "descriptionPlain": "Plain text JD",
            "hostedUrl": "https://jobs.lever.co/beta/abc-123",
        }
    ])
    jobs, err = lever.fetch_company_jobs("beta")
    assert err is None and len(jobs) == 1
    j = jobs[0]
    assert j.source == "lever" and j.company == "beta" and j.work_mode == "remote"
    print("OK  lever: parsed", j)

print("\nALL ADAPTER UNIT TESTS PASSED")
