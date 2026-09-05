"""Deterministic CampusPilot domain core."""

from .coverage import (
    AcademicCoverageRecord,
    AcademicCoverageRegistry,
    CoverageCapabilities,
    CoverageLevel,
)

from .db import Base, create_session_factory, resolve_database_url
from .services import DegreeAuditService

__all__ = [
    "AcademicCoverageRecord",
    "AcademicCoverageRegistry",
    "CoverageCapabilities",
    "CoverageLevel",
    "Base",
    "DegreeAuditService",
    "create_session_factory",
    "resolve_database_url",
]
