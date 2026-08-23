import { ApiError, requestJson, runButtonTask } from "./core/api.js";
import {
  loadPlannerCatalog,
  renderCompletedCourses,
  renderProgramOptions,
  renderStreamOptions,
} from "./planner/catalog.js";
import { renderEvidence } from "./planner/evidence.js";
import { createPlanResultRenderer } from "./planner/results.js";

const ids = [
  "serviceState", "serviceLabel", "runDemoButton", "catalogMeta", "planForm",
  "resetPlanButton", "programVariant", "studyStream", "startSemester", "maxLoad",
  "completedCourses", "policyFlexibility", "generateButton", "plannerEmpty",
  "plannerMessage", "planResults", "confidenceBadge", "summaryEntry", "summaryCredits",
  "summaryValid", "summaryRules", "warningList", "planTabs", "selectedPlanName",
  "selectedPlanSemesters", "selectedPlanDescription", "semesterTimeline", "traceCount",
  "traceList", "evidenceSection", "evidenceCount", "evidenceGrid", "retrievedDate", "toast",
];
const elements = Object.fromEntries(ids.map((id) => [id, document.getElementById(id)]));
const renderer = createPlanResultRenderer(elements);
let catalog = null;
let activeRequest = null;

function currentProgram() {
  return catalog.programs.find((program) => program.program_variant_id === elements.programVariant.value);
}

function checkedCourses() {
  return [...elements.completedCourses.querySelectorAll("input:checked")].map((input) => input.value);
}

function setCheckedCourses(courseCodes) {
  const selected = new Set(courseCodes);
  elements.completedCourses.querySelectorAll("input").forEach((input) => {
    input.checked = selected.has(input.value);
  });
}

function applyScenario(name = "el2") {
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

function plannerRequest() {
  return {
    program_variant_id: elements.programVariant.value,
    handbook_year: 2026,
    study_stream: elements.studyStream.value,
    completed_courses: checkedCourses(),
    max_courses_per_semester: Number(elements.maxLoad.value),
    preserve_policy_flexibility: elements.policyFlexibility.checked,
    start_semester: elements.startSemester.value,
  };
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

async function generatePlan(triggerButton) {
  if (!catalog) return;
  if (activeRequest) activeRequest.abort();
  activeRequest = new AbortController();
  const controller = activeRequest;
  elements.plannerMessage.classList.add("hidden");
  elements.planResults.parentElement.setAttribute("aria-busy", "true");
  try {
    await runButtonTask(triggerButton, "正在计算与校验…", async () => {
      const payload = await requestJson("/api/plans/generate", {
        method: "POST",
        body: JSON.stringify(plannerRequest()),
        signal: controller.signal,
      });
      if (controller !== activeRequest) return;
      renderer.render(payload);
      renderEvidence({
        container: elements.evidenceGrid,
        count: elements.evidenceCount,
        section: elements.evidenceSection,
        payload,
        catalogSources: catalog.sources,
      });
      showToast("三套路径已完成确定性校验。", "success");
      elements.planResults.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  } catch (error) {
    if (error.name !== "AbortError") showPlannerError(error);
  } finally {
    if (controller === activeRequest) {
      activeRequest = null;
      elements.planResults.parentElement.setAttribute("aria-busy", "false");
    }
  }
}

async function checkCoreHealth() {
  try {
    const health = await requestJson("/health/ready");
    const ready = health.status === "ready" && health.catalog_loaded;
    elements.serviceState.className = `service-state ${ready ? "online" : "degraded"}`;
    elements.serviceLabel.textContent = ready ? "Planner 核心可用" : "服务降级";
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
    elements.runDemoButton.disabled = false;
  } catch (error) {
    showPlannerError(error);
    elements.catalogMeta.textContent = "培养方案加载失败";
  }
}

elements.planForm.addEventListener("submit", (event) => {
  event.preventDefault();
  generatePlan(event.submitter || elements.generateButton);
});
elements.runDemoButton.addEventListener("click", () => {
  applyScenario("el2");
  generatePlan(elements.runDemoButton);
});
elements.resetPlanButton.addEventListener("click", () => {
  if (activeRequest) activeRequest.abort();
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

initialize();
