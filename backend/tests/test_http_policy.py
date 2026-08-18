"""Policy tests for the ethical HTTP client.

These make no network calls. They assert that the refusals happen before any
request is attempted — which is the point of putting the policy in the client
rather than in a document.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from etl.http.client import (  # noqa: E402
    GATED_HOSTS,
    EthicalHTTPClient,
    FetchRefused,
    FetchResult,
    GatedHostRefused,
)


@pytest.fixture
def client() -> EthicalHTTPClient:
    return EthicalHTTPClient(contact="student@example.com")


def test_anonymous_client_is_rejected() -> None:
    with pytest.raises(ValueError, match="real contact address"):
        EthicalHTTPClient(contact="")


@pytest.mark.parametrize("host", sorted(GATED_HOSTS))
def test_gated_government_portals_are_refused(
    client: EthicalHTTPClient, host: str
) -> None:
    with pytest.raises(GatedHostRefused, match="deep-links"):
        client.fetch(f"https://{host}/some/record")


def test_kaveri_and_eaasthi_are_in_the_gated_list() -> None:
    # The two that matter most: property registration and e-Khata.
    assert "kaveri.karnataka.gov.in" in GATED_HOSTS
    assert "eaasthi.karnataka.gov.in" in GATED_HOSTS


def test_non_http_schemes_are_refused(client: EthicalHTTPClient) -> None:
    with pytest.raises(FetchRefused, match="unsupported scheme"):
        client.fetch("ftp://example.com/data.zip")


def test_government_hosts_get_a_slower_rate_limit(client: EthicalHTTPClient) -> None:
    assert client._interval_for("bbmp.gov.in") >= 2.0
    assert client._interval_for("indiacode.nic.in") >= 2.0
    assert client._interval_for("data.opencity.in") == 1.0


def test_user_agent_identifies_the_project_and_a_contact() -> None:
    c = EthicalHTTPClient(contact="student@example.com")
    assert "student@example.com" in c.user_agent
    assert "GBA-Property-Intelligence" in c.user_agent


# --- provenance output ---------------------------------------------------


def _result(**kw: object) -> FetchResult:
    base = dict(
        url="https://data.opencity.in/x.kml",
        final_url="https://data.opencity.in/x.kml",
        status_code=200,
        content=b"<kml/>",
        content_type="application/vnd.google-earth.kml+xml",
        fetched_at=datetime.now(UTC),
        sha256="abc123",
        tls_exception_used=False,
    )
    base.update(kw)
    return FetchResult(**base)  # type: ignore[arg-type]


def test_provenance_requires_explicit_tier_and_records_the_hash() -> None:
    prov = _result().provenance(
        name="GBA Final Wards 2025",
        tier="T2",
        availability="DOWNLOAD",
        licence="Public domain",
    )
    assert prov["tier"] == "T2"
    assert prov["method"] == "http_download"
    assert "sha256=abc123" in str(prov["access_notes"])


def test_tls_exception_is_recorded_in_access_notes() -> None:
    prov = _result(tls_exception_used=True).provenance(
        name="x", tier="T1", availability="DOWNLOAD"
    )
    assert "TLS chain exception" in str(prov["access_notes"])


def test_redirects_are_recorded() -> None:
    prov = _result(final_url="https://data.opencity.in/y.kml").provenance(
        name="x", tier="T2", availability="DOWNLOAD"
    )
    assert "redirected to" in str(prov["access_notes"])
    assert prov["source_url"] == "https://data.opencity.in/y.kml"
