"""Endpoint verification tests.

The important property is that a host blocked by a local network policy is not
reported as a broken endpoint. Getting that wrong would turn a restricted
environment into a hundred spurious bug reports.
"""

from __future__ import annotations

import pandas as pd
import pytest
import requests

from smml.util.verify import STATUS_MEANING, ProbeResult, Status, probe, summarize


class FakeResponse:
    def __init__(self, status_code, url):
        self.status_code = status_code
        self.url = url

    def close(self):
        pass


class FakeSession:
    def __init__(self, status_code=200, final_url=None, raises=None):
        self.status_code = status_code
        self.final_url = final_url
        self.raises = raises
        self.headers = {}

    def head(self, url, **kwargs):
        if self.raises:
            raise self.raises
        return FakeResponse(self.status_code, self.final_url or url)

    def get(self, url, **kwargs):
        return self.head(url, **kwargs)


@pytest.mark.parametrize(
    ("code", "expected", "needs_fix"),
    [
        (200, Status.ALIVE, False),
        (204, Status.ALIVE, False),
        (301, Status.REDIRECTED, True),
        (404, Status.NOT_FOUND, True),
        (410, Status.NOT_FOUND, True),
        (401, Status.AUTH_REQUIRED, False),
        (403, Status.FORBIDDEN, False),
        (429, Status.RATE_LIMITED, False),
        (500, Status.SERVER_ERROR, False),
    ],
)
def test_status_mapping(code, expected, needs_fix):
    result = probe("https://example.org/x", "x", session=FakeSession(code))
    assert result.status == expected
    assert result.needs_fix is needs_fix


def test_a_redirect_is_reported_with_its_target():
    """A moved endpoint is the most common failure and the easiest to fix."""
    result = probe("https://old.example.org/api", "x",
                   session=FakeSession(200, final_url="https://new.example.org/api"))
    assert result.status == Status.REDIRECTED
    assert result.final_url == "https://new.example.org/api"
    assert result.needs_fix


def test_a_proxy_block_is_not_reported_as_a_broken_endpoint():
    """Otherwise a restricted network turns into a hundred spurious bug reports."""
    result = probe("https://example.org/x", "x",
                   session=FakeSession(raises=requests.exceptions.ProxyError("denied")))
    assert result.status == Status.BLOCKED_BY_POLICY
    assert not result.needs_fix


def test_an_unreachable_host_does_need_a_look():
    result = probe("https://example.org/x", "x",
                   session=FakeSession(raises=requests.exceptions.ConnectionError("no route")))
    assert result.status == Status.UNREACHABLE
    assert result.needs_fix


def test_a_tls_failure_is_recorded_with_its_reason():
    result = probe("https://example.org/x", "x",
                   session=FakeSession(raises=requests.exceptions.SSLError("bad cert")))
    assert result.status == Status.UNREACHABLE
    assert "TLS" in result.detail


@pytest.mark.parametrize("url", ["", "   ", "unknown", "n/a"])
def test_an_absent_url_is_skipped_not_failed(url):
    result = probe(url, "x")
    assert result.status == Status.SKIPPED
    assert not result.needs_fix


def test_a_head_refusal_falls_back_to_a_ranged_get():
    """Plenty of APIs reject HEAD and answer GET perfectly well."""

    class HeadRefusing(FakeSession):
        def __init__(self):
            super().__init__()
            self.head_calls = 0

        def head(self, url, **kwargs):
            self.head_calls += 1
            return FakeResponse(405, url)

        def get(self, url, **kwargs):
            return FakeResponse(200, url)

    session = HeadRefusing()
    result = probe("https://example.org/x", "x", session=session)
    assert session.head_calls == 1
    assert result.status == Status.ALIVE


def test_every_status_has_a_documented_meaning():
    """The report is meant to be handed back for repair, so each row has to say
    what it means without a second round of investigation."""
    for status in (Status.ALIVE, Status.REDIRECTED, Status.NOT_FOUND, Status.FORBIDDEN,
                   Status.AUTH_REQUIRED, Status.RATE_LIMITED, Status.SERVER_ERROR,
                   Status.UNREACHABLE, Status.BLOCKED_BY_POLICY):
        meaning, _ = STATUS_MEANING[status]
        assert len(meaning) > 10


def test_result_row_carries_what_a_fix_needs():
    row = ProbeResult("soilgrids", "https://x/y", Status.NOT_FOUND, http_code=404).as_row()
    for key in ("short_id", "status", "http_code", "url", "needs_fix", "meaning"):
        assert key in row


def test_summary_counts_by_status():
    report = pd.DataFrame([
        {"status": Status.ALIVE}, {"status": Status.ALIVE},
        {"status": Status.NOT_FOUND},
    ])
    summary = summarize(report)
    assert set(summary["status"]) == {Status.ALIVE, Status.NOT_FOUND}
    assert summary.loc[summary["status"] == Status.ALIVE, "n"].iloc[0] == 2
    assert summary["pct"].sum() == pytest.approx(100.0)


def test_summary_on_an_empty_report():
    assert summarize(pd.DataFrame()).empty
