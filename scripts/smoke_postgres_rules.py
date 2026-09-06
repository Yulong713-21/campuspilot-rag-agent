"""Run deterministic rule smoke checks against configured PostgreSQL."""

from __future__ import annotations

import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from campuspilot_core.db import (  # noqa: E402
    create_session_factory,
    resolve_database_url,
)
from campuspilot_core.seed import (  # noqa: E402
    inspect_minimal_seed_fixture,
    seed_minimal_domain_data,
)
from campuspilot_core.smoke import run_deterministic_rule_smoke  # noqa: E402


def main() -> None:
    database_url = resolve_database_url()
    if not database_url.startswith("postgresql+"):
        raise RuntimeError(
            "PostgreSQL smoke test requires a postgresql+psycopg DATABASE_URL"
        )
    factory = create_session_factory(database_url)
    with factory() as session:
        fixture_state, counts = inspect_minimal_seed_fixture(session)
        if fixture_state == "absent":
            seed_minimal_domain_data(session)
        elif fixture_state == "incomplete":
            raise RuntimeError(f"incomplete CPTU fixture: {counts}")
        result = run_deterministic_rule_smoke(session)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
