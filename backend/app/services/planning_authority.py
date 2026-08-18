"""Which authority grants planning permission for a point.

Audit task R5 established that **no public GIS layer of planning-authority
boundaries exists** — BMRDA publishes PDF jurisdiction maps only. So this
project has always returned `planning_authority` as UNAVAILABLE, on the grounds
that inferring it from a locality name would be a guess.

That reasoning is still right for the region at large. But it was applied too
widely. Inside a city corporation's limits the answer is not an inference from
geography at all — it is fixed by statute, and the platform already resolves the
corporation as a `VERIFIED` fact. Two different questions were being refused
together:

    "Which of the 12 regional planning authorities covers this point?"
        -> needs a boundary layer nobody publishes. Still UNAVAILABLE.

    "Who grants planning permission inside GBA / GCC limits?"
        -> fixed by the governing Act. Answerable, with a citation.

So this module answers the second and keeps refusing the first. Nothing here is
derived from a locality name, a nearest-match, or a guess: a point either falls
inside a corporation whose statutory position is cited below, or it does not.

WHAT THIS IS NOT
----------------
It names the authority. It does not tell you what that authority will permit,
and it is not a permission, an approval, or a pre-application opinion. Building
approvals in both cities are split by building category, and that split is
reported rather than flattened.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from app.facts import Fact, SourceRef, Status, Tier

# --- statutory basis, cited rather than assumed --------------------------

BENGALURU_BASIS = {
    "authority": "Greater Bengaluru Authority (GBA)",
    "instrument": "Greater Bengaluru Governance Act, 2024",
    "effect": (
        "GBA came into existence on 15 May 2025 and exercises the powers of the "
        "local planning authority for its area, including preparing master "
        "plans, granting building permissions and enforcing planning "
        "regulations. Approvals, notifications, bye-laws and master plans "
        "previously issued by BDA stand transferred to it."
    ),
    "building_permission": (
        "Building permission inside corporation limits is granted by the "
        "relevant city corporation under the corporation's own Building "
        "(Amendment) Bye-laws 2026 — five instruments, one per corporation, "
        "effective 14 May 2026."
    ),
    "source_url": "https://data.opencity.in/dataset/bengaluru-city-corporations-bye-laws-2026",
    "valid_from": date(2025, 5, 15),
}

CHENNAI_BASIS = {
    "authority": "Chennai Metropolitan Development Authority (CMDA)",
    "instrument": "Tamil Nadu Town and Country Planning Act, 1971 (s. 49)",
    "effect": (
        "CMDA regulates development in the Chennai Metropolitan Area through "
        "the issue of Planning Permission under section 49."
    ),
    "building_permission": (
        "CMDA has delegated planning permission for ordinary buildings, and for "
        "normally permissible Industrial / Residential / Institutional / "
        "Commercial uses, sub-divisions and small layouts, to the local body — "
        "Greater Chennai Corporation inside its limits. CMDA issues permission "
        "directly for Special Buildings, Group Developments and High Rise "
        "Buildings, for which powers are not delegated."
    ),
    "source_url": "https://www.cmdachennai.gov.in/planningpermission.html",
    "valid_from": date(1971, 1, 1),
}

BASIS: dict[str, dict[str, Any]] = {
    "bengaluru": BENGALURU_BASIS,
    "chennai": CHENNAI_BASIS,
}

OUTSIDE_REASON = (
    "This point is not inside the city corporation's limits. Which of the "
    "regional planning authorities covers it (BDA, BMRDA, Anekal, BIAAPA, "
    "Hoskote, Nelamangala, and others — or CMDA's wider metropolitan area) "
    "cannot be determined: no public GIS layer of planning-authority boundaries "
    "is published, only PDF jurisdiction maps (audit R5). Determining it from "
    "the locality name would be a guess."
)

NOT_A_PERMISSION = (
    "This names the authority with jurisdiction. It is not a permission, an "
    "approval, or an indication of what will be permitted. Confirm with the "
    "authority before relying on it."
)


def _source(city_id: str) -> SourceRef:
    basis = BASIS[city_id]
    return SourceRef(
        source_id=uuid5(NAMESPACE_URL, basis["source_url"]),
        name=f"{basis['authority']} — {basis['instrument']}",
        organisation=basis["authority"],
        source_url=basis["source_url"],
        tier=Tier.T2,
        source_updated=basis["valid_from"],
        licence="Statutory instrument; document republished via a public portal",
    )


def facts(city_id: str, inside_corporation: bool,
          corporation: str | None = None) -> dict[str, Fact[Any]]:
    """Planning and building-permission authority for a point.

    `inside_corporation` comes from the ward layer — a point that resolved to a
    ward is inside the corporation by construction. Nothing is inferred from a
    name.
    """
    if city_id not in BASIS or not inside_corporation:
        return {
            "planning_authority": Fact.unavailable(OUTSIDE_REASON),
            "building_permission_authority": Fact.unavailable(OUTSIDE_REASON),
        }

    basis = BASIS[city_id]
    src = _source(city_id)

    if city_id == "bengaluru":
        permission_body = (
            f"Bengaluru {corporation} City Corporation" if corporation
            else "the relevant Bengaluru city corporation"
        )
    else:
        permission_body = (
            "Greater Chennai Corporation (ordinary buildings, delegated by "
            "CMDA); CMDA directly for Special Buildings, Group Developments "
            "and High Rise Buildings"
        )

    return {
        "planning_authority": Fact.observed(
            basis["authority"],
            source=src,
            confidence=0.85,
            status=Status.VERIFIED,
            valid_as_of=basis["valid_from"],
            caveats=[
                f"Established by {basis['instrument']}. {basis['effect']}",
                NOT_A_PERMISSION,
            ],
        ),
        "building_permission_authority": Fact.observed(
            permission_body,
            source=src,
            confidence=0.80,
            status=Status.VERIFIED,
            caveats=[basis["building_permission"], NOT_A_PERMISSION],
        ),
    }


def explain(city_id: str) -> dict[str, Any]:
    """The statutory position, for the UI and the report."""
    basis = BASIS.get(city_id)
    if basis is None:
        return {"available": False, "reason": f"No statutory basis recorded for {city_id}."}
    return {
        "available": True,
        "authority": basis["authority"],
        "instrument": basis["instrument"],
        "effect": basis["effect"],
        "building_permission": basis["building_permission"],
        "source_url": basis["source_url"],
        "inside_corporation_only": True,
        "outside_reason": OUTSIDE_REASON,
        "not_a_permission": NOT_A_PERMISSION,
    }
