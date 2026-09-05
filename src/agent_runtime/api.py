"""FastAPI composition root for CampusPilot product and agent capabilities."""

from contextlib import asynccontextmanager
from dataclasses import dataclass
import hmac
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import time
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import (
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Path as ApiPath,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from .approval_service import (
    ApprovalService,
    ThreadConflictError,
    ThreadNotFoundError,
    ThreadOwnershipRepository,
)
from .approval_workflow import LangGraphApprovalWorkflow
from .admin_config import EnvironmentConfigStore, env_flag
from .deployment_profiles import resolve_deployment_profile
from .anonymous_session import AnonymousSessionRepository
from .campuspilot import (
    CampusPilotCatalog,
    CampusPilotConversationAgent,
    CampusPilotEvidenceRetriever,
    CampusPilotPlanningAgent,
)
from .campuspilot_conversation_graph import CampusPilotConversationGraph
from .handbook_vector import (
    CampusPilotHybridRetriever,
    CampusPilotMilvusStore,
    SentenceTransformerReranker,
    create_dense_embedder,
    read_chunks,
)
from .handbook_qa import HandbookQuestionAnsweringAgent, HandbookQueryRewriter
from .retrieval import (
    ElasticsearchHandbookStore,
    EvidenceRetriever,
    FallbackLexicalRetriever,
    InMemoryBM25Retriever,
    RetrievalRequest,
    RetrievalScope,
    RetrievalScopeResolver,
)
from .semester_advisor import create_semester_advice_agent_with_cloud
from .openai_compatible_client import OpenAICompatibleChatClient
from .llm_errors import (
    CampusPilotLLMError,
    LLMErrorCategory,
    llm_error_http_status,
)
from .planning_goal_interpreter import CloudPlanningGoalInterpreter
from .program_recommendation_interpreter import (
    CloudRecommendationProfileInterpreter,
)
from .program_recommendation_narrator import ProgramRecommendationNarrator
from .rate_limit import InMemoryRateLimiter
from .runtime_context import bind_request_id, current_request_id, reset_request_id
from .runtime_logging import log_event, runtime_logger
from .plan_narrator import StudyPlanNarrator
from .australian_terminology import AustralianTerminologyGlossary
from .recruitment_knowledge import (
    ChinaRecruitmentKnowledgeBase,
    RecruitmentQuestionAnsweringAgent,
)
from campuspilot_core.admission_mvp import AdmissionMvpService
from campuspilot_core.coverage import AcademicCoverageRegistry
from campuspilot_core.institution_catalog import InstitutionCatalog
from campuspilot_core.program_recommendation import ProgramRecommendationService
from campuspilot_core.transcript_parser import (
    TranscriptParseService,
    TranscriptValidationError,
)


FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
REPO_ROOT = FRONTEND_DIR.parent
RUNTIME_LOGGER = runtime_logger("api")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


@dataclass(frozen=True)
class EvidenceRetrieverRuntime:
    """Configured retrieval capabilities plus safe degradation diagnostics.

    Requested and active states are separate because optional infrastructure
    may be configured yet unavailable during startup or a later request.
    """
    retriever: EvidenceRetriever
    vector_requested: bool
    vector_error: str | None = None
    retrieval_mode: str = "catalog_bm25"
    lexical_requested: bool = False
    lexical_backend: str = "catalog_bm25"
    lexical_error: str | None = None

    @property
    def vector_active(self) -> bool:
        return (
            isinstance(self.retriever, CampusPilotHybridRetriever)
            and self.retriever.vector_store is not None
        )

    @property
    def vector_degraded(self) -> bool:
        return self.vector_requested and not self.vector_active

    @property
    def lexical_search_error(self) -> str | None:
        lexical = getattr(self.retriever, "lexical_retriever", None)
        return self.lexical_error or getattr(lexical, "last_error", None)

    @property
    def lexical_active(self) -> bool:
        return (
            self.lexical_requested
            and self.lexical_backend == "elasticsearch"
            and self.lexical_search_error is None
        )

    @property
    def lexical_degraded(self) -> bool:
        return self.lexical_requested and not self.lexical_active


class ActionRequest(BaseModel):
    tool_name: str = Field(min_length=1, max_length=100)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ResumeRequest(BaseModel):
    approved: bool


class AdminConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cloud_llm_enabled: bool | None = None
    openai_base_url: str | None = Field(default=None, min_length=1, max_length=500)
    openai_model: str | None = Field(default=None, min_length=1, max_length=200)
    api_key: SecretStr | None = None
    openai_timeout_seconds: float | None = Field(
        default=None,
        ge=1,
        le=300,
    )
    retrieval_mode: Literal["catalog_bm25", "full_bm25", "hybrid"] | None = None
    vector_search_enabled: bool | None = None
    reranker_enabled: bool | None = None
    rate_limit_per_minute: int | None = Field(default=None, ge=0, le=10000)
    max_upload_bytes: int | None = Field(
        default=None,
        ge=1024,
        le=100 * 1024 * 1024,
    )

    @field_validator("openai_base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("https://"):
            raise ValueError("OpenAI-compatible Base URL must use HTTPS")
        return value.rstrip("/") if value else value


class AdminLlmTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=1000)
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    max_tokens: int = Field(default=128, ge=1, le=2048)


class ProgramComparisonRequest(BaseModel):
    first_program_variant_id: str = Field(min_length=1)
    second_program_variant_id: str = Field(min_length=1)
    handbook_year: int = Field(default=2026, ge=2020, le=2100)
    study_stream: str = Field(min_length=1)


class CourseRoleRequest(BaseModel):
    program_variant_id: str = Field(min_length=1)
    handbook_year: int = Field(default=2026, ge=2020, le=2100)
    study_stream: str = Field(min_length=1)
    course_code: str = Field(min_length=1)


class StudyPlanRequest(BaseModel):
    program_variant_id: str = Field(min_length=1)
    handbook_year: int = Field(default=2026, ge=2020, le=2100)
    study_stream: str = Field(min_length=1)
    completed_courses: list[str] = Field(default_factory=list)
    max_courses_per_semester: int = Field(default=4, ge=1, le=4)
    preserve_policy_flexibility: bool = False
    start_semester: str = Field(
        default="2026-S2",
        pattern=r"^\d{4}-S[12]$",
    )
    semester_course_limits: dict[
        Annotated[str, Field(pattern=r"^\d{4}-S[12]$")],
        Literal[0, 2, 3, 4],
    ] = Field(default_factory=dict)
    planning_goal: Literal[
        "compare_options",
        "fastest_completion",
        "internship_priority",
        "study_internship_balance",
        "workload_balance",
        "policy_flexibility",
    ] = "compare_options"


class SemesterAdviceRequest(StudyPlanRequest):
    plan_id: str = Field(pattern=r"^(fastest|balanced|flexible|custom)$")
    semester: str = Field(pattern=r"^\d{4} S[12]$")


class DegreeProgressRequest(BaseModel):
    program_variant_id: str = Field(min_length=1)
    handbook_year: int = Field(default=2026, ge=2020, le=2100)
    study_stream: str = Field(min_length=1)
    completed_courses: list[str] = Field(default_factory=list)


class AgentChatRequest(BaseModel):
    thread_id: str | None = Field(default=None, min_length=8, max_length=128)
    message: str = Field(min_length=1, max_length=4000)
    program_variant_id: str | None = Field(default=None, max_length=128)
    handbook_year: int = Field(default=2026, ge=2020, le=2100)
    study_stream: str | None = Field(default=None, max_length=128)
    completed_courses: list[str] = Field(default_factory=list, max_length=100)
    max_courses_per_semester: int = Field(default=4, ge=1, le=4)
    preserve_policy_flexibility: bool = False
    start_semester: str = Field(
        default="2026-S2",
        pattern=r"^\d{4}-S[12]$",
    )
    conversation_history: list["AgentChatMessage"] = Field(
        default_factory=list,
        max_length=6,
    )


class AgentChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class EvidenceSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    handbook_year: int = Field(default=2026, ge=2020, le=2100)
    university_id: str | None = None
    discipline_id: str | None = None
    program_code: str | None = None
    specialisation_code: str | None = None
    source_type: str | None = None
    k: int = Field(default=3, ge=1, le=10)


class TerminologySearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    k: int = Field(default=5, ge=1, le=10)


class AdmissionEvaluationRequest(BaseModel):
    university: str = Field(min_length=1)
    program: str = ""
    requested_study_level: Literal[
        "COURSEWORK_MASTER",
        "RESEARCH_DEGREE",
        "UNDERGRADUATE",
    ] = "COURSEWORK_MASTER"
    discipline_id: str | None = None
    undergraduate_institution: str | None = None
    undergraduate_major: str | None = None
    score_value: float | None = Field(default=None, ge=0)
    score_scale: float | None = Field(default=None, gt=0)
    score_basis: (
        Literal[
            "RAW_PERCENT",
            "GPA",
            "OFFICIAL_EQUIVALENT_PERCENT",
        ]
        | None
    ) = None
    prior_coursework: list[str] = Field(default_factory=list)
    completed_credits: float | None = Field(default=None, ge=0)
    total_credits: float | None = Field(default=None, gt=0)
    expected_graduation: str | None = None


class ProgramRecommendationRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    university: str | None = Field(default=None, max_length=200)
    undergraduate_major: str | None = Field(default=None, max_length=200)
    career_goal: str | None = Field(default=None, max_length=500)
    personality: str | None = Field(default=None, max_length=500)
    preferences: str | None = Field(default=None, max_length=500)
    score_value: float | None = Field(default=None, ge=0)
    score_scale: float | None = Field(default=None, gt=0)
    max_results: int = Field(default=3, ge=1, le=5)


class RemainingAverageRequest(BaseModel):
    current_average: float | None = Field(default=None, ge=0, le=100)
    target_final_average: float | None = Field(default=None, ge=0, le=100)
    completed_credits: float | None = Field(default=None, ge=0)
    total_credits: float | None = Field(default=None, gt=0)


def _create_evidence_retriever(
    catalog: CampusPilotCatalog,
) -> EvidenceRetrieverRuntime:
    """Initialize lexical, dense, and reranking capabilities independently."""
    retrieval_mode = os.environ.get(
        "CAMPUSPILOT_RETRIEVAL_MODE",
        "",
    ).strip().lower()
    deployment = resolve_deployment_profile(os.environ)
    enabled = os.environ.get(
        "CAMPUSPILOT_VECTOR_SEARCH_ENABLED",
        "1" if deployment.vector_search_enabled else "0",
    ).lower() in {"1", "true", "yes"}
    fallback = CampusPilotEvidenceRetriever(
        catalog.data.get("official_documents", [])
    )
    elasticsearch_url = os.environ.get("ELASTICSEARCH_URL", "").strip()
    lexical_backend = os.environ.get(
        "CAMPUSPILOT_LEXICAL_BACKEND",
        deployment.lexical_backend,
    ).strip().lower()
    lexical_requested = lexical_backend == "elasticsearch"

    if retrieval_mode == "full_bm25" and not lexical_requested:
        return EvidenceRetrieverRuntime(
            retriever=CampusPilotHybridRetriever(
                chunks=read_chunks(),
                vector_store=None,
            ),
            vector_requested=False,
            retrieval_mode="full_corpus_bm25",
            lexical_backend="memory_bm25",
        )
    if not enabled and not lexical_requested:
        return EvidenceRetrieverRuntime(
            retriever=fallback,
            vector_requested=False,
            retrieval_mode="catalog_bm25",
        )

    # The published chunk corpus is the common local fallback and the shared
    # identity source for Elasticsearch and Milvus.
    try:
        chunks = read_chunks()
        memory_lexical = InMemoryBM25Retriever(chunks)
    except Exception as exc:
        log_event(
            RUNTIME_LOGGER,
            "retrieval_degraded",
            level=logging.WARNING,
            component="handbook_corpus",
            error_type=type(exc).__name__,
            fallback="catalog_bm25",
        )
        return EvidenceRetrieverRuntime(
            retriever=fallback,
            vector_requested=enabled,
            vector_error=type(exc).__name__ if enabled else None,
            retrieval_mode="catalog_bm25_degraded",
            lexical_requested=lexical_requested,
            lexical_backend="catalog_bm25",
            lexical_error=type(exc).__name__ if lexical_requested else None,
        )

    # Elasticsearch is canonical when configured. Wrapping it preserves an
    # in-process fallback for failures that happen after a healthy startup.
    lexical_retriever: Any = memory_lexical
    active_lexical_backend = "memory_bm25"
    lexical_error = None
    if lexical_requested:
        try:
            elasticsearch_store = ElasticsearchHandbookStore(
                url=elasticsearch_url or "http://127.0.0.1:9200",
                index_name=os.environ.get(
                    "ELASTICSEARCH_INDEX",
                    "campuspilot-handbook-v1",
                ),
                request_timeout=float(
                    os.environ.get("ELASTICSEARCH_TIMEOUT_SECONDS", "3")
                ),
            )
            elasticsearch_store.ensure_ready()
            lexical_retriever = FallbackLexicalRetriever(
                elasticsearch_store,
                memory_lexical,
            )
            active_lexical_backend = "elasticsearch"
        except Exception as exc:
            lexical_error = type(exc).__name__
            log_event(
                RUNTIME_LOGGER,
                "retrieval_degraded",
                level=logging.WARNING,
                component="elasticsearch",
                error_type=lexical_error,
                fallback="full_corpus_bm25",
            )

    if not enabled:
        return EvidenceRetrieverRuntime(
            retriever=CampusPilotHybridRetriever(
                chunks=chunks,
                vector_store=None,
                lexical_retriever=lexical_retriever,
            ),
            vector_requested=False,
            retrieval_mode=(
                "elasticsearch_bm25"
                if active_lexical_backend == "elasticsearch"
                else "full_corpus_bm25_degraded"
            ),
            lexical_requested=lexical_requested,
            lexical_backend=active_lexical_backend,
            lexical_error=lexical_error,
        )
    # Dense retrieval and reranking are initialized after lexical retrieval so
    # either component can degrade without discarding available BM25 evidence.
    try:
        backend = os.environ.get(
            "CAMPUSPILOT_EMBEDDING_BACKEND",
            "sentence-transformer",
        )
        model_path = os.environ.get("CAMPUSPILOT_EMBEDDING_MODEL_PATH")
        if not model_path:
            raise RuntimeError(
                "CAMPUSPILOT_EMBEDDING_MODEL_PATH is required when vector search is enabled"
            )
        embedder = create_dense_embedder(backend, model_path)
        vector_store = CampusPilotMilvusStore(
            uri=os.environ.get(
                "CAMPUSPILOT_MILVUS_URI",
                "http://127.0.0.1:19530",
            ),
            collection_name=os.environ.get(
                "CAMPUSPILOT_MILVUS_COLLECTION",
                "campuspilot_handbook_v2",
            ),
            embedder=embedder,
            canonical_chunks=chunks,
        )
        reranker = None
        reranker_enabled = os.environ.get(
            "CAMPUSPILOT_RERANKER_ENABLED",
            "1" if deployment.reranker_enabled else "0",
        ).lower() in {"1", "true", "yes"}
        if reranker_enabled:
            reranker_path = os.environ.get("CAMPUSPILOT_RERANKER_MODEL_PATH")
            if not reranker_path:
                raise RuntimeError(
                    "CAMPUSPILOT_RERANKER_MODEL_PATH is required when reranking is enabled"
                )
            reranker = SentenceTransformerReranker(reranker_path)
        return EvidenceRetrieverRuntime(
            retriever=CampusPilotHybridRetriever(
                chunks=chunks,
                vector_store=vector_store,
                reranker=reranker,
                lexical_retriever=lexical_retriever,
            ),
            vector_requested=True,
            retrieval_mode=(
                (
                    "elasticsearch_"
                    if active_lexical_backend == "elasticsearch"
                    else "bm25_"
                )
                + backend.replace("-", "_")
                + "_milvus_rrf"
                + ("_reranked" if reranker is not None else "")
            ),
            lexical_requested=lexical_requested,
            lexical_backend=active_lexical_backend,
            lexical_error=lexical_error,
        )
    except Exception as exc:
        log_event(
            RUNTIME_LOGGER,
            "retrieval_degraded",
            level=logging.WARNING,
            component="vector_retrieval",
            error_type=type(exc).__name__,
            fallback="full_corpus_bm25",
        )
        try:
            full_bm25 = CampusPilotHybridRetriever(
                chunks=chunks,
                vector_store=None,
                lexical_retriever=lexical_retriever,
            )
            return EvidenceRetrieverRuntime(
                retriever=full_bm25,
                vector_requested=True,
                vector_error=type(exc).__name__,
                retrieval_mode=(
                    "elasticsearch_bm25_vector_degraded"
                    if active_lexical_backend == "elasticsearch"
                    else "full_corpus_bm25_degraded"
                ),
                lexical_requested=lexical_requested,
                lexical_backend=active_lexical_backend,
                lexical_error=lexical_error,
            )
        except Exception as fallback_exc:
            log_event(
                RUNTIME_LOGGER,
                "retrieval_degraded",
                level=logging.WARNING,
                component="full_corpus_bm25",
                error_type=type(fallback_exc).__name__,
                fallback="catalog_bm25",
            )
        return EvidenceRetrieverRuntime(
            retriever=fallback,
            vector_requested=True,
            vector_error=type(exc).__name__,
            retrieval_mode="catalog_bm25_degraded",
            lexical_requested=lexical_requested,
            lexical_backend="catalog_bm25",
            lexical_error=lexical_error,
        )


def create_app(
    database_path: str | Path = "logs/day35-agent-api.sqlite3",
    token_to_user: dict[str, str] | None = None,
    semester_advisor: Any | None = None,
    transcript_service: TranscriptParseService | None = None,
) -> FastAPI:
    database = Path(database_path)
    if token_to_user is not None:
        tokens = dict(token_to_user)
    else:
        configured_tokens = os.environ.get("CAMPUSPILOT_API_TOKENS_JSON")
        if configured_tokens:
            parsed_tokens = json.loads(configured_tokens)
            if not isinstance(parsed_tokens, dict) or not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in parsed_tokens.items()
            ):
                raise ValueError(
                    "CAMPUSPILOT_API_TOKENS_JSON must be a string mapping"
                )
            tokens = parsed_tokens
        elif os.environ.get("CAMPUSPILOT_ENV", "development") == "production":
            tokens = {}
        else:
            tokens = {
                "alice-demo-token": "alice",
                "bob-demo-token": "bob",
            }
    bearer = HTTPBearer(auto_error=False)
    max_upload_bytes = int(
        os.environ.get("CAMPUSPILOT_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024))
    )
    if max_upload_bytes <= 0:
        raise ValueError("CAMPUSPILOT_MAX_UPLOAD_BYTES must be positive")
    rate_limit_per_minute = int(
        os.environ.get("CAMPUSPILOT_RATE_LIMIT_PER_MINUTE", "0")
    )
    rate_limiter = (
        InMemoryRateLimiter(limit=rate_limit_per_minute)
        if rate_limit_per_minute > 0
        else None
    )
    admin_enabled = env_flag("CAMPUSPILOT_ADMIN_ENABLED")
    admin_local_only = env_flag("CAMPUSPILOT_ADMIN_LOCAL_ONLY", default=True)
    admin_token = os.environ.get("CAMPUSPILOT_ADMIN_TOKEN", "")
    if admin_enabled and not admin_token:
        raise ValueError(
            "CAMPUSPILOT_ADMIN_TOKEN is required when local admin is enabled"
        )
    env_file = Path(
        os.environ.get("CAMPUSPILOT_ENV_FILE", str(REPO_ROOT / ".env"))
    )
    config_store = EnvironmentConfigStore(env_file)
    deployment = resolve_deployment_profile(os.environ)
    campus_catalog = CampusPilotCatalog()
    academic_coverage = AcademicCoverageRegistry.from_path()
    retrieval_scope_resolver = RetrievalScopeResolver()
    admission_service = AdmissionMvpService()
    institution_catalog = InstitutionCatalog()
    transcript_parser = transcript_service or TranscriptParseService()
    terminology = AustralianTerminologyGlossary()
    retriever_runtime = _create_evidence_retriever(campus_catalog)
    evidence_retriever = retriever_runtime.retriever
    planning_agent = CampusPilotPlanningAgent(
        campus_catalog,
        evidence_retriever=evidence_retriever,
    )
    cloud_llm_enabled = os.environ.get(
        "CAMPUSPILOT_CLOUD_LLM_ENABLED",
        "0",
    ).lower() in {"1", "true", "yes"}
    cloud_client = (
        OpenAICompatibleChatClient.from_environment() if cloud_llm_enabled else None
    )
    goal_interpreter = (
        CloudPlanningGoalInterpreter(cloud_client) if cloud_client is not None else None
    )
    recommendation_service = ProgramRecommendationService(
        admission_service,
        profile_interpreter=(
            CloudRecommendationProfileInterpreter(cloud_client)
            if cloud_client is not None
            else None
        ),
        narrator=ProgramRecommendationNarrator(cloud_client),
    )
    handbook_qa_agent = HandbookQuestionAnsweringAgent(
        evidence_retriever,
        client=cloud_client,
        query_rewriter=(
            HandbookQueryRewriter(cloud_client) if cloud_client is not None else None
        ),
    )
    conversation_agent = CampusPilotConversationGraph(
        CampusPilotConversationAgent(
            campus_catalog,
            planning_agent,
            goal_interpreter,
            terminology,
            handbook_qa_agent,
            StudyPlanNarrator(cloud_client),
            recruitment_agent=RecruitmentQuestionAnsweringAgent(
                ChinaRecruitmentKnowledgeBase(),
                cloud_client,
            ),
            program_recommendation_service=recommendation_service,
        ),
    )
    semester_advice_agent = semester_advisor or create_semester_advice_agent_with_cloud(
        cloud_client
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            database,
            check_same_thread=False,
        )
        conversation_database = database.with_name(
            f"{database.stem}-conversation{database.suffix}"
        )
        conversation_connection = sqlite3.connect(
            conversation_database,
            check_same_thread=False,
        )
        try:
            saver = SqliteSaver(connection)
            conversation_agent.configure_checkpointer(
                SqliteSaver(conversation_connection)
            )
            app.state.approval_service = ApprovalService(
                workflow=LangGraphApprovalWorkflow(checkpointer=saver),
                owners=ThreadOwnershipRepository(connection),
            )
            app.state.session_repository = AnonymousSessionRepository(
                connection,
                ttl_seconds=int(
                    os.environ.get(
                        "CAMPUSPILOT_SESSION_TTL_SECONDS",
                        "86400",
                    )
                ),
            )
            yield
        finally:
            conversation_connection.close()
            connection.close()

    app = FastAPI(
        title="CampusPilot Agent API",
        description=("海外高校项目比较、课程角色判断、毕业路径规划与用户确认。"),
        version="0.2.0",
        lifespan=lifespan,
    )
    app.state.cloud_client = cloud_client
    app.state.config_store = config_store
    app.state.started_at = time.monotonic()
    cors_origins = [
        value.strip()
        for value in os.environ.get(
            "CAMPUSPILOT_CORS_ORIGINS",
            "http://127.0.0.1:18082,http://localhost:18082",
        ).split(",")
        if value.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(CampusPilotLLMError)
    async def handle_llm_error(
        request: Request,
        exc: CampusPilotLLMError,
    ) -> JSONResponse:
        request_id = current_request_id() or getattr(
            request.state,
            "request_id",
            uuid4().hex,
        )
        log_event(
            RUNTIME_LOGGER,
            "application_error_returned",
            level=logging.ERROR,
            path=request.url.path,
            error_category=exc.category.value,
            error_code=exc.public_code,
            provider=exc.provider,
            model=exc.model,
        )
        return JSONResponse(
            status_code=llm_error_http_status(exc),
            content={
                "error": {
                    "code": exc.public_code,
                    "message": exc.public_message,
                    "request_id": request_id,
                }
            },
        )

    expensive_paths = {
        "/api/session",
        "/api/agent/chat",
        "/api/plans/semesters/explain",
        "/api/admissions/recommend",
        "/api/admissions/transcripts/parse",
    }

    @app.middleware("http")
    async def runtime_request_middleware(request: Request, call_next):
        supplied_request_id = request.headers.get("X-Request-ID", "").strip()
        request_id = (
            supplied_request_id
            if REQUEST_ID_PATTERN.fullmatch(supplied_request_id)
            else uuid4().hex
        )
        token = bind_request_id(request_id)
        started_at = time.perf_counter()
        method = request.method
        path = request.url.path
        request.state.request_id = request_id
        log_event(
            RUNTIME_LOGGER,
            "request_started",
            method=method,
            path=path,
        )
        try:
            if (
                rate_limiter is not None
                and method == "POST"
                and path in expensive_paths
            ):
                client_host = request.client.host if request.client else "unknown"
                allowed, retry_after = rate_limiter.allow(
                    f"{client_host}:{path}"
                )
                if not allowed:
                    response = JSONResponse(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        content={"detail": "request rate limit exceeded"},
                        headers={"Retry-After": str(retry_after)},
                    )
                else:
                    response = await call_next(request)
            else:
                response = await call_next(request)
        except Exception as exc:
            duration_ms = round((time.perf_counter() - started_at) * 1000, 1)
            log_event(
                RUNTIME_LOGGER,
                "request_failed",
                level=logging.ERROR,
                method=method,
                path=path,
                duration_ms=duration_ms,
                error_type=type(exc).__name__,
                error_category="application_error",
            )
            raise
        else:
            duration_ms = round((time.perf_counter() - started_at) * 1000, 1)
            response.headers["X-Request-ID"] = request_id
            log_event(
                RUNTIME_LOGGER,
                "request_completed",
                level=(
                    logging.WARNING
                    if response.status_code >= 500
                    else logging.INFO
                ),
                method=method,
                path=path,
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
            return response
        finally:
            reset_request_id(token)

    # Keep the public URL stable while the repository uses an explicit frontend/
    # production boundary.
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    def current_user(
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Depends(bearer),
        ],
    ) -> str:
        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user_id = tokens.get(credentials.credentials)
        if user_id is None:
            user_id = app.state.session_repository.resolve(
                credentials.credentials
            )
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return user_id

    def service() -> ApprovalService:
        return app.state.approval_service

    def require_admin(
        request: Request,
        supplied_token: Annotated[
            str | None,
            Header(alias="X-CampusPilot-Admin-Token"),
        ] = None,
    ) -> None:
        if not admin_enabled:
            raise HTTPException(status_code=404, detail="local admin is disabled")
        host = request.client.host if request.client else ""
        if admin_local_only and host not in {"127.0.0.1", "::1", "localhost"}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="local admin only accepts loopback requests",
            )
        if supplied_token is None or not hmac.compare_digest(
            supplied_token,
            admin_token,
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid admin token",
            )

    @app.get("/", include_in_schema=False)
    def root() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")

    @app.get("/admin", include_in_schema=False)
    def admin_page(request: Request) -> FileResponse:
        if not admin_enabled:
            raise HTTPException(status_code=404, detail="local admin is disabled")
        host = request.client.host if request.client else ""
        if admin_local_only and host not in {"127.0.0.1", "::1", "localhost"}:
            raise HTTPException(status_code=404, detail="local admin is unavailable")
        return FileResponse(FRONTEND_DIR / "admin.html")

    @app.get("/api/admin/config", include_in_schema=False)
    def get_admin_config(
        _: Annotated[None, Depends(require_admin)],
    ) -> dict[str, Any]:
        config = config_store.public_config()
        runtime_client = app.state.cloud_client
        return {
            "config": config,
            "runtime": {
                "llm_client_active": runtime_client is not None,
                "model": runtime_client.model if runtime_client is not None else None,
                "base_url": (
                    runtime_client.base_url if runtime_client is not None else None
                ),
                "restart_note": (
                    "检索、Reranker、限流、上传限制和 LLM 开关需重启服务。"
                ),
            },
        }

    @app.put("/api/admin/config", include_in_schema=False)
    def update_admin_config(
        update: AdminConfigUpdate,
        _: Annotated[None, Depends(require_admin)],
    ) -> dict[str, Any]:
        before = config_store.public_config()
        payload = update.model_dump(exclude_none=True, exclude={"api_key"})
        api_key = update.api_key.get_secret_value() if update.api_key else None
        try:
            config_store.update(payload, api_key=api_key)
        except (OSError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
        after = config_store.public_config()
        changed_fields = [
            field
            for field in payload
            if before.get(field) != after.get(field)
        ]
        if api_key:
            changed_fields.append("api_key")
        restart_fields = {
            "cloud_llm_enabled",
            "retrieval_mode",
            "vector_search_enabled",
            "reranker_enabled",
            "rate_limit_per_minute",
            "max_upload_bytes",
        }
        restart_required = sorted(restart_fields.intersection(changed_fields))
        hot_applied: list[str] = []
        runtime_client = app.state.cloud_client
        live_fields = {
            "openai_base_url",
            "openai_model",
            "openai_timeout_seconds",
            "api_key",
        }
        requested_live_fields = live_fields.intersection(changed_fields)
        if requested_live_fields and runtime_client is not None:
            try:
                runtime_client.reconfigure(
                    api_key=(api_key if api_key else None),
                    base_url=after["openai_base_url"],
                    model=after["openai_model"],
                    timeout_seconds=after["openai_timeout_seconds"],
                )
                hot_applied = sorted(requested_live_fields)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=str(exc),
                ) from exc
        elif requested_live_fields:
            restart_required.extend(sorted(requested_live_fields))
        return {
            "saved": True,
            "config": after,
            "hot_applied_fields": hot_applied,
            "restart_required_fields": sorted(set(restart_required)),
            "message": (
                "配置已保存；标记字段需重启服务后生效。"
                if restart_required
                else "配置已保存并应用到当前模型客户端。"
            ),
        }

    @app.post("/api/admin/llm/test", include_in_schema=False)
    def test_admin_llm(
        test: AdminLlmTestRequest,
        _: Annotated[None, Depends(require_admin)],
    ) -> dict[str, Any]:
        try:
            client = OpenAICompatibleChatClient.from_environment()
            started = time.perf_counter()
            result = client.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是 CampusPilot 配置测试助手。请用简体中文简短回答，"
                            "不要调用工具，不要补充未提供的事实。"
                        ),
                    },
                    {"role": "user", "content": test.prompt},
                ],
                temperature=test.temperature,
                max_tokens=test.max_tokens,
            )
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        except CampusPilotLLMError:
            raise
        except Exception as exc:
            raise CampusPilotLLMError(
                category=LLMErrorCategory.UNKNOWN,
                provider="openai_compatible",
                detail_type=type(exc).__name__,
            ) from exc
        content = result["message"].get("content")
        return {
            "ok": True,
            "content": content if isinstance(content, str) else "",
            "model": result.get("model"),
            "usage": result.get("usage", {}),
            "elapsed_ms": elapsed_ms,
        }

    @app.get("/health")
    def health() -> dict[str, Any]:
        git_sha = os.environ.get("CAMPUSPILOT_GIT_SHA", "unknown")
        return {
            "status": "ok",
            "product": "CampusPilot",
            "version": app.version,
            "commit": git_sha[:12] if git_sha != "unknown" else git_sha,
            "environment": os.environ.get("CAMPUSPILOT_ENV", "development"),
            "deployment_profile": deployment.profile.value,
            "academic_coverage": academic_coverage.summary(),
            "uptime_seconds": round(time.monotonic() - app.state.started_at, 1),
            "data_mode": campus_catalog.data["data_mode"],
            "retrieval_mode": (
                retriever_runtime.retrieval_mode
            ),
            "goal_interpreter": (
                "cloud_openai_compatible" if cloud_llm_enabled else "deterministic"
            ),
            "cloud_llm_enabled": cloud_llm_enabled,
            "llm_provider": (
                cloud_client.provider_name
                if cloud_client is not None
                else None
            ),
            "llm_model": cloud_client.model if cloud_client is not None else None,
            "vector_search_enabled": retriever_runtime.vector_active,
            "lexical_search_backend": retriever_runtime.lexical_backend,
            "lexical_search_degraded": retriever_runtime.lexical_degraded,
        }

    @app.get("/health/live")
    def liveness() -> dict[str, str]:
        return {"status": "alive", "product": "CampusPilot"}

    @app.get("/health/ready")
    def readiness() -> dict[str, Any]:
        return {
            "status": "ready",
            "product": "CampusPilot",
            "catalog_loaded": bool(campus_catalog.data),
            "retriever_ready": evidence_retriever is not None,
            "vector_search_enabled": retriever_runtime.vector_active,
            "vector_search_requested": retriever_runtime.vector_requested,
            "vector_search_degraded": retriever_runtime.vector_degraded,
            "vector_search_error": retriever_runtime.vector_error,
            "lexical_search_enabled": retriever_runtime.lexical_active,
            "lexical_search_requested": retriever_runtime.lexical_requested,
            "lexical_search_degraded": retriever_runtime.lexical_degraded,
            "lexical_search_error": retriever_runtime.lexical_search_error,
            "cloud_llm_enabled": cloud_llm_enabled,
        }

    @app.post("/api/session")
    def create_anonymous_session() -> dict[str, str | int]:
        return app.state.session_repository.issue()

    @app.get("/api/catalog")
    def get_catalog() -> dict[str, Any]:
        return campus_catalog.public_catalog()

    @app.get("/api/universities")
    def get_go8_universities(
        discipline_id: str | None = Query(default=None),
    ) -> dict[str, Any]:
        try:
            return campus_catalog.list_go8_universities(discipline_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

    @app.get("/api/coverage/capabilities")
    def get_academic_coverage(
        university_id: str = Query(min_length=1),
        program_code: str | None = Query(default=None),
        handbook_year: int | None = Query(default=None, ge=2020, le=2100),
        specialisation_code: str | None = Query(default=None),
    ) -> dict[str, Any]:
        record = academic_coverage.resolve(
            university_id=university_id,
            program_code=program_code,
            handbook_year=handbook_year,
            specialisation_code=specialisation_code,
        )
        return {
            "scope": {
                "university_id": university_id.lower(),
                "program_code": (
                    program_code.upper() if program_code else None
                ),
                "handbook_year": handbook_year,
                "specialisation_code": (
                    specialisation_code.upper()
                    if specialisation_code
                    else None
                ),
            },
            "coverage": record.to_dict() if record else None,
            "model": "CATALOG -> STRUCTURED -> VERIFIED",
        }

    @app.post("/api/programs/compare")
    def compare_programs(
        request: ProgramComparisonRequest,
    ) -> dict[str, Any]:
        try:
            return campus_catalog.compare_programs(
                request.first_program_variant_id,
                request.second_program_variant_id,
                request.handbook_year,
                request.study_stream,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

    @app.post("/api/courses/classify")
    def classify_course_role(
        request: CourseRoleRequest,
    ) -> dict[str, Any]:
        try:
            return campus_catalog.classify_course_role(
                **request.model_dump(),
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

    @app.post("/api/plans/generate")
    def generate_study_plans(
        request: StudyPlanRequest,
    ) -> dict[str, Any]:
        try:
            result = planning_agent.plan(request.model_dump())
            result.setdefault("degraded", False)
            result.setdefault("degradation", None)
            log_event(
                RUNTIME_LOGGER,
                "planner_completed",
                route="/api/plans/generate",
                plan_count=len(result.get("plans", [])),
                all_valid=(result.get("validation") or {}).get("all_valid"),
                retrieval_mode=retriever_runtime.retrieval_mode,
                fallback=False,
            )
            return result
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

    @app.post("/api/plans/semesters/explain")
    def explain_plan_semester(
        request: SemesterAdviceRequest,
    ) -> dict[str, Any]:
        try:
            planning_result = planning_agent.plan(
                request.model_dump(
                    exclude={"plan_id", "semester"},
                )
            )
            plan = next(
                item
                for item in planning_result["plans"]
                if item["plan_id"] == request.plan_id
            )
            semester = next(
                item
                for item in plan["semesters"]
                if item["semester"] == request.semester
            )
            return semester_advice_agent.explain(
                program=planning_result["program"],
                plan=plan,
                semester=semester,
                completed_courses=request.completed_courses,
                evidence=planning_result["evidence"],
            )
        except StopIteration as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="plan or semester not found",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

    @app.post("/api/progress/calculate")
    def calculate_degree_progress(
        request: DegreeProgressRequest,
    ) -> dict[str, Any]:
        try:
            return planning_agent.calculate_progress(request.model_dump())
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

    @app.post("/api/agent/chat")
    def chat_with_planning_agent(
        request: AgentChatRequest,
    ) -> dict[str, Any]:
        try:
            result = conversation_agent.respond(request.model_dump(exclude_unset=True))
            log_event(
                RUNTIME_LOGGER,
                "route_selected",
                route=result.get("conversation_route"),
                thread_id=(result.get("thread_state") or {}).get("thread_id"),
                fallback=bool(result.get("degraded")),
                error_category=(result.get("degradation") or {}).get("reason"),
            )
            return result
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

    @app.post("/api/evidence/search")
    def search_official_evidence(
        request: EvidenceSearchRequest,
    ) -> dict[str, Any]:
        scope = retrieval_scope_resolver.resolve(
            request.query,
            explicit=RetrievalScope(
                handbook_year=request.handbook_year,
                university_id=request.university_id,
                discipline_id=request.discipline_id,
                program_code=request.program_code,
                specialisation_code=request.specialisation_code,
                source_type=request.source_type,
            ),
        )
        documents = evidence_retriever.retrieve(
            RetrievalRequest(
                query=request.query,
                scope=scope,
                k=request.k,
            )
        )
        log_event(
            RUNTIME_LOGGER,
            "retrieval_completed",
            route="/api/evidence/search",
            retrieval_mode=retriever_runtime.retrieval_mode,
            result_count=len(documents),
            fallback=(
                retriever_runtime.vector_degraded
                or retriever_runtime.lexical_degraded
            ),
        )
        return {
            "documents": documents,
            "count": len(documents),
            "answer_source": retriever_runtime.retrieval_mode,
            "scope": scope.to_search_kwargs(),
        }

    @app.post("/api/terminology/search")
    def search_australian_terminology(
        request: TerminologySearchRequest,
    ) -> dict[str, Any]:
        terms = terminology.search(request.query, k=request.k)
        return {
            "terms": terms,
            "count": len(terms),
            "dataset_version": terminology.dataset_version,
            "answer_source": "official_australian_terminology",
        }

    @app.get("/api/admissions/programs")
    def list_admission_programs(
        university: str = Query(min_length=1),
        discipline_id: str | None = Query(default=None),
    ) -> dict[str, Any]:
        return admission_service.find_programs(
            university,
            discipline_id=discipline_id,
        )

    @app.get("/api/admissions/institutions")
    def search_admission_institutions(
        query: str = "",
        country_code: Literal["CN", "AU"] | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 50:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="limit must be between 1 and 50",
            )
        return institution_catalog.search(
            query,
            country_code=country_code,
            limit=limit,
        )

    @app.post("/api/admissions/evaluate")
    def evaluate_admission(
        request: AdmissionEvaluationRequest,
    ) -> dict[str, Any]:
        return admission_service.evaluate(request.model_dump())

    @app.post("/api/admissions/recommend")
    def recommend_admission_programs(
        request: ProgramRecommendationRequest,
    ) -> dict[str, Any]:
        return recommendation_service.recommend(request.model_dump())

    @app.post("/api/admissions/remaining-average")
    def calculate_admission_remaining_average(
        request: RemainingAverageRequest,
    ) -> dict[str, Any]:
        try:
            return admission_service.calculate_remaining_average(request.model_dump())
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

    @app.post("/api/admissions/transcripts/parse")
    async def parse_admission_transcript(
        file: UploadFile = File(...),
        provider: Literal["local_pdf", "multimodal_llm"] = Query(default="local_pdf"),
    ) -> dict[str, Any]:
        content = await file.read(max_upload_bytes + 1)
        if len(content) > max_upload_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"file exceeds {max_upload_bytes} bytes",
            )
        try:
            return transcript_parser.parse(
                filename=file.filename or "transcript.pdf",
                content_type=file.content_type,
                content=content,
                provider=provider,
            )
        except TranscriptValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

    @app.post("/approval/{thread_id}/start")
    def start_approval(
        thread_id: Annotated[
            str,
            ApiPath(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"),
        ],
        request: ActionRequest,
        user_id: Annotated[str, Depends(current_user)],
        approval_service: Annotated[ApprovalService, Depends(service)],
    ) -> dict[str, Any]:
        try:
            return approval_service.start(
                thread_id=thread_id,
                user_id=user_id,
                action=request.model_dump(),
            )
        except ThreadConflictError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

    @app.get("/approval/{thread_id}")
    def get_approval(
        thread_id: Annotated[
            str,
            ApiPath(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"),
        ],
        user_id: Annotated[str, Depends(current_user)],
        approval_service: Annotated[ApprovalService, Depends(service)],
    ) -> dict[str, Any]:
        try:
            return approval_service.get(
                thread_id=thread_id,
                user_id=user_id,
            )
        except ThreadNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="thread not found",
            ) from exc

    @app.post("/approval/{thread_id}/resume")
    def resume_approval(
        thread_id: Annotated[
            str,
            ApiPath(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"),
        ],
        request: ResumeRequest,
        user_id: Annotated[str, Depends(current_user)],
        approval_service: Annotated[ApprovalService, Depends(service)],
    ) -> dict[str, Any]:
        try:
            return approval_service.resume(
                thread_id=thread_id,
                user_id=user_id,
                approved=request.approved,
            )
        except ThreadNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="thread not found",
            ) from exc
        except ThreadConflictError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

    return app


app = create_app()
