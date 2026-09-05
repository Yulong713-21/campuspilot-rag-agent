from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.deployment_profiles import (  # noqa: E402
    DeploymentProfile,
    resolve_deployment_profile,
)


class DeploymentProfilesTest(unittest.TestCase):
    def test_lite_standard_and_full_select_progressive_components(self) -> None:
        lite = resolve_deployment_profile(
            {"CAMPUSPILOT_DEPLOYMENT_PROFILE": "lite"}
        )
        standard = resolve_deployment_profile(
            {"CAMPUSPILOT_DEPLOYMENT_PROFILE": "standard"}
        )
        full = resolve_deployment_profile(
            {"CAMPUSPILOT_DEPLOYMENT_PROFILE": "full"}
        )

        self.assertEqual(lite.profile, DeploymentProfile.LITE)
        self.assertEqual(lite.lexical_backend, "memory")
        self.assertEqual(standard.lexical_backend, "elasticsearch")
        self.assertFalse(standard.vector_search_enabled)
        self.assertTrue(full.vector_search_enabled)
        self.assertTrue(full.reranker_enabled)

    def test_unknown_profile_fails_with_supported_names(self) -> None:
        with self.assertRaisesRegex(ValueError, "lite, standard, full"):
            resolve_deployment_profile(
                {"CAMPUSPILOT_DEPLOYMENT_PROFILE": "huge"}
            )


if __name__ == "__main__":
    unittest.main()
