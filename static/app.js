const state = {
  catalog: null,
  planResponse: null,
  selectedPlan: null,
  pendingThreadId: null,
  busy: false,
  selectedDiscipline: "computing",
  sessionToken: window.localStorage.getItem("campuspilot-session-token"),
};

const elements = Object.fromEntries(
  [
    "serviceLabel",
    "retrievedDate",
    "sourceCount",
    "catalogVersion",
    "planForm",
    "programVariant",
    "studyStream",
    "startSemester",
    "maxLoad",
    "completedCourses",
    "policyFlexibility",
    "generateButton",
    "resetPlanButton",
    "plannerEmpty",
    "planResults",
    "summaryEntry",
    "summaryCredits",
    "summaryValid",
    "summaryConfidence",
    "warningList",
    "planTabs",
    "savePlanButton",
    "selectedPlanName",
    "selectedPlanDescription",
    "selectedPlanSemesters",
    "semesterTimeline",
    "traceCount",
    "traceList",
    "sourceList",
    "compareForm",
    "compareFirst",
    "compareSecond",
    "compareStream",
    "compareResults",
    "classifierForm",
    "classifierProgram",
    "classifierStream",
    "classifierCourse",
    "classifierResult",
    "disciplineFilters",
    "universityCount",
    "disciplineCount",
    "verifiedUniversityCount",
    "go8CoverageNotice",
    "universityGrid",
    "confirmDialog",
    "closeDialogButton",
    "confirmPreview",
    "rejectSaveButton",
    "confirmSaveButton",
    "toast",
  ].map((id) => [id, document.getElementById(id)]),
);

const roleLabels = {
  FOUNDATION_CORE: "Foundation Core",
  CORE: "Core",
  CAPSTONE: "Capstone",
  RESEARCH_CORE: "Research Core",
  PRESCRIBED_ELECTIVE: "Prescribed Elective",
  GENERAL_ELECTIVE: "General Elective",
  NOT_ELIGIBLE: "不计入当前路径",
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || `请求失败（HTTP ${response.status}）`);
  }
  return payload;
}

async function sessionToken() {
  if (state.sessionToken) {
    return state.sessionToken;
  }
  const session = await api("/api/session", { method: "POST" });
  state.sessionToken = session.access_token;
  window.localStorage.setItem("campuspilot-session-token", state.sessionToken);
  return state.sessionToken;
}

function setBusy(busy) {
  state.busy = busy;
  document.querySelectorAll("button").forEach((button) => {
    button.disabled = busy;
  });
  elements.generateButton.textContent = busy ? "规划中..." : "生成三套方案";
}

function showToast(message, type = "info") {
  elements.toast.textContent = message;
  elements.toast.classList.toggle("error", type === "error");
  elements.toast.classList.remove("hidden");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => {
    elements.toast.classList.add("hidden");
  }, 3800);
}

function programLabel(program) {
  return `${program.program_code} · Entry Level ${program.entry_level} · ${program.duration_years} 年`;
}

function fillProgramSelect(select, programs) {
  select.replaceChildren();
  programs.forEach((program) => {
    const option = document.createElement("option");
    option.value = program.program_variant_id;
    option.textContent = programLabel(program);
    select.append(option);
  });
}

function currentProgram(select = elements.programVariant) {
  return state.catalog.programs.find(
    (program) => program.program_variant_id === select.value,
  );
}

function fillStreamSelect(select, program) {
  const previous = select.value;
  select.replaceChildren();
  program.study_streams.forEach((stream) => {
    const option = document.createElement("option");
    option.value = stream;
    option.textContent = stream;
    select.append(option);
  });
  if (program.study_streams.includes(previous)) {
    select.value = previous;
  }
}

function renderCourseOptions() {
  elements.completedCourses.replaceChildren();
  state.catalog.courses.forEach((course) => {
    const label = document.createElement("label");
    label.className = "course-check";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = course.course_code;
    const text = document.createElement("span");
    const code = document.createElement("strong");
    const name = document.createElement("small");
    code.textContent = course.course_code;
    name.textContent = course.course_name;
    text.append(code, name);
    label.append(input, text);
    elements.completedCourses.append(label);
  });
}

function renderSourceList(sourceIds) {
  elements.sourceList.replaceChildren();
  sourceIds.forEach((sourceId) => {
    const source = state.catalog.sources.find(
      (item) => item.source_id === sourceId,
    );
    if (!source) {
      return;
    }
    const item = document.createElement("li");
    const link = document.createElement("a");
    const meta = document.createElement("small");
    link.href = source.url;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = source.title;
    meta.textContent = `${source.source_type} · 获取于 ${source.retrieved_at}`;
    item.append(link, meta);
    elements.sourceList.append(item);
  });
}

function renderTrace(trace) {
  elements.traceList.replaceChildren();
  elements.traceCount.textContent = `${trace.length} steps`;
  trace.forEach((event, index) => {
    const item = document.createElement("li");
    const number = document.createElement("span");
    const content = document.createElement("div");
    const title = document.createElement("strong");
    const detail = document.createElement("small");
    number.textContent = String(index + 1);
    title.textContent = event.tool;
    detail.textContent = event.ok ? "执行成功" : "需要调整";
    content.append(title, detail);
    item.append(number, content);
    elements.traceList.append(item);
  });
}

function renderUniversityDirectory() {
  const universities = state.catalog.universities.filter((university) =>
    university.discipline_ids.includes(state.selectedDiscipline),
  );
  const disciplineMap = new Map(
    state.catalog.disciplines.map((item) => [item.discipline_id, item.name]),
  );

  elements.universityCount.textContent = String(universities.length);
  elements.disciplineCount.textContent = String(state.catalog.disciplines.length);
  elements.verifiedUniversityCount.textContent = String(
    universities.filter(
      (item) => item.coverage_status === "planning_verified",
    ).length,
  );
  elements.go8CoverageNotice.textContent = state.catalog.go8_coverage_notice;
  elements.universityGrid.replaceChildren();

  universities.forEach((university) => {
    const article = document.createElement("article");
    article.className = "university-card";

    const heading = document.createElement("div");
    heading.className = "university-heading";
    const identity = document.createElement("div");
    const location = document.createElement("p");
    const title = document.createElement("h2");
    const status = document.createElement("span");
    location.className = "overline";
    location.textContent = `${university.city} · ${university.state}`;
    title.textContent = university.name;
    status.className = `coverage-status ${university.coverage_status}`;
    status.textContent = university.coverage_label;
    identity.append(location, title);
    heading.append(identity, status);

    const disciplineList = document.createElement("div");
    disciplineList.className = "discipline-list";
    university.discipline_ids.forEach((disciplineId) => {
      const tag = document.createElement("span");
      tag.textContent = disciplineMap.get(disciplineId);
      disciplineList.append(tag);
    });

    const catalogLink = document.createElement("a");
    catalogLink.className = "catalog-link";
    catalogLink.href = university.catalog_url;
    catalogLink.target = "_blank";
    catalogLink.rel = "noreferrer";
    catalogLink.textContent = "打开学校官方课程目录";

    article.append(heading, disciplineList);
    if (state.selectedDiscipline === "computing") {
      const program = university.representative_program;
      const programBlock = document.createElement("div");
      programBlock.className = "representative-program";
      const programText = document.createElement("div");
      const programLabel = document.createElement("span");
      const programTitle = document.createElement("strong");
      const programMeta = document.createElement("small");
      programLabel.textContent = "已核验的计算机类代表项目";
      programTitle.textContent = program.name;
      programMeta.textContent = [
        program.program_code,
        program.duration,
        program.credit_value,
      ].filter(Boolean).join(" · ");
      programText.append(programLabel, programTitle, programMeta);
      const programLink = document.createElement("a");
      programLink.href = program.official_url;
      programLink.target = "_blank";
      programLink.rel = "noreferrer";
      programLink.textContent = "项目资料";
      programBlock.append(programText, programLink);
      article.append(programBlock);
    }
    article.append(catalogLink);
    elements.universityGrid.append(article);
  });
}

function renderDisciplineFilters() {
  elements.disciplineFilters.replaceChildren();
  state.catalog.disciplines.forEach((discipline) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "discipline-button";
    button.classList.toggle(
      "active",
      discipline.discipline_id === state.selectedDiscipline,
    );
    button.textContent = discipline.name;
    button.addEventListener("click", () => {
      state.selectedDiscipline = discipline.discipline_id;
      renderDisciplineFilters();
      renderUniversityDirectory();
    });
    elements.disciplineFilters.append(button);
  });
}

function renderWarnings(warnings) {
  elements.warningList.replaceChildren();
  warnings.forEach((warning) => {
    const item = document.createElement("div");
    item.className = "warning-item";
    item.textContent = warning;
    elements.warningList.append(item);
  });
}

function courseClass(course) {
  if (course.rule_type === "CAPSTONE") {
    return "course-item capstone";
  }
  if (course.rule_type === "RESEARCH_CORE") {
    return "course-item research";
  }
  return "course-item";
}

function renderSelectedPlan(plan) {
  state.selectedPlan = plan;
  elements.selectedPlanName.textContent = plan.name;
  elements.selectedPlanDescription.textContent = plan.description;
  elements.selectedPlanSemesters.textContent = String(plan.estimated_semesters);
  elements.semesterTimeline.replaceChildren();

  plan.semesters.forEach((semester) => {
    const row = document.createElement("div");
    row.className = "semester-row";
    const heading = document.createElement("div");
    heading.className = "semester-name";
    const name = document.createElement("strong");
    const count = document.createElement("span");
    name.textContent = semester.semester;
    count.textContent = `${semester.courses.length} 门课程`;
    heading.append(name, count);

    const courses = document.createElement("div");
    courses.className = "semester-courses";
    semester.courses.forEach((course) => {
      const item = document.createElement("div");
      item.className = courseClass(course);
      const code = document.createElement("strong");
      const title = document.createElement("small");
      code.textContent = `${course.course_code} · ${roleLabels[course.rule_type] || course.rule_type}`;
      title.textContent = course.course_name;
      item.title = course.course_name;
      item.append(code, title);
      courses.append(item);
    });

    const credits = document.createElement("div");
    credits.className = "semester-credits";
    credits.textContent = `${semester.total_credits} cp`;
    row.append(heading, courses, credits);
    elements.semesterTimeline.append(row);
  });

  document.querySelectorAll(".plan-tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.planId === plan.plan_id);
  });
}

function renderPlanTabs(plans) {
  elements.planTabs.replaceChildren();
  plans.forEach((plan) => {
    const button = document.createElement("button");
    button.className = "plan-tab";
    button.type = "button";
    button.role = "tab";
    button.dataset.planId = plan.plan_id;
    button.textContent = plan.name;
    button.addEventListener("click", () => renderSelectedPlan(plan));
    elements.planTabs.append(button);
  });
}

function renderPlanResponse(payload) {
  state.planResponse = payload;
  elements.plannerEmpty.classList.add("hidden");
  elements.planResults.classList.remove("hidden");
  elements.summaryEntry.textContent = `EL ${payload.program.entry_level}`;
  elements.summaryCredits.textContent = `${payload.remaining_credits} cp`;
  elements.summaryValid.textContent = `${payload.validation.valid_plan_count} / ${payload.plans.length}`;
  elements.summaryConfidence.textContent =
    payload.confidence === "high" ? "高" : "需复核";
  renderWarnings(payload.warnings);
  renderPlanTabs(payload.plans);
  renderSelectedPlan(payload.plans[0]);
  renderTrace(payload.trace);
  renderSourceList(payload.source_ids);
}

async function generatePlan(event) {
  event.preventDefault();
  const completed = [
    ...elements.completedCourses.querySelectorAll("input:checked"),
  ].map((input) => input.value);
  const request = {
    program_variant_id: elements.programVariant.value,
    handbook_year: 2026,
    study_stream: elements.studyStream.value,
    completed_courses: completed,
    max_courses_per_semester: Number(elements.maxLoad.value),
    preserve_policy_flexibility: elements.policyFlexibility.checked,
    start_semester: elements.startSemester.value,
  };
  setBusy(true);
  try {
    const payload = await api("/api/plans/generate", {
      method: "POST",
      body: JSON.stringify(request),
    });
    renderPlanResponse(payload);
    showToast("已生成并校验三套毕业路径。");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setBusy(false);
  }
}

function resetPlanner() {
  elements.planForm.reset();
  fillStreamSelect(elements.studyStream, currentProgram());
  elements.planResults.classList.add("hidden");
  elements.plannerEmpty.classList.remove("hidden");
  state.planResponse = null;
  state.selectedPlan = null;
}

function renderComparison(payload) {
  const [first, second] = payload.programs;
  const rows = [
    ["比较项", programLabel(first), programLabel(second)],
    ["完成学分", `${first.credits_to_complete} cp`, `${second.credits_to_complete} cp`],
    ["典型时长", `${first.duration_years} 年`, `${second.duration_years} 年`],
    ["Entry credit", `${first.entry_credit_points} cp`, `${second.entry_credit_points} cp`],
    ["必修学分", `${first.mandatory_credits} cp`, `${second.mandatory_credits} cp`],
    ["选修空间", `${first.elective_credits} cp`, `${second.elective_credits} cp`],
  ];
  const table = document.createElement("div");
  table.className = "comparison-table";
  rows.forEach((row, rowIndex) => {
    row.forEach((value, columnIndex) => {
      const cell = document.createElement("div");
      if (columnIndex === 0) {
        cell.className = "label";
      }
      const content = document.createElement(rowIndex === 0 ? "strong" : "span");
      content.textContent = value;
      cell.append(content);
      table.append(cell);
    });
  });
  const note = document.createElement("div");
  note.className = "comparison-note";
  note.textContent = payload.risk_notice;
  elements.compareResults.replaceChildren(table, note);
}

async function comparePrograms(event) {
  event.preventDefault();
  try {
    const payload = await api("/api/programs/compare", {
      method: "POST",
      body: JSON.stringify({
        first_program_variant_id: elements.compareFirst.value,
        second_program_variant_id: elements.compareSecond.value,
        handbook_year: 2026,
        study_stream: elements.compareStream.value,
      }),
    });
    renderComparison(payload);
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function classifyCourse(event) {
  event.preventDefault();
  try {
    const payload = await api("/api/courses/classify", {
      method: "POST",
      body: JSON.stringify({
        program_variant_id: elements.classifierProgram.value,
        handbook_year: 2026,
        study_stream: elements.classifierStream.value,
        course_code: elements.classifierCourse.value,
      }),
    });
    const title = document.createElement("h2");
    const role = document.createElement("span");
    const detail = document.createElement("p");
    title.textContent = `${payload.course.course_code} · ${payload.course.course_name}`;
    role.className = "role-badge";
    role.textContent = roleLabels[payload.rule_type] || payload.rule_type;
    detail.textContent = payload.credit_group
      ? `计入学分组：${payload.credit_group}`
      : "该课程不计入当前 Entry Level 与 Study Stream。";
    elements.classifierResult.replaceChildren(title, role, detail);
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function startSaveConfirmation() {
  if (!state.selectedPlan || !state.planResponse) {
    return;
  }
  state.pendingThreadId = `plan-${Date.now().toString(36)}`;
  const action = {
    tool_name: "save_study_plan",
    arguments: {
      plan_id: state.selectedPlan.plan_id,
      plan_name: state.selectedPlan.name,
      program_variant_id: state.planResponse.program.program_variant_id,
      semester_count: state.selectedPlan.estimated_semesters,
    },
  };
  try {
    const token = await sessionToken();
    await api(
      `/approval/${encodeURIComponent(state.pendingThreadId)}/start`,
      {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: JSON.stringify(action),
      },
    );
    elements.confirmPreview.innerHTML = `
      <dl>
        <div><dt>项目</dt><dd>${state.planResponse.program.program_code} · EL ${state.planResponse.program.entry_level}</dd></div>
        <div><dt>方案</dt><dd>${state.selectedPlan.name}</dd></div>
        <div><dt>预计学期</dt><dd>${state.selectedPlan.estimated_semesters}</dd></div>
        <div><dt>动作</dt><dd>保存到个人学习方案</dd></div>
      </dl>
    `;
    elements.confirmDialog.showModal();
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function decideSave(approved) {
  if (!state.pendingThreadId) {
    return;
  }
  try {
    const token = await sessionToken();
    const payload = await api(
      `/approval/${encodeURIComponent(state.pendingThreadId)}/resume`,
      {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: JSON.stringify({ approved }),
      },
    );
    elements.confirmDialog.close();
    state.pendingThreadId = null;
    showToast(
      payload.status === "executed"
        ? "方案已确认保存，执行次数为 1。"
        : "已放弃保存，未执行副作用。",
    );
  } catch (error) {
    showToast(error.message, "error");
  }
}

function switchView(viewName) {
  document.querySelectorAll(".view").forEach((view) => {
    view.classList.toggle("hidden", view.id !== `${viewName}View`);
  });
  document.querySelectorAll(".nav-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === viewName);
  });
}

async function loadCatalog() {
  try {
    state.catalog = await api("/api/catalog");
    elements.retrievedDate.textContent = state.catalog.retrieved_at;
    elements.sourceCount.textContent = String(state.catalog.sources.length);
    elements.catalogVersion.textContent = state.catalog.catalog_version;
    renderDisciplineFilters();
    renderUniversityDirectory();

    [
      elements.programVariant,
      elements.compareFirst,
      elements.compareSecond,
      elements.classifierProgram,
    ].forEach((select) => fillProgramSelect(select, state.catalog.programs));
    elements.compareSecond.selectedIndex = 1;

    fillStreamSelect(elements.studyStream, currentProgram());
    fillStreamSelect(elements.compareStream, currentProgram(elements.compareFirst));
    fillStreamSelect(
      elements.classifierStream,
      currentProgram(elements.classifierProgram),
    );

    elements.classifierCourse.replaceChildren();
    state.catalog.courses.forEach((course) => {
      const option = document.createElement("option");
      option.value = course.course_code;
      option.textContent = `${course.course_code} · ${course.course_name}`;
      elements.classifierCourse.append(option);
    });
    renderCourseOptions();
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function checkHealth() {
  const wrapper = document.querySelector(".service-state");
  try {
    const payload = await api("/health");
    wrapper.classList.add("online");
    elements.serviceLabel.textContent = `${payload.product} 正常`;
  } catch {
    wrapper.classList.add("offline");
    elements.serviceLabel.textContent = "服务异常";
  }
}

elements.planForm.addEventListener("submit", generatePlan);
elements.resetPlanButton.addEventListener("click", resetPlanner);
elements.programVariant.addEventListener("change", () => {
  fillStreamSelect(elements.studyStream, currentProgram());
});
elements.compareForm.addEventListener("submit", comparePrograms);
elements.compareFirst.addEventListener("change", () => {
  fillStreamSelect(
    elements.compareStream,
    currentProgram(elements.compareFirst),
  );
});
elements.classifierForm.addEventListener("submit", classifyCourse);
elements.classifierProgram.addEventListener("change", () => {
  fillStreamSelect(
    elements.classifierStream,
    currentProgram(elements.classifierProgram),
  );
});
elements.savePlanButton.addEventListener("click", startSaveConfirmation);
elements.confirmSaveButton.addEventListener("click", () => decideSave(true));
elements.rejectSaveButton.addEventListener("click", () => decideSave(false));
elements.closeDialogButton.addEventListener("click", () => decideSave(false));
document.querySelectorAll(".nav-button").forEach((button) => {
  button.addEventListener("click", () => switchView(button.dataset.view));
});

loadCatalog();
checkHealth();
