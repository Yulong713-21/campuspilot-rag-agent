from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CacheRule:
    fresh_ttl_seconds: float
    max_stale_seconds: float
    allow_stale: bool

    def __post_init__(self) -> None:
        if self.fresh_ttl_seconds < 0:
            raise ValueError("fresh_ttl_seconds must be at least 0")
        if self.max_stale_seconds < self.fresh_ttl_seconds:
            raise ValueError("max_stale_seconds must not be smaller than fresh TTL")


@dataclass(frozen=True)
class CacheDecision:
    category: str
    use_cache: bool
    cache_state: str
    next_action: str
    cache_age_seconds: float


class CacheFreshnessPolicy:
    def __init__(self, rules: dict[str, CacheRule]) -> None:
        self.rules = rules

    def decide(self, category: str, cache_age_seconds: float) -> CacheDecision:
        if cache_age_seconds < 0:
            raise ValueError("cache_age_seconds must be at least 0")

        rule = self.rules.get(category)
        if rule is None:
            return CacheDecision(
                category=category,
                use_cache=False,
                cache_state="unclassified",
                next_action="fetch_authoritative_source",
                cache_age_seconds=cache_age_seconds,
            )

        if cache_age_seconds <= rule.fresh_ttl_seconds:
            return CacheDecision(
                category=category,
                use_cache=True,
                cache_state="fresh",
                next_action="answer_user",
                cache_age_seconds=cache_age_seconds,
            )

        if rule.allow_stale and cache_age_seconds <= rule.max_stale_seconds:
            return CacheDecision(
                category=category,
                use_cache=True,
                cache_state="stale_but_servable",
                next_action="answer_user_and_refresh_cache",
                cache_age_seconds=cache_age_seconds,
            )

        return CacheDecision(
            category=category,
            use_cache=False,
            cache_state="expired",
            next_action="fetch_authoritative_source_or_fail",
            cache_age_seconds=cache_age_seconds,
        )
