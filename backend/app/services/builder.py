"""BUILDER MODE — development project financial analysis (Module 19).

Deterministic arithmetic, fully itemised. The ML contribution is the expected
selling price, which may come from the trained price model; everything else is
transparent accounting so a builder can check every line.

Nothing here is a recommendation to invest.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SQM_PER_SQFT = 0.092903


@dataclass(slots=True)
class BuilderInput:
    land_area_sqft: float
    land_cost_total: float
    construction_cost_per_sqft: float
    expected_builtup_sqft: float
    num_units: int
    avg_unit_size_sqft: float
    expected_selling_price_psf: float
    other_costs_pct: float = 8.0        # approvals, design, statutory, contingency
    marketing_pct: float = 3.0
    finance_rate_pct: float = 11.0
    project_months: int = 30
    debt_share_pct: float = 60.0


def analyse(inp: BuilderInput, *, price_source: str) -> dict[str, Any]:
    """Full project economics with best / base / worst scenarios."""
    if inp.expected_builtup_sqft <= 0 or inp.num_units <= 0:
        return {"error": "Built-up area and unit count must be greater than zero"}

    construction = inp.expected_builtup_sqft * inp.construction_cost_per_sqft
    base_cost = inp.land_cost_total + construction
    other = base_cost * (inp.other_costs_pct / 100.0)

    saleable = inp.num_units * inp.avg_unit_size_sqft
    revenue = saleable * inp.expected_selling_price_psf
    marketing = revenue * (inp.marketing_pct / 100.0)

    debt = (inp.land_cost_total + construction) * (inp.debt_share_pct / 100.0)
    # Average outstanding balance over the build is roughly half the facility.
    finance = debt * (inp.finance_rate_pct / 100.0) * (inp.project_months / 12.0) * 0.5

    total_cost = base_cost + other + marketing + finance
    gross_profit = revenue - (base_cost + other)
    net_profit = revenue - total_cost
    roi = (net_profit / total_cost * 100.0) if total_cost else 0.0
    margin = (net_profit / revenue * 100.0) if revenue else 0.0

    breakeven_psf = (total_cost / saleable) if saleable else 0.0
    breakeven_units = (
        math_ceil(total_cost / (inp.avg_unit_size_sqft * inp.expected_selling_price_psf))
        if inp.avg_unit_size_sqft and inp.expected_selling_price_psf else None
    )

    def scenario(label: str, price_delta_pct: float, cost_delta_pct: float) -> dict[str, Any]:
        rev = saleable * inp.expected_selling_price_psf * (1 + price_delta_pct / 100.0)
        cost = total_cost * (1 + cost_delta_pct / 100.0)
        profit = rev - cost
        return {
            "scenario": label,
            "assumption": (
                f"selling price {price_delta_pct:+.0f}%, total cost {cost_delta_pct:+.0f}%"
            ),
            "revenue": round(rev),
            "total_cost": round(cost),
            "net_profit": round(profit),
            "roi_pct": round(profit / cost * 100.0, 1) if cost else None,
        }

    sensitivity = []
    for d in (-15, -10, -5, 0, 5, 10, 15):
        rev = saleable * inp.expected_selling_price_psf * (1 + d / 100.0)
        sensitivity.append({
            "price_change_pct": d,
            "net_profit": round(rev - total_cost),
            "roi_pct": round((rev - total_cost) / total_cost * 100.0, 1) if total_cost else None,
        })

    # Diagnose an unviable project rather than just printing a negative number.
    land_psf_of_saleable = inp.land_cost_total / saleable if saleable else 0.0
    diagnosis = None
    if net_profit < 0:
        reasons = []
        if inp.expected_selling_price_psf < breakeven_psf:
            gap = breakeven_psf - inp.expected_selling_price_psf
            reasons.append(
                f"The expected selling price of Rs {inp.expected_selling_price_psf:,.0f}/sq.ft "
                f"is below the break-even price of Rs {breakeven_psf:,.0f}/sq.ft, a shortfall "
                f"of Rs {gap:,.0f}/sq.ft."
            )
        if land_psf_of_saleable > inp.expected_selling_price_psf * 0.45:
            reasons.append(
                f"Land alone costs Rs {land_psf_of_saleable:,.0f} per saleable sq.ft, which is "
                f"{land_psf_of_saleable / inp.expected_selling_price_psf * 100:.0f}% of the "
                f"selling price. Land above roughly 40-45% of the selling price rarely leaves a margin."
            )
        if saleable < inp.expected_builtup_sqft * 0.7:
            reasons.append(
                f"Only {saleable:,.0f} sq.ft of the {inp.expected_builtup_sqft:,.0f} sq.ft built-up "
                f"area is saleable ({saleable / inp.expected_builtup_sqft * 100:.0f}%). Construction "
                f"is paid on the full built-up area but revenue comes only from saleable area."
            )
        required_price = breakeven_psf
        required_land = max(0.0, revenue - (construction + other + marketing + finance))
        diagnosis = {
            "viable": False,
            "headline": "This project does not break even under the stated assumptions.",
            "reasons": reasons,
            "to_break_even": [
                f"Raise the selling price to at least Rs {required_price:,.0f}/sq.ft, or",
                f"Reduce the land cost to about Rs {required_land:,.0f} "
                f"(Rs {required_land / inp.land_area_sqft:,.0f}/sq.ft of land), or",
                "Increase saleable area within the permitted built-up limit.",
            ],
            "note": (
                "A negative result is a valid finding, not an error: it means the "
                "land price and the achievable selling price are inconsistent."
            ),
        }
    else:
        diagnosis = {
            "viable": True,
            "headline": f"The project returns {roi:.1f}% under the stated assumptions.",
            "reasons": [],
            "to_break_even": [],
            "note": "Viability is highly sensitive to the selling price - see the scenarios below.",
        }

    return {
        "diagnosis": diagnosis,
        "land_cost_per_saleable_sqft": round(land_psf_of_saleable),
        "inputs": {
            "land_area_sqft": inp.land_area_sqft,
            "expected_builtup_sqft": inp.expected_builtup_sqft,
            "saleable_sqft": round(saleable),
            "num_units": inp.num_units,
            "avg_unit_size_sqft": inp.avg_unit_size_sqft,
            "expected_selling_price_psf": round(inp.expected_selling_price_psf),
            "expected_selling_price_source": price_source,
        },
        "costs": {
            "land": round(inp.land_cost_total),
            "construction": round(construction),
            "other_costs": round(other),
            "marketing": round(marketing),
            "finance": round(finance),
            "total": round(total_cost),
        },
        "returns": {
            "revenue": round(revenue),
            "gross_profit": round(gross_profit),
            "net_profit": round(net_profit),
            "roi_pct": round(roi, 1),
            "margin_pct": round(margin, 1),
        },
        "breakeven": {
            "price_per_sqft": round(breakeven_psf),
            "units_to_sell": breakeven_units,
            "note": (
                "Break-even selling price is total project cost divided by "
                "saleable area."
            ),
        },
        "scenarios": [
            scenario("BEST CASE", +10, -5),
            scenario("BASE CASE", 0, 0),
            scenario("WORST CASE", -15, +10),
        ],
        "sensitivity": sensitivity,
        "assumptions": [
            f"Other costs at {inp.other_costs_pct}% of land + construction "
            "(approvals, design, statutory charges, contingency)",
            f"Marketing at {inp.marketing_pct}% of revenue",
            f"Debt {inp.debt_share_pct}% of land + construction at "
            f"{inp.finance_rate_pct}% over {inp.project_months} months, charged on "
            "an average outstanding balance of half the facility",
            "No land appreciation, no phased sales, no GST, no stamp duty",
            "Saleable area = units x average unit size; loading factor not modelled",
        ],
        "disclaimer": (
            "Financial modelling under stated assumptions. NOT a valuation, NOT "
            "investment advice, and NOT a statement of what may lawfully be "
            "built — see Development feasibility for the regulatory position."
        ),
    }


def math_ceil(x: float) -> int:
    import math

    return int(math.ceil(x))
