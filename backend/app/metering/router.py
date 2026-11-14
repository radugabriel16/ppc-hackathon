"""HTTP routes for the metering domain.

Endpoints are added incrementally in later PHASE1.md steps; this module only
defines the router object so app.main can mount it under the correct ROLE now.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["metering"])
