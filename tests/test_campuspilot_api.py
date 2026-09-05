from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.api import create_app  # noqa: E402
from agent_runtime.handbook_vector import HandbookChunk  # noqa: E402


class FakeSemesterAdvisor:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def explain(self, **facts):
        self.calls.append(facts)
        return {
            "summary": "本学期先完成核心能力建设。",
            "arrangement_reason": "课程均已通过规则引擎校验。",
            "study_strategy": ["按周完成实验", "提前复习核心概念"],
            "internship_advice": "本学期开始整理项目经历。",
            "risk_notes": ["考试形式仍需核对课程大纲。"],
            "evidence_ids": ["MONASH-C6001-HANDBOOK-2026"],
            "answer_source": "ollama_semester_advisor",
            "confidence": "medium",
            "next_action": "review_semester_advice",
            "trace": [{"tool": "generate_semester_advice", "ok": True}],
            "trace_tools": ["generate_semester_advice"],
        }


class CampusPilotAPITest(unittest.TestCase):
    def setUp(self) -> None:
        logs_dir = REPO_ROOT / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir = TemporaryDirectory(dir=logs_dir)
        database = Path(self.temp_dir.name) / "campuspilot-api.sqlite3"
        self.client_context = TestClient(create_app(database_path=database))
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.temp_dir.cleanup()

    def test_catalog_exposes_versioned_official_sample(self) -> None:
        response = self.client.get("/api/catalog")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["data_mode"],
            "official_public_sample",
        )
        self.assertEqual(len(response.json()["programs"]), 2)
        self.assertEqual(response.json()["official_document_count"], 4)
        self.assertEqual(len(response.json()["universities"]), 8)
        self.assertEqual(len(response.json()["disciplines"]), 5)

    def test_recommend_programs_without_preselecting_discipline(self) -> None:
        response = self.client.post(
            "/api/admissions/recommend",
            json={
                "prompt": "我喜欢沟通和创意，希望毕业后做品牌营销",
                "score_value": 78,
                "score_scale": 100,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "PROGRAM_RECOMMENDATIONS_READY")
        self.assertTrue(payload["recommendations"])
        self.assertEqual(
            payload["answer_source"], "catalog_program_recommendation_agent"
        )

    def test_search_undergraduate_institution_master_data(self) -> None:
        response = self.client.get(
            "/api/admissions/institutions",
            params={"query": "莫纳什", "country_code": "AU"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["catalog_counts"]["CN"], 1412)
        self.assertEqual(
            payload["matches"][0]["official_name"],
            "Monash University",
        )
        self.assertEqual(payload["next_action"], "select_verified_institution")

    def test_filter_go8_universities_by_common_discipline(self) -> None:
        response = self.client.get(
            "/api/universities",
            params={"discipline_id": "engineering"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 8)
        self.assertEqual(response.json()["planning_verified_count"], 1)

    def test_reject_unknown_go8_discipline(self) -> None:
        response = self.client.get(
            "/api/universities",
            params={"discipline_id": "medicine"},
        )

        self.assertEqual(response.status_code, 422)

    def test_search_official_evidence(self) -> None:
        response = self.client.post(
            "/api/evidence/search",
            json={
                "query": "FIT5120 capstone final semester",
                "handbook_year": 2026,
                "k": 2,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["documents"][0]["document_id"],
            "DOC-FIT5120-2026",
        )
        self.assertEqual(
            response.json()["answer_source"],
            "catalog_bm25",
        )

    def test_compare_programs(self) -> None:
        response = self.client.post(
            "/api/programs/compare",
            json={
                "first_program_variant_id": "MONASH-C6001-EL1",
                "second_program_variant_id": "MONASH-C6001-EL2",
                "handbook_year": 2026,
                "study_stream": "Industry Experience",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["differences"]["credits_to_complete"],
            -24,
        )

    def test_classify_course_role(self) -> None:
        response = self.client.post(
            "/api/courses/classify",
            json={
                "program_variant_id": "MONASH-C6001-EL2",
                "handbook_year": 2026,
                "study_stream": "Industry Experience",
                "course_code": "FIT5120",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["rule_type"],
            "CAPSTONE",
        )

    def test_generate_study_plans(self) -> None:
        response = self.client.post(
            "/api/plans/generate",
            json={
                "program_variant_id": "MONASH-C6001-EL2",
                "handbook_year": 2026,
                "study_stream": "Industry Experience",
                "completed_courses": ["FIT5057"],
                "max_courses_per_semester": 4,
                "preserve_policy_flexibility": True,
                "start_semester": "2026-S2",
            },
        )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(payload["plans"]), 3)
        self.assertEqual(
            [plan["plan_id"] for plan in payload["plans"]],
            ["fastest", "balanced", "flexible"],
        )
        self.assertEqual(
            [plan["estimated_semesters"] for plan in payload["plans"]],
            [3, 4, 5],
        )
        self.assertTrue(payload["validation"]["all_valid"])
        self.assertEqual(
            payload["trace_tools"][-3:],
            [
                "calculate_credit_progress",
                "generate_study_plan",
                "validate_study_plan",
            ],
        )
        self.assertEqual(
            payload["answer_source"],
            "official_rag_and_structured_rules",
        )
        first_course = payload["plans"][0]["semesters"][0]["courses"][0]
        self.assertIn(first_course["workload_level"], {"LOW", "MEDIUM", "HIGH"})
        self.assertEqual(first_course["exam_status"], "NO")
        self.assertNotIn("考核待核实", first_course["assessment_tags"])

    def test_explain_semester_regenerates_plan_before_calling_agent(
        self,
    ) -> None:
        advisor = FakeSemesterAdvisor()
        logs_dir = REPO_ROOT / "logs"
        with TemporaryDirectory(dir=logs_dir) as temp_dir:
            database = Path(temp_dir) / "semester-agent.sqlite3"
            with TestClient(
                create_app(
                    database_path=database,
                    semester_advisor=advisor,
                )
            ) as client:
                response = client.post(
                    "/api/plans/semesters/explain",
                    json={
                        "program_variant_id": "MONASH-C6001-EL2",
                        "handbook_year": 2026,
                        "study_stream": "Industry Experience",
                        "completed_courses": ["FIT5057"],
                        "max_courses_per_semester": 4,
                        "preserve_policy_flexibility": True,
                        "start_semester": "2026-S2",
                        "plan_id": "fastest",
                        "semester": "2026 S2",
                    },
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["answer_source"],
            "ollama_semester_advisor",
        )
        self.assertEqual(len(advisor.calls), 1)
        self.assertEqual(
            advisor.calls[0]["plan"]["plan_id"],
            "fastest",
        )
        self.assertEqual(
            advisor.calls[0]["semester"]["semester"],
            "2026 S2",
        )

    def test_explain_semester_rejects_semester_outside_validated_plan(
        self,
    ) -> None:
        advisor = FakeSemesterAdvisor()
        logs_dir = REPO_ROOT / "logs"
        with TemporaryDirectory(dir=logs_dir) as temp_dir:
            database = Path(temp_dir) / "semester-agent.sqlite3"
            with TestClient(
                create_app(
                    database_path=database,
                    semester_advisor=advisor,
                )
            ) as client:
                response = client.post(
                    "/api/plans/semesters/explain",
                    json={
                        "program_variant_id": "MONASH-C6001-EL2",
                        "handbook_year": 2026,
                        "study_stream": "Industry Experience",
                        "completed_courses": ["FIT5057"],
                        "max_courses_per_semester": 4,
                        "preserve_policy_flexibility": True,
                        "start_semester": "2026-S2",
                        "plan_id": "fastest",
                        "semester": "2035 S1",
                    },
                )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(advisor.calls, [])

    def test_calculate_degree_progress_exposes_missing_rules_and_trace(
        self,
    ) -> None:
        response = self.client.post(
            "/api/progress/calculate",
            json={
                "program_variant_id": "MONASH-C6001-EL2",
                "handbook_year": 2026,
                "study_stream": "Industry Experience",
                "completed_courses": [
                    "fit5057",
                    "FIT5125",
                    "UNKNOWN1000",
                ],
            },
        )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["completed_credits"], 12)
        self.assertEqual(payload["remaining_credits"], 60)
        self.assertEqual(payload["ignored_courses"], ["UNKNOWN1000"])
        self.assertEqual(
            payload["trace_tools"],
            ["get_program_rules", "calculate_degree_progress"],
        )
        self.assertEqual(
            payload["violations"][0]["error_code"],
            "TOTAL_CREDITS_NOT_MET",
        )
        self.assertEqual(payload["next_action"], "select_remaining_courses")

    def test_chat_routes_fast_graduation_goal_to_study_plan_tools(
        self,
    ) -> None:
        response = self.client.post(
            "/api/agent/chat",
            json={
                "message": "我想尽快毕业，帮我规划一下",
                "program_variant_id": "MONASH-C6001-EL1",
                "handbook_year": 2026,
                "study_stream": "Industry Experience",
                "completed_courses": ["FIT5057", "FIT5125"],
                "max_courses_per_semester": 4,
                "start_semester": "2026-S2",
            },
        )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["intent"], "study_plan")
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(len(payload["study_plans"]["plans"]), 3)
        self.assertEqual(
            payload["trace_tools"][-3:],
            [
                "generate_study_plan",
                "validate_study_plan",
                "generate_plan_explanation",
            ],
        )

    def test_chat_keeps_four_course_limit_for_workload_balance(self) -> None:
        response = self.client.post(
            "/api/agent/chat",
            json={
                "message": "怎么选课实现负载均衡",
                "program_variant_id": "MONASH-C6001-EL1",
                "handbook_year": 2026,
                "study_stream": "Industry Experience",
                "completed_courses": ["FIT5057", "FIT5058"],
                "max_courses_per_semester": 4,
                "start_semester": "2026-S2",
            },
        )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            payload["study_plans"]["profile"]["max_courses_per_semester"],
            4,
        )
        first_plan = payload["study_plans"]["plans"][0]
        self.assertEqual(first_plan["name"], "负载均衡优先")
        self.assertEqual(len(first_plan["semesters"][0]["courses"]), 4)

    def test_chat_routes_credit_question_to_progress_tool(self) -> None:
        response = self.client.post(
            "/api/agent/chat",
            json={
                "message": "我还差多少学分？",
                "program_variant_id": "MONASH-C6001-EL2",
                "study_stream": "Industry Experience",
                "completed_courses": ["FIT5057"],
            },
        )

        payload = response.json()
        self.assertEqual(payload["intent"], "degree_progress")
        self.assertEqual(payload["progress"]["completed_credits"], 6)
        self.assertIn("calculate_degree_progress", payload["trace_tools"])

    def test_chat_classifies_course_role_with_user_facing_answer(self) -> None:
        response = self.client.post(
            "/api/agent/chat",
            json={
                "message": "FIT5120 在当前路径中算什么课？",
                "program_variant_id": "MONASH-C6001-EL2",
                "study_stream": "Industry Experience",
            },
        )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["intent"], "course_role")
        self.assertEqual(payload["course_role"]["rule_type"], "CAPSTONE")
        self.assertEqual(payload["course_role"]["credits_counted"], 12)
        self.assertIn("毕业项目课", payload["message"])
        self.assertEqual(payload["trace_tools"][-1], "classify_course_role")

    def test_chat_asks_for_missing_program_context(self) -> None:
        response = self.client.post(
            "/api/agent/chat",
            json={"message": "帮我生成最快毕业方案"},
        )

        payload = response.json()
        self.assertEqual(payload["status"], "needs_clarification")
        self.assertEqual(
            payload["missing_fields"],
            ["program_variant_id", "study_stream"],
        )
        self.assertEqual(payload["next_action"], "ask_clarification")

    def test_chat_explains_supported_capabilities_for_open_question(
        self,
    ) -> None:
        response = self.client.post(
            "/api/agent/chat",
            json={"message": "你好，你可以帮我做什么？"},
        )

        payload = response.json()
        self.assertEqual(payload["intent"], "capabilities")
        self.assertEqual(payload["next_action"], "wait_for_user_goal")

    def test_chat_routes_handbook_question_to_retrieval_agent(self) -> None:
        response = self.client.post(
            "/api/agent/chat",
            json={
                "message": "FIT5120 的课程要求是什么？",
                "program_variant_id": "MONASH-C6001-EL2",
                "handbook_year": 2026,
                "study_stream": "Industry Experience",
            },
        )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["intent"], "handbook_qa")
        self.assertGreater(len(payload["evidence"]), 0)
        self.assertIn("search_handbook", payload["trace_tools"])
        self.assertEqual(
            payload["answer_source"],
            "handbook_extractive_fallback",
        )

    def test_chat_answers_stable_terminology_from_faq_before_rag(self) -> None:
        response = self.client.post(
            "/api/agent/chat",
            json={"message": "Entry Level 1 是 Master 第一年吗？"},
        )

        payload = response.json()
        self.assertEqual(payload["answer_source"], "campuspilot_faq")
        self.assertEqual(payload["confidence"], "high")
        self.assertIn("search_faq", payload["trace_tools"])
        self.assertNotIn("search_handbook", payload["trace_tools"])

    def test_chat_routes_company_recruitment_time_to_versioned_kb(self) -> None:
        response = self.client.post(
            "/api/agent/chat",
            json={"message": "阿里巴巴2027届秋招什么时候投？"},
        )

        payload = response.json()
        self.assertEqual(payload["intent"], "recruitment_qa")
        self.assertEqual(payload["answer_source"], "recruitment_extractive_answer")
        self.assertIn("search_china_recruitment_kb", payload["trace_tools"])
        self.assertEqual(payload["evidence"][0]["source_id"], "alibaba-campus-2027")

    def test_recruitment_goal_with_arrangement_routes_to_study_plan(self) -> None:
        response = self.client.post(
            "/api/agent/chat",
            json={
                "message": "我想 2028 年秋招就业，推荐我怎么安排",
                "program_variant_id": "MONASH-C6001-EL2",
                "handbook_year": 2026,
                "study_stream": "Industry Experience",
                "completed_courses": ["FIT5057", "FIT5058"],
                "max_courses_per_semester": 4,
                "start_semester": "2026-S2",
            },
        )

        payload = response.json()
        self.assertEqual(payload["intent"], "study_plan")
        self.assertIsNotNone(payload["study_plans"])
        self.assertEqual(payload["study_plans"]["plans"][0]["name"], "秋招准备优先")
        self.assertIn("2028 年秋招", payload["message"])
        self.assertNotIn("search_china_recruitment_kb", payload["trace_tools"])

    def test_current_course_question_overrides_recruitment_history(self) -> None:
        response = self.client.post(
            "/api/agent/chat",
            json={
                "message": "FIT5120 的考核方式是什么？",
                "program_variant_id": "MONASH-C6001-EL2",
                "handbook_year": 2026,
                "study_stream": "Industry Experience",
                "conversation_history": [
                    {"role": "user", "content": "阿里巴巴秋招什么时候投？"},
                    {"role": "assistant", "content": "这里是招聘时间。"},
                ],
            },
        )

        payload = response.json()
        self.assertEqual(payload["intent"], "handbook_qa")
        self.assertIn("search_handbook", payload["trace_tools"])
        self.assertNotIn("search_china_recruitment_kb", payload["trace_tools"])

    def test_current_plan_request_overrides_recruitment_history(self) -> None:
        response = self.client.post(
            "/api/agent/chat",
            json={
                "message": "帮我生成最快毕业方案",
                "program_variant_id": "MONASH-C6001-EL2",
                "study_stream": "Industry Experience",
                "conversation_history": [
                    {"role": "user", "content": "字节跳动秋招什么时候投？"},
                ],
            },
        )

        payload = response.json()
        self.assertEqual(payload["intent"], "study_plan")
        self.assertIsNotNone(payload["study_plans"])

    def test_elliptical_follow_up_can_inherit_recruitment_intent(self) -> None:
        response = self.client.post(
            "/api/agent/chat",
            json={
                "message": "我 2027 年毕业",
                "conversation_history": [
                    {"role": "user", "content": "我该什么时候参加秋招？"},
                ],
            },
        )

        self.assertEqual(response.json()["intent"], "recruitment_qa")

    def test_searches_australian_terminology_with_source(self) -> None:
        response = self.client.post(
            "/api/terminology/search",
            json={
                "query": "Entry Level 1 是 master 第一年吗？",
                "k": 3,
            },
        )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["terms"][0]["term_id"], "entry-level")
        self.assertEqual(
            payload["answer_source"],
            "official_australian_terminology",
        )

    def test_health_exposes_liveness_and_readiness(self) -> None:
        live = self.client.get("/health/live")
        ready = self.client.get("/health/ready")

        self.assertEqual(live.json()["status"], "alive")
        self.assertEqual(ready.json()["status"], "ready")
        self.assertTrue(ready.json()["catalog_loaded"])
        self.assertTrue(ready.json()["retriever_ready"])

    def test_health_exposes_deployment_and_academic_coverage_models(self) -> None:
        payload = self.client.get("/health").json()

        self.assertEqual(payload["deployment_profile"], "lite")
        self.assertEqual(
            payload["academic_coverage"]["model"],
            "CATALOG -> STRUCTURED -> VERIFIED",
        )

    def test_coverage_endpoint_resolves_verified_program_override(self) -> None:
        response = self.client.get(
            "/api/coverage/capabilities",
            params={
                "university_id": "monash",
                "program_code": "c6001",
                "handbook_year": 2026,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["coverage"]["level"], "VERIFIED")
        self.assertTrue(
            response.json()["coverage"]["capabilities"][
                "deterministic_planning"
            ]
        )

    def test_vector_startup_failure_degrades_to_bm25(self) -> None:
        logs_dir = REPO_ROOT / "logs"
        with TemporaryDirectory(dir=logs_dir) as temp_dir:
            database = Path(temp_dir) / "vector-degraded.sqlite3"
            with (
                patch.dict(
                    "os.environ",
                    {
                        "CAMPUSPILOT_VECTOR_SEARCH_ENABLED": "1",
                        "CAMPUSPILOT_EMBEDDING_MODEL_PATH": "fake-model",
                    },
                ),
                patch(
                    "agent_runtime.api.create_dense_embedder",
                    return_value=object(),
                ),
                patch(
                    "agent_runtime.api.CampusPilotMilvusStore",
                    side_effect=RuntimeError("milvus unavailable"),
                ),
                TestClient(create_app(database_path=database)) as client,
            ):
                ready = client.get("/health/ready")
                evidence = client.post(
                    "/api/evidence/search",
                    json={"query": "C6001 学分要求", "k": 2},
                )

        payload = ready.json()
        self.assertEqual(ready.status_code, 200)
        self.assertTrue(payload["retriever_ready"])
        self.assertTrue(payload["vector_search_requested"])
        self.assertFalse(payload["vector_search_enabled"])
        self.assertTrue(payload["vector_search_degraded"])
        self.assertEqual(payload["vector_search_error"], "RuntimeError")
        self.assertEqual(evidence.status_code, 200)

    def test_hybrid_runtime_exposes_reranked_retrieval_mode(self) -> None:
        class FakeVectorStore:
            def search(self, query, **kwargs):
                return []

        class FakeReranker:
            def rerank(self, query, documents):
                return documents

        logs_dir = REPO_ROOT / "logs"
        with TemporaryDirectory(dir=logs_dir) as temp_dir:
            database = Path(temp_dir) / "hybrid-reranked.sqlite3"
            with (
                patch.dict(
                    "os.environ",
                    {
                        "CAMPUSPILOT_RETRIEVAL_MODE": "hybrid",
                        "CAMPUSPILOT_VECTOR_SEARCH_ENABLED": "1",
                        "CAMPUSPILOT_EMBEDDING_MODEL_PATH": "embedding-model",
                        "CAMPUSPILOT_RERANKER_ENABLED": "1",
                        "CAMPUSPILOT_RERANKER_MODEL_PATH": "reranker-model",
                    },
                ),
                patch(
                    "agent_runtime.api.create_dense_embedder",
                    return_value=object(),
                ),
                patch(
                    "agent_runtime.api.CampusPilotMilvusStore",
                    return_value=FakeVectorStore(),
                ),
                patch(
                    "agent_runtime.api.SentenceTransformerReranker",
                    return_value=FakeReranker(),
                ),
                patch(
                    "agent_runtime.api.read_chunks",
                    return_value=[
                        HandbookChunk(
                            chunk_id="hybrid-1",
                            parent_id="hybrid-parent",
                            source_id="hybrid-source",
                            university_id="monash",
                            handbook_year=2026,
                            program_code="B6022",
                            source_type="program_handbook",
                            discipline_ids=["business"],
                            title="Business Analytics",
                            heading="Structure",
                            content="Business analytics structure.",
                            parent_content="Official business analytics structure.",
                            source_url="https://example.edu/b6022",
                            source_sha256="abc",
                            program_codes=["B6022"],
                        )
                    ],
                ),
                TestClient(create_app(database_path=database)) as client,
            ):
                health = client.get("/health")
                ready = client.get("/health/ready")

        payload = health.json()
        self.assertEqual(
            payload["retrieval_mode"],
            "bm25_sentence_transformer_milvus_rrf_reranked",
        )
        self.assertTrue(ready.json()["vector_search_enabled"])

    def test_elasticsearch_runtime_exposes_lexical_health(self) -> None:
        class FakeElasticsearchStore:
            def __init__(self, **kwargs):
                self.options = kwargs

            def ensure_ready(self):
                return None

            def search(self, query, **kwargs):
                return []

        chunk = HandbookChunk(
            chunk_id="fit9136-1",
            parent_id="fit9136-parent",
            source_id="monash-fit9136-2026",
            university_id="monash",
            handbook_year=2026,
            program_code="C6001",
            source_type="unit_handbook",
            discipline_ids=["computing"],
            title="FIT9136 Introduction to Python programming",
            heading="Availability",
            content="FIT9136 is available in Semester 2.",
            parent_content="Official FIT9136 availability evidence.",
            source_url="https://example.edu/fit9136",
            source_sha256="abc",
            program_codes=["C6001"],
        )
        logs_dir = REPO_ROOT / "logs"
        with TemporaryDirectory(dir=logs_dir) as temp_dir:
            database = Path(temp_dir) / "elasticsearch-active.sqlite3"
            with (
                patch.dict(
                    "os.environ",
                    {
                        "CAMPUSPILOT_VECTOR_SEARCH_ENABLED": "0",
                        "CAMPUSPILOT_LEXICAL_BACKEND": "elasticsearch",
                        "ELASTICSEARCH_URL": "http://elasticsearch:9200",
                        "ELASTICSEARCH_INDEX": "handbook-test",
                    },
                ),
                patch(
                    "agent_runtime.api.ElasticsearchHandbookStore",
                    FakeElasticsearchStore,
                ),
                patch("agent_runtime.api.read_chunks", return_value=[chunk]),
                TestClient(create_app(database_path=database)) as client,
            ):
                health = client.get("/health")
                ready = client.get("/health/ready")

        self.assertEqual(health.json()["retrieval_mode"], "elasticsearch_bm25")
        self.assertEqual(
            health.json()["lexical_search_backend"],
            "elasticsearch",
        )
        self.assertTrue(ready.json()["lexical_search_enabled"])
        self.assertFalse(ready.json()["lexical_search_degraded"])

    def test_elasticsearch_startup_failure_degrades_to_memory_bm25(self) -> None:
        chunk = HandbookChunk(
            chunk_id="fit9136-1",
            parent_id="fit9136-parent",
            source_id="monash-fit9136-2026",
            university_id="monash",
            handbook_year=2026,
            program_code="C6001",
            source_type="unit_handbook",
            discipline_ids=["computing"],
            title="FIT9136 Introduction to Python programming",
            heading="Availability",
            content="FIT9136 is available in Semester 2.",
            parent_content="Official FIT9136 availability evidence.",
            source_url="https://example.edu/fit9136",
            source_sha256="abc",
            program_codes=["C6001"],
        )
        logs_dir = REPO_ROOT / "logs"
        with TemporaryDirectory(dir=logs_dir) as temp_dir:
            database = Path(temp_dir) / "elasticsearch-degraded.sqlite3"
            with (
                patch.dict(
                    "os.environ",
                    {
                        "CAMPUSPILOT_VECTOR_SEARCH_ENABLED": "0",
                        "CAMPUSPILOT_LEXICAL_BACKEND": "elasticsearch",
                        "ELASTICSEARCH_URL": "http://elasticsearch:9200",
                    },
                ),
                patch(
                    "agent_runtime.api.ElasticsearchHandbookStore",
                    side_effect=ConnectionError("elasticsearch unavailable"),
                ),
                patch("agent_runtime.api.read_chunks", return_value=[chunk]),
                TestClient(create_app(database_path=database)) as client,
            ):
                ready = client.get("/health/ready")

        payload = ready.json()
        self.assertEqual(ready.status_code, 200)
        self.assertTrue(payload["retriever_ready"])
        self.assertTrue(payload["lexical_search_requested"])
        self.assertFalse(payload["lexical_search_enabled"])
        self.assertTrue(payload["lexical_search_degraded"])
        self.assertEqual(payload["lexical_search_error"], "ConnectionError")

    def test_full_bm25_mode_uses_runtime_handbook_chunks(self) -> None:
        chunk = HandbookChunk(
            chunk_id="business-1",
            parent_id="business-parent",
            source_id="monash-b6022-2026",
            university_id="monash",
            handbook_year=2026,
            program_code="B6022",
            source_type="program_handbook",
            discipline_ids=["business"],
            title="Master of Business Analytics",
            heading="Course structure",
            content="B6022 business analytics course structure.",
            parent_content="Official business analytics course structure.",
            source_url="https://example.edu/b6022",
            source_sha256="abc",
            program_codes=["B6022"],
        )
        logs_dir = REPO_ROOT / "logs"
        with TemporaryDirectory(dir=logs_dir) as temp_dir:
            database = Path(temp_dir) / "full-bm25.sqlite3"
            with (
                patch.dict(
                    "os.environ",
                    {
                        "CAMPUSPILOT_RETRIEVAL_MODE": "full_bm25",
                        "CAMPUSPILOT_VECTOR_SEARCH_ENABLED": "0",
                    },
                ),
                patch(
                    "agent_runtime.api.read_chunks",
                    return_value=[
                        chunk,
                        HandbookChunk(
                            **{
                                **chunk.to_dict(),
                                "chunk_id": "computing-1",
                                "parent_id": "computing-parent",
                                "source_id": "monash-c6001-2026",
                                "program_code": "C6001",
                                "discipline_ids": ["computing"],
                                "title": "Master of Information Technology",
                                "content": "C6001 information technology degree.",
                                "parent_content": "Official C6001 structure.",
                                "program_codes": ["C6001"],
                            }
                        ),
                        HandbookChunk(
                            **{
                                **chunk.to_dict(),
                                "chunk_id": "engineering-1",
                                "parent_id": "engineering-parent",
                                "source_id": "monash-e6001-2026",
                                "program_code": "E6001",
                                "discipline_ids": ["engineering"],
                                "title": "Master of Engineering",
                                "content": "E6001 engineering degree requirements.",
                                "parent_content": "Official E6001 structure.",
                                "program_codes": ["E6001"],
                            }
                        ),
                    ],
                ),
                TestClient(create_app(database_path=database)) as client,
            ):
                health = client.get("/health")
                evidence = client.post(
                    "/api/evidence/search",
                    json={
                        "query": "B6022 business analytics course structure",
                        "university_id": "monash",
                        "discipline_id": "business",
                        "program_code": "B6022",
                        "handbook_year": 2026,
                    },
                )

        self.assertEqual(health.json()["retrieval_mode"], "full_corpus_bm25")
        self.assertEqual(evidence.json()["count"], 1)
        self.assertEqual(
            evidence.json()["answer_source"],
            "full_corpus_bm25",
        )


if __name__ == "__main__":
    unittest.main()
