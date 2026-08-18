"""v1 API router.

Endpoints are added as their phase lands. Routes for unbuilt phases are absent
rather than stubbed with fake data — an endpoint that returns plausible
placeholder values is the exact failure mode this project is designed against.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import advisory as advisory_routes
from app.api.v1 import advisory_ml as advisory_ml_routes
from app.api.v1 import builder as builder_routes
from app.api.v1 import cities as city_routes
from app.api.v1 import cross_city as cross_city_routes
from app.api.v1 import total_price as total_price_routes
from app.api.v1 import documents as document_routes
from app.api.v1 import extra as extra_routes
from app.api.v1 import feasibility as feasibility_routes
from app.api.v1 import flood as flood_routes
from app.api.v1 import insights as insight_routes
from app.api.v1 import jurisdiction as jurisdiction_routes
from app.api.v1 import layers as layer_routes
from app.api.v1 import meta as meta_routes
from app.api.v1 import ml as ml_routes
from app.api.v1 import nearby as nearby_routes
from app.api.v1 import planning as planning_routes
from app.api.v1 import planning_ml as planning_ml_routes
from app.api.v1 import predict as predict_routes
from app.api.v1 import report as report_routes
from app.api.v1 import roads as road_routes
from app.api.v1 import valuation as valuation_routes

api_router = APIRouter()

# --- existing routes, unchanged ---
api_router.include_router(
    jurisdiction_routes.router, prefix="/jurisdiction", tags=["jurisdiction"]
)
api_router.include_router(layer_routes.router, prefix="/map", tags=["map"])
api_router.include_router(nearby_routes.router, prefix="/nearby", tags=["nearby"])
api_router.include_router(
    feasibility_routes.router, prefix="/feasibility", tags=["feasibility"]
)
api_router.include_router(
    valuation_routes.router, prefix="/valuation", tags=["valuation"]
)
api_router.include_router(meta_routes.router, prefix="/sources", tags=["sources"])

# --- multi-city + ML additions ---
api_router.include_router(city_routes.router, prefix="/cities", tags=["cities"])
api_router.include_router(ml_routes.router, prefix="/ml", tags=["machine-learning"])
api_router.include_router(insight_routes.router, prefix="/insights", tags=["insights"])
api_router.include_router(builder_routes.router, prefix="/builder", tags=["builder"])
api_router.include_router(predict_routes.router, prefix="/predict", tags=["prediction"])
api_router.include_router(planning_routes.router, prefix="/planning", tags=["planning"])
api_router.include_router(advisory_routes.router, prefix="/advisory", tags=["advisory"])
api_router.include_router(report_routes.router, prefix="/report", tags=["report"])
api_router.include_router(extra_routes.router, prefix="/extra", tags=["extra-models"])
api_router.include_router(road_routes.router, prefix="/roads", tags=["roads"])
api_router.include_router(flood_routes.router, prefix="/flood", tags=["environment"])
api_router.include_router(document_routes.router, prefix="/documents", tags=["documents"])
api_router.include_router(advisory_ml_routes.router, prefix="/advisory-ml", tags=["advisory-ml"])
api_router.include_router(planning_ml_routes.router, prefix="/planning-ml", tags=["planning-ml"])
api_router.include_router(cross_city_routes.router, prefix="/cross-city", tags=["cross-city"])
api_router.include_router(total_price_routes.router, prefix="/total-price", tags=["total-price"])
