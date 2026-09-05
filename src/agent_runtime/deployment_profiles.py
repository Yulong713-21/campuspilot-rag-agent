"""Named component profiles for local and production CampusPilot runtimes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class DeploymentProfile(str, Enum):
    LITE = "lite"
    STANDARD = "standard"
    FULL = "full"


@dataclass(frozen=True)
class DeploymentCapabilities:
    """Default optional components selected by a deployment profile."""

    profile: DeploymentProfile
    lexical_backend: str
    vector_search_enabled: bool
    reranker_enabled: bool


PROFILE_CAPABILITIES = {
    DeploymentProfile.LITE: DeploymentCapabilities(
        profile=DeploymentProfile.LITE,
        lexical_backend="memory",
        vector_search_enabled=False,
        reranker_enabled=False,
    ),
    DeploymentProfile.STANDARD: DeploymentCapabilities(
        profile=DeploymentProfile.STANDARD,
        lexical_backend="elasticsearch",
        vector_search_enabled=False,
        reranker_enabled=False,
    ),
    DeploymentProfile.FULL: DeploymentCapabilities(
        profile=DeploymentProfile.FULL,
        lexical_backend="elasticsearch",
        vector_search_enabled=True,
        reranker_enabled=True,
    ),
}


def resolve_deployment_profile(
    environ: Mapping[str, str],
) -> DeploymentCapabilities:
    """Resolve named defaults; explicit component variables still override."""

    name = environ.get("CAMPUSPILOT_DEPLOYMENT_PROFILE", "lite").lower()
    try:
        return PROFILE_CAPABILITIES[DeploymentProfile(name)]
    except ValueError as exc:
        supported = ", ".join(item.value for item in DeploymentProfile)
        raise ValueError(
            f"unsupported CAMPUSPILOT_DEPLOYMENT_PROFILE: {name}; "
            f"expected one of {supported}"
        ) from exc
