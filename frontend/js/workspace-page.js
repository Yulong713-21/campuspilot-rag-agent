import { ApiError, requestJson, requestJsonWithMeta, runButtonTask } from "./core/api.js";
import { createConversation, assistantText } from "./pia/conversation.js";
import {
  loadPlannerCatalog,
  renderCompletedCourses,
  renderProgramOptions,
  renderStreamOptions,
} from "./planner/catalog.js";
import { renderEvidence } from "./planner/evidence.js";
import { createPlanResultRenderer } from "./planner/results.js";
import { buildPlannerRequest, verifiedChatRequest, verifiedPrompt } from "./workflows/c6001.js";

const ids = [
  "serviceState", "serviceLabel", "conversation", "chatForm", "chatInput", "sendButton",
  "runVerifiedButton", "catalogMeta", "planForm", "resetPlanButton", "programVariant",
  "studyStream", "startSemester", "maxLoad", "completedCourses", "policyFlexibility",
  "generateButton", "planningOutput", "plannerEmpty", "plannerMessage", "planResults",
  "confidenceBadge", "summaryEntry", "summaryCredits", "summaryValid", "summaryRules",
  "ruleChecks", "warningList", "planTabs", "selectedPlanName", "selectedPlanSemesters",
  "selectedPlanDescription", "semesterTimeline", "traceCount", "traceList",
  "evidenceSection", "evidenceCount", "evidenceGrid", "retrievedDate", "toast",
];
const elements = Object.fromEntries(ids.map((id) => [id, document.getElementById(id)]));
const conversation = createConversation(elements.conversation);
const renderer = createPlanResultRenderer(elements);
let catalog = null;
let activePlanningRequest = null;
let activeChatRequest = null;

function currentProgram() {
  return catalog?.programs.find((program) => program.program_variant_id === elements.programVariant.value);
}

function setCheckedCourses(courseCodes) {
  const selected = new Set(courseCodes);
  elements.completedCourses.querySelectorAll("input").forEach((input) => {
    input.checked = selected.has(input.value);
  });
}

function applyScenario(name = "el2") {
  if (!catalog) return;
  const scenarios = {
    el1: { program: "MONASH-C6001-EL1", completed: [], load: "4", flexible: false },
    el2: { program: "MONASH-C6001-EL2", completed: ["FIT5057"], load: "4", flexible: true },
    balanced: { program: "MONASH-C6001-EL2", completed: ["FIT5057", "FIT5125"], load: "3", flexible: true },
  };
  const scenario = scenarios[name] || scenarios.el2;
  elements.programVariant.value = scenario.program;
  renderStreamOptions(elements.studyStream, currentProgram(), "Industry Experience");
  elements.startSemester.value = "2026-S2";
  elements.maxLoad.value = scenario.load;
  elements.policyFlexibility.checked = scenario.flexible;
  setCheckedCourses(scenario.completed);
  document.querySelectorAll("[data-scenario]").forEach((button) => {
    button.classList.toggle("active", button.dataset.scenario === name);
  });
}

function showToast(message, type = "info") {
  elements.toast.textContent = message;
  elements.toast.className = `toast ${type}`;
  window.setTimeout(() => elements.toast.classList.add("hidden"), 3200);
}

function showPlannerError(error) {
  const reference = error instanceof ApiError && error.requestId ? ` · Reference ${error.requestId}` : "";
  elements.plannerMessage.textContent = `${error.message || "规划请求失败"}${reference}`;
  elements.plannerMessage.classList.remove("hidden");
}

function renderSources(payload) {
  if (!catalog) return;
  renderEvidence({
    container: elements.evidenceGrid,
    count: elements.evidenceCount,
    section: elements.evidenceSection,
    payload,
    catalogSources: catalog.sources,
  });
}

function renderPlanningResult(payload, { scroll = true } = {}) {
  elements.plannerMessage.classList.add("hidden");
  renderer.render(payload);
  renderSources(payload);
  if (scroll) elements.planResults.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function runVerifiedWorkflow() {
  if (!catalog) return;
  if (activePlanningRequest) activePlanningRequest.abort();
  const controller = new AbortController();
  activePlanningRequest = controller;
  const priorHistory = conversation.history();
  conversation.addUser(verifiedPrompt);
  elements.planningOutput.setAttribute("aria-busy", "true");
  elements.plannerMessage.classList.add("hidden");
  try {
    await runButtonTask(elements.runVerifiedButton, "正在生成与校验…", async () => {
      const { payload, requestId } = await requestJsonWithMeta("/api/agent/chat", {
        method: "POST",
        body: JSON.stringify(verifiedChatRequest(elements, priorHistory)),
        signal: controller.signal,
      });
      if (controller !== activePlanningRequest) return;
      const plans = payload.study_plans;
      if (!plans) throw new Error(assistantText(payload));
      conversation.addAssistant(
        payload.message || `已根据 Monash C6001 2026 规则生成 ${plans.plans?.length || 3} 套有效路径。`,
        { requestId },
      );
      renderPlanningResult(plans);
      showToast("C6001 路径已由版本化规则引擎生成。", "success");
    });
  } catch (error) {
    if (error.name !== "AbortError") {
      showPlannerError(error);
      conversation.addAssistant(`这次规划没有完成：${error.message || "服务暂时不可用"}`);
    }
  } finally {
    if (controller === activePlanningRequest) {
      activePlanningRequest = null;
      elements.planningOutput.setAttribute("aria-busy", "false");
    }
  }
}

async function generateCustomPlan(triggerButton) {
  if (!catalog) return;
  if (activePlanningRequest) activePlanningRequest.abort();
  const controller = new AbortController();
  activePlanningRequest = controller;
  conversation.addUser("请按我设置的约束重新生成 C6001 学习路径。");
  elements.planningOutput.setAttribute("aria-busy", "true");
  elements.plannerMessage.classList.add("hidden");
  try {
    await runButtonTask(triggerButton, "正在计算与校验…", async () => {
      const { payload, requestId } = await requestJsonWithMeta("/api/plans/generate", {
        method: "POST",
        body: JSON.stringify(buildPlannerRequest(elements)),
        signal: controller.signal,
      });
      if (controller !== activePlanningRequest) return;
      conversation.addAssistant(`已按新约束完成 deterministic planning，并生成 ${payload.plans?.length || 3} 套路径。`, { requestId });
      renderPlanningResult(payload);
      showToast("自定义路径已校验。", "success");
    });
  } catch (error) {
    if (error.name !== "AbortError") showPlannerError(error);
  } finally {
    if (controller === activePlanningRequest) {
      activePlanningRequest = null;
      elements.planningOutput.setAttribute("aria-busy", "false");
    }
  }
}

async function sendChatMessage(message) {
  const text = String(message || "").trim();
  if (!text) return;
  if (activeChatRequest) activeChatRequest.abort();
  const controller = new AbortController();
  activeChatRequest = controller;
  const priorHistory = conversation.history();
  conversation.addUser(text);
  elements.chatInput.value = "";
  try {
    await runButtonTask(elements.sendButton, "…", async () => {
      const context = catalog ? buildPlannerRequest(elements) : {};
      const { payload, requestId } = await requestJsonWithMeta("/api/agent/chat", {
        method: "POST",
        body: JSON.stringify({
          message: text,
          ...context,
          conversation_history: priorHistory,
        }),
        signal: controller.signal,
      });
      if (controller !== activeChatRequest) return;
      conversation.addAssistant(assistantText(payload), { requestId });
      if (payload.study_plans) renderPlanningResult(payload.study_plans);
      else if (Array.isArray(payload.evidence) && payload.evidence.length) renderSources(payload);
    });
  } catch (error) {
    if (error.name !== "AbortError") {
      const reference = error instanceof ApiError && error.requestId ? `（Reference ${error.requestId}）` : "";
      conversation.addAssistant(`请求暂时没有完成${reference}。${error.message || "请稍后重试。"}`);
    }
  } finally {
    if (controller === activeChatRequest) activeChatRequest = null;
  }
}

async function checkCoreHealth() {
  try {
    const health = await requestJson("/health/ready");
    const ready = health.status === "ready" && health.catalog_loaded;
    elements.serviceState.className = `service-state ${ready ? "online" : "degraded"}`;
    elements.serviceLabel.textContent = ready ? "核心服务可用" : "服务降级";
  } catch (_) {
    elements.serviceState.className = "service-state offline";
    elements.serviceLabel.textContent = "核心服务离线";
  }
}

async function initialize() {
  checkCoreHealth();
  try {
    catalog = await loadPlannerCatalog();
    renderProgramOptions(elements.programVariant, catalog.programs);
    renderCompletedCourses(elements.completedCourses, catalog.courses);
    applyScenario("el2");
    elements.catalogMeta.textContent = `${catalog.catalog_version} · ${catalog.official_document_count} 份官方文档`;
    elements.retrievedDate.textContent = `Data snapshot · ${catalog.retrieved_at}`;
    elements.generateButton.disabled = false;
    elements.runVerifiedButton.disabled = false;
  } catch (error) {
    showPlannerError(error);
    elements.catalogMeta.textContent = "培养方案加载失败";
  }
}

elements.chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  sendChatMessage(elements.chatInput.value);
});
elements.runVerifiedButton.addEventListener("click", runVerifiedWorkflow);
elements.planForm.addEventListener("submit", (event) => {
  event.preventDefault();
  generateCustomPlan(event.submitter || elements.generateButton);
});
elements.resetPlanButton.addEventListener("click", () => {
  if (activePlanningRequest) activePlanningRequest.abort();
  applyScenario("el2");
  renderer.reset();
  elements.evidenceSection.classList.add("hidden");
  elements.plannerMessage.classList.add("hidden");
});
elements.programVariant.addEventListener("change", () => {
  renderStreamOptions(elements.studyStream, currentProgram(), elements.studyStream.value);
});
document.querySelectorAll("[data-scenario]").forEach((button) => {
  button.addEventListener("click", () => applyScenario(button.dataset.scenario));
});
document.querySelectorAll("[data-prompt]").forEach((button) => {
  button.addEventListener("click", () => {
    elements.chatInput.value = button.dataset.prompt;
    elements.chatInput.focus();
  });
});

initialize();
