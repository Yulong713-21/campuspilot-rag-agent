from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import Session


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from campuspilot_core.admission_criteria import (  # noqa: E402
    extract_directory,
    sync_catalog,
    write_catalog,
    write_vector_documents,
)
from campuspilot_core.db import Base  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract official admission criteria into SQL and RAG docs."
    )
    parser.add_argument(
        "--source-directory",
        type=Path,
        default=REPO_ROOT / "data/official_sources/clean/monash/2026",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=REPO_ROOT / "data/admissions/monash_2026.json",
    )
    parser.add_argument(
        "--vector-docs",
        type=Path,
        default=REPO_ROOT / "data/admissions/vector_docs/monash/2026",
    )
    parser.add_argument(
        "--database-url",
        default=f"sqlite:///{(REPO_ROOT / 'logs/campuspilot_domain.sqlite3').as_posix()}",
    )
    parser.add_argument(
        "--skip-database",
        action="store_true",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = extract_directory(args.source_directory)
    catalog_count = write_catalog(records, args.catalog)
    documents = write_vector_documents(records, args.vector_docs)
    database_count = 0
    if not args.skip_database:
        engine = create_engine(args.database_url)
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            database_count = sync_catalog(session, records)
        engine.dispose()
    print(
        json.dumps(
            {
                "official_programs": len({item.program_code for item in records}),
                "admission_pathways": catalog_count,
                "vector_documents": len(documents),
                "database_rows_synced": database_count,
                "unknown_intakes": sum(not item.available_intakes for item in records),
                "next_action": "review_criteria_before_building_admission_agent",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
