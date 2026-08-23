from contextlib import asynccontextmanager
from dataclasses import dataclass
import hmac
import json
import logging
import os
from pathlib import Path
import sqlite3
import time
from typing import Annotated, Any, Literal

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
from .semester_advisor import create_semester_advice_agent_with_cloud
from .openai_compatible_client import OpenAICompatibleChatClient
from .planning_goal_interpreter import CloudPlanningGoalInterpreter
from .program_recommendation_interpreter import (
    CloudRecommendationProfileInterpreter,
)
from .program_recommendation_narrator import ProgramRecommendationNarrator
from .rate_limit import InMemoryRateLimiter
from .plan_narrator import StudyPlanNarrator
from .australian_terminology import AustralianTerminologyGlossary
from .recruitment_knowledge import (
    ChinaRecruitmentKnowledgeBase,
    RecruitmentQuestionAnsweringAgent,
)
from campuspilot_core.admission_mvp import AdmissionMvpService
from campuspilot_core.institution_catalog import InstitutionCatalog
from campuspilot_core.program_recommendation import ProgramRecommendationService
from campuspilot_core.transcript_parser import (
    TranscriptParseService,
    TranscriptValidationError,
)


STATIC_DIR = Path(__file__).resolve().parents[2] / "static"
REPO_ROOT = STATIC_DIR.parent
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class EvidenceRetrieverRuntime:
    retriever: Any
    vector_requested: bool
    vector_error: str | None = None
    retrieval_mode: str = "catalog_bm25"

    @property
    def vector_active(self) -> bool:
        return (
            isinstance(self.retriever, CampusPilotHybridRetriever)
            and self.retriever.vector_store is not None
        )

    @property
    def vector_degraded(self) -> bool:
        return self.vector_requested and not self.vector_active


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
    retrieval_mode = os.environ.get(
        "CAMPUSPILOT_RETRIEVAL_MODE",
        "",
    ).strip().lower()
    enabled = os.environ.get(
        "CAMPUSPILOT_VECTOR_SEARCH_ENABLED",
        "0",
    ).lower() in {"1", "true", "yes"}
    fallback = CampusPilotEvidenceRetriever(
        catalog.data.get("official_documents", [])
    )
    if retrieval_mode == "full_bm25":
        return EvidenceRetrieverRuntime(
            retriever=CampusPilotHybridRetriever(
                chunks=read_chunks(),
                vector_store=None,
            ),
            vector_requested=False,
            retrieval_mode="full_corpus_bm25",
        )
    if not enabled:
        return EvidenceRetrieverRuntime(
            retriever=fallback,
            vector_requested=False,
            retrieval_mode="catalog_bm25",
        )
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
        )
        reranker = None
        reranker_enabled = os.environ.get(
            "CAMPUSPILOT_RERANKER_ENABLED",
            "0",
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
                chunks=read_chunks(),
                vector_store=vector_store,
                reranker=reranker,
            ),
            vector_requested=True,
            retrieval_mode=(
                "bm25_"
                + backend.replace("-", "_")
                + "_milvus_rrf"
                + ("_reranked" if reranker is not None else "")
            ),
        )
    except Exception as exc:
        LOGGER.exception(
            "Vector retrieval initialization failed; falling back to BM25"
        )
        try:
            full_bm25 = CampusPilotHybridRetriever(
                chunks=read_chunks(),
                vector_store=None,
            )
            return EvidenceRetrieverRuntime(
                retriever=full_bm25,
                vector_requested=True,
                vector_error=type(exc).__name__,
                retrieval_mode="full_corpus_bm25_degraded",
            )
        except Exception:
            LOGGER.exception(
                "Full corpus BM25 initialization failed; using catalog fallback"
            )
        return EvidenceRetrieverRuntime(
            retriever=fallback,
            vector_requested=True,
            vector_error=type(exc).__name__,
            retrieval_mode="catalog_bm25_degraded",
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
    campus_catalog = CampusPilotCatalog()
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

    expensive_paths = {
        "/api/session",
        "/api/agent/chat",
        "/api/plans/semesters/explain",
        "/api/admissions/recommend",
        "/api/admissions/transcripts/parse",
    }

    @app.middleware("http")
    async def limit_expensive_requests(request: Request, call_next):
        if (
            rate_limiter is not None
            and request.method == "POST"
            and request.url.path in expensive_paths
        ):
            client_host = request.client.host if request.client else "unknown"
            allowed, retry_after = rate_limiter.allow(
                f"{client_host}:{request.url.path}"
            )
            if not allowed:
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={"detail": "request rate limit exceeded"},
                    headers={"Retry-After": str(retry_after)},
                )
        return await call_next(request)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

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
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/admin", include_in_schema=False)
    def admin_page(request: Request) -> FileResponse:
        if not admin_enabled:
            raise HTTPException(status_code=404, detail="local admin is disabled")
        host = request.client.host if request.client else ""
        if admin_local_only and host not in {"127.0.0.1", "::1", "localhost"}:
            raise HTTPException(status_code=404, detail="local admin is unavailable")
        return FileResponse(STATIC_DIR / "admin.html")

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
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"{type(exc).__name__}: {str(exc)[:300]}",
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
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "product": "CampusPilot",
            "data_mode": campus_catalog.data["data_mode"],
            "retrieval_mode": (
                retriever_runtime.retrieval_mode
            ),
            "goal_interpreter": (
                "cloud_openai_compatible" if cloud_llm_enabled else "deterministic"
            ),
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
            return planning_agent.plan(request.model_dump())
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
            return conversation_agent.respond(request.model_dump(exclude_unset=True))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

    @app.post("/api/evidence/search")
    def search_official_evidence(
        request: EvidenceSearchRequest,
    ) -> dict[str, Any]:
        documents = evidence_retriever.search(
            request.query,
            handbook_year=request.handbook_year,
            university_id=request.university_id,
            discipline_id=request.discipline_id,
            program_code=request.program_code,
            k=request.k,
        )
        return {
            "documents": documents,
            "count": len(documents),
            "answer_source": retriever_runtime.retrieval_mode,
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
