from __future__ import annotations

from pathlib import Path
import sys
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.handbook_vector import HandbookChunk  # noqa: E402
from agent_runtime.retrieval import (  # noqa: E402
    FallbackLexicalRetriever,
    InMemoryBM25Retriever,
)
from campuspilot_core.db import Base  # noqa: E402
from campuspilot_core.models import Course, CourseOffering, CourseVersion  # noqa: E402
from campuspilot_core.seed import seed_minimal_domain_data  # noqa: E402
from campuspilot_core.services import DegreeAuditService  # noqa: E402


class Phase3FaultIsolationTest(unittest.TestCase):
    def test_fit9136_rule_truth_survives_elasticsearch_failure(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            ids = seed_minimal_domain_data(session)
            course = Course(
                university_id=ids["university_id"],
                code="FIT9136",
                canonical_name="Introduction to Python programming",
            )
            session.add(course)
            session.flush()
            version = CourseVersion(
                course_id=course.id,
                handbook_year=2026,
                title=course.canonical_name,
                credit_points=6,
                evidence={"source_id": "POSTGRES-RULE-FIXTURE"},
            )
            session.add(version)
            session.flush()
            session.add(
                CourseOffering(
                    course_version_id=version.id,
                    teaching_period="Semester 2",
                    evidence={"source_id": "POSTGRES-RULE-FIXTURE"},
                )
            )
            session.commit()

            chunk = HandbookChunk(
                chunk_id="fit9136",
                parent_id="fit9136-parent",
                source_id="MONASH-FIT9136-2026",
                university_id="monash",
                handbook_year=2026,
                program_code="C6001",
                source_type="unit_handbook",
                discipline_ids=["computing"],
                title="FIT9136 Introduction to Python programming",
                heading="Availability",
                content="FIT9136 Semester 2 availability.",
                parent_content="Official Handbook evidence.",
                source_url="https://handbook.monash.edu/2026/units/FIT9136",
                source_sha256="abc",
                program_codes=["C6001"],
            )

            class UnavailableElasticsearch:
                def search(self, query: str, **kwargs):
                    raise ConnectionError("elasticsearch unavailable")

            evidence = FallbackLexicalRetriever(
                UnavailableElasticsearch(),
                InMemoryBM25Retriever(
                    [
                        chunk,
                        HandbookChunk(
                            **{
                                **chunk.to_dict(),
                                "chunk_id": "other-one",
                                "parent_id": "other-parent-one",
                                "title": "Database systems",
                                "content": "Relational algebra and transactions.",
                            }
                        ),
                        HandbookChunk(
                            **{
                                **chunk.to_dict(),
                                "chunk_id": "other-two",
                                "parent_id": "other-parent-two",
                                "title": "Computer networks",
                                "content": "Routing and network protocols.",
                            }
                        ),
                    ]
                ),
            )
            self.assertTrue(evidence.search("Can I take FIT9136 in Semester 2?"))
            self.assertEqual(evidence.last_error, "ConnectionError")

            rules = DegreeAuditService(session)
            resolved = rules.get_course_version(
                university_id=ids["university_id"],
                course_code="FIT9136",
                handbook_year=2026,
            )
            self.assertTrue(
                rules.is_course_offered(
                    course_version_id=resolved.id,
                    teaching_period="Semester 2",
                )
            )
            self.assertEqual(
                rules.get_prerequisites(
                    ids["program_version_ids"]["MIT-2026"],
                    ids["specialisation_ids"]["MIT-2026-AI"],
                    course.id,
                ),
                [],
            )
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
