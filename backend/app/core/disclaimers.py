"""Module 39 disclaimers, defined once and attached to every response envelope.

Kept in code rather than in a CMS so they cannot be edited away, and so a test
can assert that no report is ever serialised without them.
"""

from __future__ import annotations

from typing import Final

PLATFORM_NATURE: Final = (
    "This platform is a decision-support and research prototype. It is not an "
    "official government system and its output has no legal standing."
)

DOES_NOT_REPLACE: Final[tuple[str, ...]] = (
    "Government approval",
    "Legal title verification",
    "Advocate or legal due diligence",
    "Official building-plan sanction",
    "Licensed surveyor verification",
    "Planning authority confirmation",
    "Property registration verification",
    "Professional valuation",
)

KHATA_IS_NOT_TITLE: Final = (
    "A Khata or e-Khata is a municipal record for property tax purposes. It is "
    "not proof of legal title or ownership. Title must be verified separately "
    "through registered documents and legal due diligence."
)

RECORDS_NOT_AUTOMATED: Final = (
    "Official property records (e-Khata/e-Aasthi, property tax, building "
    "permission, occupancy and encumbrance certificates) are not available "
    "through any public API. This platform links to the official portals and "
    "checks documents you supply; it does not hold or retrieve government "
    "records on your behalf."
)

PREDICTIONS_ARE_NOT_FACTS: Final = (
    "Estimated values are model predictions, not valuations, and are trained on "
    "asking prices rather than registered transaction prices. Asking prices are "
    "systematically higher than transaction prices."
)

FEASIBILITY_IS_NOT_APPROVAL: Final = (
    "Development feasibility output is an indicative calculation under stated "
    "assumptions. It is not a building-plan sanction and does not guarantee that "
    "any authority will approve the described development."
)

DERIVED_LAND_USE: Final = (
    "Land use shown here is digitised from published master-plan map sheets and "
    "is indicative. Confirm the notified land use with the planning authority."
)

RISK_IS_COMPUTED: Final = (
    "Unless explicitly marked as official risk data, risk indicators are computed "
    "from geographic proximity and terrain. They are not an official flood, drain "
    "or environmental determination."
)

STANDARD_SET: Final[tuple[str, ...]] = (
    PLATFORM_NATURE,
    RECORDS_NOT_AUTOMATED,
)
