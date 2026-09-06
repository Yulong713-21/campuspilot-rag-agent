const roleLabels = {
  FOUNDATION: "Foundation",
  CORE: "Core",
  CAPSTONE: "Capstone",
  ELECTIVE: "Elective",
  RESEARCH_CORE: "Research",
};

function renderWarnings(container, warnings = []) {
  container.replaceChildren(...warnings.map((warning) => {
    const item = document.createElement("p");
    item.textContent = warning;
    return item;
  }));
  container.classList.toggle("hidden", warnings.length === 0);
}

function renderTimeline(container, plan) {
  container.replaceChildren(...plan.semesters.map((semester) => {
    const row = document.createElement("article");
    row.className = "semester-row";
    const header = document.createElement("div");
    header.className = "semester-header";
    const term = document.createElement("strong");
    const credits = document.createElement("span");
    term.textContent = semester.semester;
    credits.textContent = `${semester.total_credits} cp`;
    header.append(term, credits);

    const courses = document.createElement("div");
    courses.className = "semester-courses";
    semester.courses.forEach((course) => {
      const item = document.createElement("div");
      item.className = `course-chip ${String(course.rule_type || "").toLowerCase()}`;
      const code = document.createElement("strong");
      const name = document.createElement("span");
      const role = document.createElement("small");
      code.textContent = course.course_code;
      name.textContent = course.course_name;
      role.textContent = roleLabels[course.rule_type] || course.rule_type;
      item.append(code, name, role);
      courses.append(item);
    });
    row.append(header, courses);
    return row;
  }));
}

function renderTrace(list, count, trace = []) {
  count.textContent = `${trace.length} steps`;
  list.replaceChildren(...trace.map((event, index) => {
    const item = document.createElement("li");
    const number = document.createElement("span");
    const body = document.createElement("div");
    const title = document.createElement("strong");
    const status = document.createElement("small");
    number.textContent = String(index + 1).padStart(2, "0");
    title.textContent = String(event.tool || "rule_check").replaceAll("_", " ");
    status.textContent = event.ok ? "通过" : "需要复核";
    body.append(title, status);
    item.append(number, body);
    return item;
  }));
}

function renderRuleChecks(container, allValid) {
  const checks = ["Credits", "Prerequisites", "Availability", "Capstone"];
  container.replaceChildren(...checks.map((label) => {
    const item = document.createElement("span");
    item.className = `rule-check${allValid ? "" : " review"}`;
    item.textContent = `${allValid ? "✓" : "!"} ${label}`;
    return item;
  }));
}

export function createPlanResultRenderer(elements) {
  let selectedPlan = null;

  function selectPlan(plan) {
    selectedPlan = plan;
    elements.selectedPlanName.textContent = plan.name;
    elements.selectedPlanDescription.textContent = plan.description;
    elements.selectedPlanSemesters.textContent = `${plan.estimated_semesters} 学期`;
    renderTimeline(elements.semesterTimeline, plan);
    elements.planTabs.querySelectorAll("button").forEach((button) => {
      const active = button.dataset.planId === plan.plan_id;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", String(active));
    });
  }

  function render(payload) {
    const plans = Array.isArray(payload.plans) ? payload.plans : [];
    elements.summaryEntry.textContent = `EL ${payload.program.entry_level}`;
    elements.summaryCredits.textContent = `${payload.remaining_credits} cp`;
    elements.summaryValid.textContent = `${payload.validation.valid_plan_count} / ${plans.length}`;
    elements.summaryRules.textContent = payload.validation.all_valid ? "全部通过" : "需要复核";
    elements.confidenceBadge.textContent = payload.confidence === "high" ? "高置信度" : "建议复核";
    elements.confidenceBadge.classList.toggle("review", payload.confidence !== "high");
    renderWarnings(elements.warningList, payload.warnings);

    elements.planTabs.replaceChildren(...plans.map((plan) => {
      const button = document.createElement("button");
      button.type = "button";
      button.role = "tab";
      button.dataset.planId = plan.plan_id;
      button.dataset.routeLabel = `Route ${String(plans.indexOf(plan) + 1).padStart(2, "0")}`;
      button.textContent = plan.name;
      button.addEventListener("click", () => selectPlan(plan));
      return button;
    }));
    renderRuleChecks(elements.ruleChecks, payload.validation.all_valid);
    renderTrace(elements.traceList, elements.traceCount, payload.trace);
    if (plans.length) selectPlan(plans[0]);
    elements.plannerEmpty.classList.add("hidden");
    elements.planResults.classList.remove("hidden");
    return selectedPlan;
  }

  function reset() {
    selectedPlan = null;
    elements.planResults.classList.add("hidden");
    elements.plannerEmpty.classList.remove("hidden");
  }

  return { render, reset, selected: () => selectedPlan };
}
