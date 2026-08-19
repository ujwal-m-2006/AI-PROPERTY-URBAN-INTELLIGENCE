"""RFC 7807 problem responses.

Missing data is a first-class, expected outcome in this system — not a 500.
Giving it a typed problem response means the frontend can render GREY
"data unavailable" states correctly instead of showing an error banner, which
is the difference between an honest gap and a broken feature.
"""

from __future__ import annotations

from fastapi import Request, status
from fastapi.responses import JSONResponse

PROBLEM_BASE = "https://gba-intel.local/problems"

HTTP_422 = 422  # spelled out: the Starlette constant name is in flux across versions


class ProblemError(Exception):
    """Base for typed API problems."""

    problem_type = "about:blank"
    title = "Error"
    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, detail: str, **extra: object) -> None:
        super().__init__(detail)
        self.detail = detail
        self.extra = extra


class DataUnavailable(ProblemError):
    """We do not hold this data and will not invent it."""

    problem_type = f"{PROBLEM_BASE}/data-unavailable"
    title = "Data unavailable"
    status_code = status.HTTP_404_NOT_FOUND


class SourceConflict(ProblemError):
    """Sources disagree; the caller gets both, not a resolution."""

    problem_type = f"{PROBLEM_BASE}/source-conflict"
    title = "Conflicting records detected"
    status_code = status.HTTP_409_CONFLICT


class LowConfidence(ProblemError):
    """A result exists but falls below the threshold for the request."""

    problem_type = f"{PROBLEM_BASE}/low-confidence"
    title = "Low-confidence result"
    status_code = HTTP_422


class OutsideCoverage(ProblemError):
    """The point lies outside Greater Bengaluru."""

    problem_type = f"{PROBLEM_BASE}/outside-coverage"
    title = "Outside Greater Bengaluru coverage"
    status_code = HTTP_422


class UnknownCity(ProblemError, KeyError):
    """A city we do not cover.

    Also a KeyError, because `cities.get` raised one long before this class
    existed and non-HTTP callers (pipelines, scripts) still catch that. What
    changes is the HTTP behaviour: asking for Mysuru used to escape every
    city-aware endpoint as an unhandled KeyError and surface as a 500 — the
    status that means "we broke", when the truth is "you asked for a city we
    do not have".
    """

    problem_type = f"{PROBLEM_BASE}/unknown-city"
    title = "City not covered"
    status_code = status.HTTP_400_BAD_REQUEST


class RecordNotAutomatable(ProblemError):
    """The caller asked for something only an OTP-gated portal can answer."""

    problem_type = f"{PROBLEM_BASE}/record-not-automatable"
    title = "Official record cannot be retrieved automatically"
    status_code = status.HTTP_501_NOT_IMPLEMENTED


async def problem_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ProblemError)
    body: dict[str, object] = {
        "type": exc.problem_type,
        "title": exc.title,
        "status": exc.status_code,
        "detail": exc.detail,
        "instance": str(request.url.path),
    }
    body.update(exc.extra)
    return JSONResponse(
        status_code=exc.status_code,
        content=body,
        media_type="application/problem+json",
    )
