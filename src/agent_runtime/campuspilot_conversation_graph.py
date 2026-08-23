from __future__ import annotations

import re
from typing import Any, TypedDict
from uuid import uuid4

from langgraph.graph import END, StateGraph

from .campuspilot import CampusPilotConversationAgent
from .llm_errors import CampusPilotLLMError


class CampusPilotConversationState(TypedDict, total=False):
    request: dict[str, Any]
    query: str
    intent_candidate: str | None
    course_code_candidate: str | None
    intent_decision: dict[str, Any] | None
    intent_source: str
    intent_confidence: float
    intent_validation_error: str | None
    intent_inherited: bool
    intent: str | None
    course_code: str | None
    route: str
    graph_trace: list[dict[str, Any]]
    response: dict[str, Any]
    planning_context: dict[str, Any]
    last_intent: str | None
    last_course_code: str | None
    pending_fields: list[str]
    turn_count: int


class CampusPilotConversationGraph:
    """High-level business routing around specialized CampusPilot agents."""

    STRUCTURED_INTENTS = {
        "study_plan",
        "degree_progress",
        "course_role",
        "program_recommendation",
    }
    GROUNDED_QA_INTENTS = {"handbook_qa", "recruitment_qa"}
    INTENT_CONFIDENCE_THRESHOLD = 0.55

    CONTEXT_FIELDS = {
        "program_variant_id",
        "handbook_year",
        "study_stream",
        "completed_courses",
        "max_courses_per_semester",
        "preserve_policy_flexibility",
        "start_semester",
    }
    REQUEST_DEFAULTS = {
        "handbook_year": 2026,
        "completed_courses": [],
        "max_courses_per_semester": 4,
        "preserve_policy_flexibility": False,
        "start_semester": "2026-S2",
        "conversation_history": [],
    }
    FOLLOW_UP_MARKERS = (
        "那",
        "再",
        "呢",
        "这个",
        "它",
        "继续",
        "改成",
        "换成",
        "均衡",
        "详细",
        "为什么",
        "怎么办",
        "更偏",
        "偏技术",
        "偏数据",
        "偏商业",
    )
    CLARIFICATION_MARKERS = (
        "1年制",
        "1.5年制",
        "2年制",
        "S1",
        "S2",
        "方向",
        "项目",
        "学期",
        "已修",
        "课程",
    )
    RECOMMENDATION_PROFILE_MARKERS = (
        "技术",
        "代码",
        "编程",
        "数据",
        "金融",
        "市场",
        "管理",
        "沟通",
        "创意",
        "喜欢",
        "不喜欢",
        "擅长",
    )

    def __init__(
        self,
        agent: CampusPilotConversationAgent,
        checkpointer: Any | None = None,
    ) -> None:
        self.agent = agent
        self.intent_interpreter = agent.goal_interpreter
        self.checkpointer = checkpointer
        self.graph = self._build_graph()

    def configure_checkpointer(self, checkpointer: Any) -> None:
        """Attach durable persistence after the API lifespan opens SQLite."""
        self.checkpointer = checkpointer
        self.graph = self._build_graph()

    def _build_graph(self):
        workflow = StateGraph(CampusPilotConversationState)
        workflow.add_node("normalize_request", self._normalize_request)
        workflow.add_node("detect_intent_signals", self._detect_intent_signals)
        workflow.add_node("parse_structured_intent", self._parse_structured_intent)
        workflow.add_node("validate_intent_decision", self._validate_intent_decision)
        workflow.add_node("route_conversation_state", self._route_conversation_state)
        workflow.add_node("run_structured_flow", self._run_locked_flow)
        workflow.add_node("run_grounded_qa", self._run_locked_flow)
        workflow.add_node("describe_capabilities", self._run_locked_flow)
        workflow.add_node("interpret_ambiguous_request", self._run_ambiguous_flow)
        workflow.set_entry_point("normalize_request")
        workflow.add_edge("normalize_request", "detect_intent_signals")
        workflow.add_edge("detect_intent_signals", "parse_structured_intent")
        workflow.add_edge("parse_structured_intent", "validate_intent_decision")
        workflow.add_edge("validate_intent_decision", "route_conversation_state")
        workflow.add_conditional_edges(
            "route_conversation_state",
            lambda state: state["route"],
            {
                "structured": "run_structured_flow",
                "grounded_qa": "run_grounded_qa",
                "capabilities": "describe_capabilities",
                "ambiguous": "interpret_ambiguous_request",
            },
        )
        workflow.add_edge("run_structured_flow", END)
        workflow.add_edge("run_grounded_qa", END)
        workflow.add_edge("describe_capabilities", END)
        workflow.add_edge("interpret_ambiguous_request", END)
        return workflow.compile(checkpointer=self.checkpointer)

    def respond(self, request: dict[str, Any]) -> dict[str, Any]:
        request = dict(request)
        thread_id = request.pop("thread_id", None)
        config = None
        if self.checkpointer is not None:
            thread_id = thread_id or f"ephemeral-{uuid4()}"
            config = {"configurable": {"thread_id": thread_id}}
        state = self.graph.invoke(
            {
                "request": request,
                "graph_trace": [],
            },
            config=config,
        )
        response = state["response"]
        graph_trace = state["graph_trace"]
        response["trace"] = [*graph_trace, *response.get("trace", [])]
        response["trace_tools"] = [
            item["tool"] for item in response["trace"] if item.get("tool")
        ]
        response["conversation_route"] = state["route"]
        response["thread_state"] = {
            "thread_id": thread_id,
            "turn_count": state.get("turn_count", 1),
            "last_intent": state.get("last_intent"),
            "pending_fields": state.get("pending_fields", []),
        }
        return response

    @staticmethod
    def _normalize_request(
        state: CampusPilotConversationState,
    ) -> CampusPilotConversationState:
        current_request = state["request"]
        query = current_request["message"].strip()
        planning_context = dict(state.get("planning_context", {}))
        planning_context.update(
            {
                key: value
                for key, value in current_request.items()
                if key in CampusPilotConversationGraph.CONTEXT_FIELDS
                and value is not None
            }
        )
        return {
            "request": {
                **CampusPilotConversationGraph.REQUEST_DEFAULTS,
                **planning_context,
                **current_request,
                "message": query,
            },
            "query": query,
            "planning_context": planning_context,
            "turn_count": state.get("turn_count", 0) + 1,
            "graph_trace": [
                {
                    "tool": "normalize_conversation_input",
                    "ok": bool(query),
                    "restored_context": bool(state.get("planning_context")),
                },
            ],
        }

    def _detect_intent_signals(
        self,
        state: CampusPilotConversationState,
    ) -> CampusPilotConversationState:
        intent, course_code = self.agent._detect_explicit_intent(state["query"])
        inherited = False
        history_inherited = False
        faq_candidate = False
        if intent is None:
            for item in reversed(
                state["request"].get("conversation_history", [])
            ):
                if item.get("role") != "user":
                    continue
                intent, course_code = self.agent._detect_explicit_intent(
                    item.get("content", "")
                )
                if intent is not None:
                    inherited = True
                    history_inherited = True
                    break
        if intent is None and self._should_inherit_intent(state):
            intent = state.get("last_intent")
            course_code = state.get("last_course_code")
            inherited = intent is not None
        if intent is None:
            faq_result = self.agent.faq_service.search(state["query"])
            if faq_result.get("hit"):
                intent = "handbook_qa"
                faq_candidate = True
        return {
            "intent_candidate": intent,
            "course_code_candidate": course_code,
            "intent_inherited": inherited,
            "graph_trace": [
                *state["graph_trace"],
                {
                    "tool": "detect_intent_signals",
                    "ok": True,
                    "intent_candidate": intent,
                    "course_code_candidate": course_code,
                    "intent_inherited": inherited,
                    "history_inherited": history_inherited,
                    "exact_faq_candidate": faq_candidate,
                },
            ],
        }

    def _parse_structured_intent(
        self,
        state: CampusPilotConversationState,
    ) -> CampusPilotConversationState:
        if self.intent_interpreter is None:
            return {
                "intent_decision": None,
                "intent_validation_error": "interpreter_unavailable",
                "graph_trace": [
                    *state["graph_trace"],
                    {
                        "tool": "parse_structured_intent",
                        "ok": False,
                        "skipped": True,
                        "reason": "interpreter_unavailable",
                    },
                ],
            }
        try:
            decision = self.intent_interpreter.interpret(
                state["query"],
                state["request"].get("conversation_history", []),
                planning_context=state.get("planning_context", {}),
            )
            return {
                "intent_decision": decision,
                "intent_validation_error": None,
                "graph_trace": [
                    *state["graph_trace"],
                    {
                        "tool": "parse_structured_intent",
                        "ok": True,
                        "intent": decision.get("intent"),
                        "confidence": decision.get("confidence"),
                        "model": decision.get("model"),
                    },
                ],
            }
        except Exception as exc:
            error = (
                exc.category.value
                if isinstance(exc, CampusPilotLLMError)
                else type(exc).__name__
            )
            return {
                "intent_decision": None,
                "intent_validation_error": error,
                "graph_trace": [
                    *state["graph_trace"],
                    {
                        "tool": "parse_structured_intent",
                        "ok": False,
                        "reason": error,
                    },
                ],
            }

    def _validate_intent_decision(
        self,
        state: CampusPilotConversationState,
    ) -> CampusPilotConversationState:
        decision = dict(state.get("intent_decision") or {})
        parsed_intent = decision.get("intent")
        confidence = float(decision.get("confidence", 0.0) or 0.0)
        error = state.get("intent_validation_error")
        source = "cloud_llm"

        parsed_course = self._normalize_course_code(decision.get("course_code"))
        if parsed_course and parsed_course not in state["query"].upper():
            parsed_course = None
            error = "course_code_not_in_user_query"
        if parsed_intent == "ambiguous" or confidence < self.INTENT_CONFIDENCE_THRESHOLD:
            parsed_intent = None
            error = error or "low_confidence_or_ambiguous"

        intent = parsed_intent or state.get("intent_candidate")
        course_code = parsed_course or state.get("course_code_candidate")
        if intent is None:
            intent = "ambiguous"
            source = "controlled_ambiguity"
        elif parsed_intent is None:
            source = "deterministic_fallback"

        accepted_decision = {
            "goal_summary": state["query"],
            "needs_clarification": False,
            "clarification_question": None,
            "terminology_terms": [],
            **decision,
            "intent": intent,
            "course_code": course_code,
            "confidence": confidence if parsed_intent else 0.0,
        }
        return {
            "intent": intent,
            "course_code": course_code,
            "intent_decision": accepted_decision,
            "intent_source": source,
            "intent_confidence": accepted_decision["confidence"],
            "intent_validation_error": error,
            "last_intent": intent if intent != "ambiguous" else state.get("last_intent"),
            "last_course_code": course_code or state.get("last_course_code"),
            "graph_trace": [
                *state["graph_trace"],
                {
                    "tool": "validate_intent_decision",
                    "ok": parsed_intent is not None,
                    "intent": intent,
                    "source": source,
                    "confidence": accepted_decision["confidence"],
                    "validation_error": error,
                },
            ],
        }

    def _route_conversation_state(
        self,
        state: CampusPilotConversationState,
    ) -> CampusPilotConversationState:
        intent = state["intent"]
        if intent in self.STRUCTURED_INTENTS:
            route = "structured"
        elif intent in self.GROUNDED_QA_INTENTS:
            route = "grounded_qa"
        elif intent == "capabilities":
            route = "capabilities"
        else:
            route = "ambiguous"
        return {
            "route": route,
            "graph_trace": [
                *state["graph_trace"],
                {
                    "tool": "route_conversation_state",
                    "ok": True,
                    "intent": intent,
                    "route": route,
                    "intent_locked": intent != "ambiguous",
                    "intent_inherited": state.get("intent_inherited", False),
                },
            ],
        }

    @staticmethod
    def _normalize_course_code(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        code = value.strip().upper()
        return code if re.fullmatch(r"[A-Z]{2,5}\d{4}", code) else None

    def _should_inherit_intent(self, state: CampusPilotConversationState) -> bool:
        if not state.get("last_intent"):
            return False
        query = state["query"]
        if len(query) > 30:
            return False
        markers = self.FOLLOW_UP_MARKERS
        if state.get("pending_fields"):
            markers = (*markers, *self.CLARIFICATION_MARKERS)
        if "recommendation_profile" in state.get("pending_fields", []):
            markers = (*markers, *self.RECOMMENDATION_PROFILE_MARKERS)
        return any(marker in query for marker in markers)

    def _run_locked_flow(
        self,
        state: CampusPilotConversationState,
    ) -> CampusPilotConversationState:
        response = self.agent.respond(
            {
                **state["request"],
                "_resolved_intent": state["intent"],
                "_resolved_course_code": state.get("course_code"),
                "_intent_locked": True,
                "_intent_interpretation": state.get("intent_decision"),
                "_intent_source": state.get("intent_source"),
                "_goal_interpretation_attempted": True,
                "_pending_fields": state.get("pending_fields", []),
                "_intent_inherited": state.get("intent_inherited", False),
            }
        )
        return self._flow_result(state, response, intent_locked=True)

    def _run_ambiguous_flow(
        self,
        state: CampusPilotConversationState,
    ) -> CampusPilotConversationState:
        response = self.agent.respond(
            {
                **state["request"],
                "_resolved_intent": "ambiguous",
                "_intent_locked": True,
                "_intent_interpretation": state.get("intent_decision"),
                "_intent_source": state.get("intent_source"),
                "_goal_interpretation_attempted": True,
            }
        )
        return self._flow_result(state, response, intent_locked=True)

    @staticmethod
    def _flow_result(
        state: CampusPilotConversationState,
        response: dict[str, Any],
        *,
        intent_locked: bool,
    ) -> CampusPilotConversationState:
        llm_reasons = {
            "rate_limited",
            "quota_exhausted",
            "timeout",
            "upstream_5xx",
            "auth_error",
            "model_unavailable",
            "invalid_response",
            "network_error",
            "unknown",
        }
        degradation_reason = (
            state.get("intent_validation_error")
            if state.get("intent_validation_error") in llm_reasons
            else None
        )
        for item in response.get("trace", []):
            if (
                item.get("source") == "openai_compatible_llm"
                and item.get("ok") is False
                and item.get("error") in llm_reasons
            ):
                degradation_reason = item["error"]
        if degradation_reason:
            response["degraded"] = True
            response["degradation"] = {
                "component": "llm",
                "reason": degradation_reason,
            }
        else:
            response.setdefault("degraded", False)
            response.setdefault("degradation", None)
        return {
            "response": response,
            "last_intent": response.get("intent") or state.get("last_intent"),
            "pending_fields": response.get("missing_fields", []),
            "graph_trace": [
                *state["graph_trace"],
                {
                    "tool": "execute_conversation_route",
                    "ok": True,
                    "route": state["route"],
                    "intent_locked": intent_locked,
                    "resolved_intent": response.get("intent"),
                },
            ],
        }
