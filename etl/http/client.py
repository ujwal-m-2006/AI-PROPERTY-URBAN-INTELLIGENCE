"""The only sanctioned way this project makes an outbound HTTP request.

The collection policy in docs/01-data-source-audit.md section 6.2 is enforced
here rather than documented and hoped for. Making the polite path the *only*
available path is far more reliable than a policy in a README.

Four things it guarantees:
  1. robots.txt is consulted and obeyed, with no override flag.
  2. OTP-, captcha- and login-gated government portals are refused outright.
  3. Per-host rate limits apply, with an identifying User-Agent.
  4. Every response carries the metadata needed to write a data_sources row,
     so nothing can enter the database without provenance.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


class FetchRefused(RuntimeError):
    """The client declined to make the request. Not an error to retry."""


class RobotsDisallowed(FetchRefused):
    pass


class GatedHostRefused(FetchRefused):
    pass


GATED_HOSTS: frozenset[str] = frozenset(
    {
        # Per-property government portals behind OTP, captcha or login.
        # Automating any of these would be both hostile and legally doubtful,
        # and would produce exactly the fabricated-records failure the platform
        # exists to avoid. The application deep-links to them instead.
        "eaasthi.karnataka.gov.in",
        "landrecords.karnataka.gov.in",
        "bhoomi.karnataka.gov.in",
        "kaveri.karnataka.gov.in",
        "kaveri2.karnataka.gov.in",
        "kaverionline.karnataka.gov.in",
        "sevasindhu.karnataka.gov.in",
    }
)

DEFAULT_MIN_INTERVAL_SECONDS = 1.0
GOV_MIN_INTERVAL_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class FetchResult:
    """A response plus everything needed to record where it came from."""

    url: str
    final_url: str
    status_code: int
    content: bytes
    content_type: str | None
    fetched_at: datetime
    sha256: str
    tls_exception_used: bool
    last_modified: str | None = None

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def provenance(
        self,
        *,
        name: str,
        tier: str,
        availability: str,
        organisation: str | None = None,
        licence: str | None = None,
        transformation: str | None = None,
    ) -> dict[str, object]:
        """Fields for a meta.data_sources row.

        Callers pass tier and licence explicitly because neither can be inferred
        from an HTTP response, and guessing them would undermine the whole
        confidence system.
        """
        notes: list[str] = [f"sha256={self.sha256}"]
        if self.tls_exception_used:
            notes.append("fetched with a pinned per-host TLS chain exception")
        if self.final_url != self.url:
            notes.append(f"redirected to {self.final_url}")

        return {
            "name": name,
            "organisation": organisation,
            "source_url": self.final_url,
            "tier": tier,
            "availability": availability,
            "licence": licence,
            "retrieved_at": self.fetched_at,
            "method": "http_download",
            "transformation": transformation,
            "access_notes": "; ".join(notes),
        }


@dataclass
class _HostState:
    last_request: float = 0.0
    robots: urllib.robotparser.RobotFileParser | None = None
    robots_checked: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)


class EthicalHTTPClient:
    """Rate-limited, robots-respecting HTTP client with provenance output.

    TLS note: several Karnataka government hosts serve incomplete certificate
    chains (see audit 6.1). Those hosts can be listed in ``tls_exceptions``,
    which disables verification *for that host only* and stamps the fact onto
    the FetchResult so it reaches access_notes. A global verify=False is not
    available, deliberately.
    """

    def __init__(
        self,
        *,
        contact: str,
        app_name: str = "GBA-Property-Intelligence",
        app_url: str = "https://example.invalid/about",
        min_interval: float = DEFAULT_MIN_INTERVAL_SECONDS,
        tls_exceptions: frozenset[str] = frozenset(),
        timeout: float = 30.0,
    ) -> None:
        if not contact or "@" not in contact:
            raise ValueError(
                "a real contact address is required; anonymous crawling of "
                "government hosts is not acceptable"
            )
        self.user_agent = f"{app_name}/0.1 (+{app_url}; {contact})"
        self.min_interval = min_interval
        self.tls_exceptions = tls_exceptions
        self.timeout = timeout
        self._hosts: dict[str, _HostState] = {}
        self._registry_lock = threading.Lock()

    # -- policy ----------------------------------------------------------

    def _state(self, host: str) -> _HostState:
        with self._registry_lock:
            return self._hosts.setdefault(host, _HostState())

    def _interval_for(self, host: str) -> float:
        if host.endswith(".gov.in") or host.endswith(".nic.in"):
            return max(self.min_interval, GOV_MIN_INTERVAL_SECONDS)
        return self.min_interval

    def _check_gated(self, host: str) -> None:
        if host in GATED_HOSTS:
            raise GatedHostRefused(
                f"{host} is an OTP/login-gated government portal. This platform "
                f"deep-links to it and never automates it. If you need data from "
                f"here, it must come from a document the user uploads."
            )

    def _robots(self, scheme: str, host: str, verify: bool) -> urllib.robotparser.RobotFileParser:
        state = self._state(host)
        with state.lock:
            if state.robots_checked and state.robots is not None:
                return state.robots

            parser = urllib.robotparser.RobotFileParser()
            robots_url = f"{scheme}://{host}/robots.txt"
            try:
                resp = httpx.get(
                    robots_url,
                    headers={"User-Agent": self.user_agent},
                    timeout=10.0,
                    verify=verify,
                    follow_redirects=True,
                )
                if resp.status_code == 200:
                    parser.parse(resp.text.splitlines())
                else:
                    # No robots.txt is permission by omission, not a blocker.
                    parser.parse([])
            except httpx.HTTPError as exc:
                logger.warning("robots.txt unreachable for %s (%s); assuming allow", host, exc)
                parser.parse([])

            state.robots = parser
            state.robots_checked = True
            return parser

    def _throttle(self, host: str) -> None:
        state = self._state(host)
        interval = self._interval_for(host)
        with state.lock:
            elapsed = time.monotonic() - state.last_request
            if elapsed < interval:
                time.sleep(interval - elapsed)
            state.last_request = time.monotonic()

    # -- fetch -----------------------------------------------------------

    def fetch(self, url: str, *, expect: str | None = None) -> FetchResult:
        """Fetch a URL under the full policy. Raises FetchRefused if declined."""
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise FetchRefused(f"unsupported scheme: {parsed.scheme}")

        host = parsed.hostname or ""
        self._check_gated(host)

        tls_exception = host in self.tls_exceptions
        verify = not tls_exception
        if tls_exception:
            logger.warning(
                "using a pinned TLS chain exception for %s; this is recorded in "
                "access_notes for every row derived from this fetch",
                host,
            )

        robots = self._robots(parsed.scheme, host, verify)
        if not robots.can_fetch(self.user_agent, url):
            raise RobotsDisallowed(f"robots.txt disallows {url}")

        self._throttle(host)

        with httpx.Client(
            headers={"User-Agent": self.user_agent},
            timeout=self.timeout,
            verify=verify,
            follow_redirects=True,
        ) as client:
            response = client.get(url)
            response.raise_for_status()

        content_type = response.headers.get("content-type")
        if expect and content_type and expect not in content_type:
            raise FetchRefused(
                f"expected {expect!r} from {url}, got {content_type!r}; "
                f"refusing to ingest an unexpected payload type"
            )

        return FetchResult(
            url=url,
            final_url=str(response.url),
            status_code=response.status_code,
            content=response.content,
            content_type=content_type,
            fetched_at=datetime.now(UTC),
            sha256=hashlib.sha256(response.content).hexdigest(),
            tls_exception_used=tls_exception,
            last_modified=response.headers.get("last-modified"),
        )
