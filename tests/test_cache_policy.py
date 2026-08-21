from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.cache_policy import CacheFreshnessPolicy, CacheRule


class CacheFreshnessPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = CacheFreshnessPolicy(
            {
                "course_intro": CacheRule(
                    fresh_ttl_seconds=6 * 60 * 60,
                    max_stale_seconds=72 * 60 * 60,
                    allow_stale=True,
                ),
                "tuition": CacheRule(
                    fresh_ttl_seconds=5 * 60,
                    max_stale_seconds=5 * 60,
                    allow_stale=False,
                ),
            }
        )

    def test_uses_stale_course_intro_and_requests_background_refresh(self) -> None:
        decision = self.policy.decide("course_intro", cache_age_seconds=24 * 60 * 60)

        self.assertTrue(decision.use_cache)
        self.assertEqual(decision.cache_state, "stale_but_servable")
        self.assertEqual(decision.next_action, "answer_user_and_refresh_cache")

    def test_uses_tuition_cache_within_short_fresh_ttl(self) -> None:
        decision = self.policy.decide("tuition", cache_age_seconds=2 * 60)

        self.assertTrue(decision.use_cache)
        self.assertEqual(decision.cache_state, "fresh")
        self.assertEqual(decision.next_action, "answer_user")

    def test_rejects_day_old_tuition_cache(self) -> None:
        decision = self.policy.decide("tuition", cache_age_seconds=24 * 60 * 60)

        self.assertFalse(decision.use_cache)
        self.assertEqual(decision.cache_state, "expired")
        self.assertEqual(
            decision.next_action,
            "fetch_authoritative_source_or_fail",
        )

    def test_unknown_category_does_not_guess_cache_policy(self) -> None:
        decision = self.policy.decide("unknown", cache_age_seconds=60)

        self.assertFalse(decision.use_cache)
        self.assertEqual(decision.cache_state, "unclassified")

    def test_rejects_negative_cache_age(self) -> None:
        with self.assertRaisesRegex(ValueError, "cache_age_seconds"):
            self.policy.decide("course_intro", cache_age_seconds=-1)


if __name__ == "__main__":
    unittest.main()
