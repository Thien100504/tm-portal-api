"""
API v1 Router Aggregator

Aggregates all v1 module routers in one place.
main.py only needs to include this router.
"""

from fastapi import APIRouter


api_v1_router = APIRouter(prefix="/api/v1")

