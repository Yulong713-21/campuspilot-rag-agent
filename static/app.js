const state = {
  catalog: null,
  planResponse: null,
  selectedPlan: null,
  pendingThreadId: null,
  busy: false,
  selectedDiscipline: "computing",
  sessionToken: window.localStorage.getItem("campuspilot-session-token"),
  chatHistory: [],
  chatThreadId:
    window.localStorage.getItem("campuspilot-chat-thread") ||
    `web-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
  admissionPrograms: [],
};

window.localStorage.setItem("campuspilot-chat-thread", state.chatThreadId);

const elements = Object.fromEntries(
  [
    "serviceLabel",
    "retrievedDate",
    "sourceCount",
    "catalogVersion",
    "chatForm",
    "chatInput",
    "chatMessages",
    "chatSuggestions",
    "sendChatButton",
    "clearChatButton",
    "admissionForm",
    "admissionUniversity",
    "admissionDiscipline",
    "admissionProgram",
    "undergraduateInstitution",
    "undergraduateMajor",
    "admissionScore",
    "admissionScale",
    "admissionGoal",
    "transcriptFile",
    "parseTranscriptButton",
    "recommendAdmissionButton",
    "evaluateAdmissionButton",
    "admissionEmpty",
    "transcriptResult",
    "admissionResult",
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
  const hasFormData = options.body instanceof FormData;
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(hasFormData ? {} : { "Content-Type": "application/json" }),
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

function createPiaMessage(content) {
  const article = document.createElement("article");
  article.className = "chat-message assistant";
  const avatar = document.createElement("span");
  avatar.className = "message-avatar";
  avatar.textContent = "P";
  const body = document.createElement("div");
  body.className = "message-body";
  const name = document.createElement("strong");
  name.textContent = "Pia";
  const text = document.createElement("p");
  text.textContent = content;
  body.append(name, text);
  article.append(avatar, body);
  return { article, body };
}

function renderProgramRecommendations(container, payload) {
  const recommendationPayload = payload.program_recommendations || payload;
  const recommendations = recommendationPayload?.recommendations || [];
  if (!recommendations.length) {
    return;
  }
  const grid = document.createElement("div");
  grid.className = "chat-program-grid";
  recommendations.forEach((program, index) => {
    const card = document.createElement("article");
    card.className = "chat-program-card";
    const rank = document.createElement("span");
    rank.className = "program-rank";
    rank.textContent = `路线 ${program.rank || index + 1}`;
    const title = document.createElement("strong");
    title.textContent = program.display_name_zh || program.program_name || program.name;
    const university = document.createElement("small");
    university.textContent = program.university_name || "";
    const reason = document.createElement("p");
    reason.textContent = (program.reasons || []).join("；") || program.tradeoff || "建议继续核对课程结构与录取要求。";
    card.append(rank, title, university, reason);
    if (program.official_url) {
      const link = document.createElement("a");
      link.href = program.official_url;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = "查看官方项目页";
      card.append(link);
    }
    grid.append(card);
  });
  container.append(grid);
}

function renderChatEvidence(container, evidence = []) {
  if (!evidence.length) {
    return;
  }
  const details = document.createElement("details");
  details.className = "chat-details";
  const summary = document.createElement("summary");
  summary.textContent = `查看依据（${evidence.length}）`;
  const list = document.createElement("ul");
  evidence.forEach((item) => {
    const row = document.createElement("li");
    const link = document.createElement("a");
    link.href = item.source_url || item.url || "#";
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = item.title || item.source_type || "官方来源";
    const excerpt = document.createElement("span");
    excerpt.textContent = item.excerpt || item.content || "";
    row.append(link, excerpt);
    list.append(row);
  });
  details.append(summary, list);
  container.append(details);
}

function renderChatTrace(container, payload) {
  const tools = payload.trace_tools || [];
  if (!tools.length) {
    return;
  }
  const details = document.createElement("details");
  details.className = "chat-details trace";
  const summary = document.createElement("summary");
  summary.textContent = `查看处理过程（${tools.length} 步）`;
  const flow = document.createElement("p");
  flow.textContent = tools.join(" → ");
  details.append(summary, flow);
  container.append(details);
}

function appendChatMessage(role, content, payload = null) {
  let article;
  let body;
  if (role === "assistant") {
    ({ article, body } = createPiaMessage(content));
  } else {
    article = document.createElement("article");
    article.className = "chat-message user";
    body = document.createElement("div");
    body.className = "message-body";
    const name = document.createElement("strong");
    name.textContent = "我";
    const text = document.createElement("p");
    text.textContent = content;
    body.append(name, text);
    article.append(body);
  }
  if (payload) {
    renderProgramRecommendations(body, payload);
    const evidence = payload.evidence || payload.documents || [];
    renderChatEvidence(body, evidence);
    renderChatTrace(body, payload);
  }
  elements.chatMessages.append(article);
  elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
  return article;
}

function setChatBusy(busy) {
  elements.sendChatButton.disabled = busy;
  elements.chatInput.disabled = busy;
  elements.sendChatButton.textContent = busy ? "Pia 思考中" : "发送";
}

async function sendChatMessage(message) {
  const trimmed = message.trim();
  if (!trimmed) {
    return;
  }
  const previousHistory = state.chatHistory.slice(-6);
  appendChatMessage("user", trimmed);
  state.chatHistory.push({ role: "user", content: trimmed.slice(0, 2000) });
  elements.chatInput.value = "";
  setChatBusy(true);
  const waiting = createPiaMessage("正在理解你的目标并选择合适的工具……");
  waiting.article.classList.add("pending");
  elements.chatMessages.append(waiting.article);
  elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
  try {
    const payload = await api("/api/agent/chat", {
      method: "POST",
      body: JSON.stringify({
        thread_id: state.chatThreadId,
        message: trimmed,
        conversation_history: previousHistory,
      }),
    });
    waiting.article.remove();
    const answer =
      payload.message ||
      payload.program_recommendations?.message ||
      "我已经完成处理，但暂时没有生成可展示的回答。";
    appendChatMessage("assistant", answer, payload);
    state.chatHistory.push({ role: "assistant", content: answer.slice(0, 2000) });
  } catch (error) {
    waiting.article.remove();
    appendChatMessage("assistant", `这次请求没有完成：${error.message}`);
  } finally {
    setChatBusy(false);
    elements.chatInput.focus();
  }
}

function resetChat() {
  state.chatHistory = [];
  state.chatThreadId = `web-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  window.localStorage.setItem("campuspilot-chat-thread", state.chatThreadId);
  elements.chatMessages.replaceChildren();
  elements.chatMessages.append(
    createPiaMessage("新对话已经开始。告诉我你的成绩、目标学校、就业想法或学习偏好吧。").article,
  );
}

async function loadAdmissionPrograms() {
  const university = elements.admissionUniversity.value;
  if (!university) {
    state.admissionPrograms = [];
    elements.admissionProgram.replaceChildren(new Option("先选择目标学校", ""));
    elements.admissionProgram.disabled = true;
    return;
  }
  elements.admissionProgram.disabled = true;
  elements.admissionProgram.replaceChildren(new Option("加载项目中……", ""));
  try {
    const params = new URLSearchParams({
      university,
      discipline_id: elements.admissionDiscipline.value,
    });
    const payload = await api(`/api/admissions/programs?${params}`);
    state.admissionPrograms = payload.programs || [];
    elements.admissionProgram.replaceChildren(new Option("请选择具体项目", ""));
    state.admissionPrograms.forEach((program) => {
      const suffix = program.evaluation_ready ? " · 规则已核验" : " · 可浏览";
      elements.admissionProgram.append(
        new Option(`${program.name}${suffix}`, program.program_code || program.name),
      );
    });
    elements.admissionProgram.disabled = false;
  } catch (error) {
    elements.admissionProgram.replaceChildren(new Option("项目加载失败", ""));
    showToast(error.message, "error");
  }
}

function renderTranscriptResult(payload) {
  elements.admissionEmpty.classList.add("hidden");
  elements.transcriptResult.classList.remove("hidden");
  const profile = payload.candidate_profile || {};
  elements.transcriptResult.replaceChildren();
  const heading = document.createElement("div");
  heading.className = "result-heading";
  const title = document.createElement("strong");
  title.textContent = "成绩单读取结果";
  const status = document.createElement("span");
  status.textContent = payload.status;
  heading.append(title, status);
  const message = document.createElement("p");
  message.textContent = payload.message;
  const facts = document.createElement("dl");
  [
    ["本科院校", profile.institution || "未识别"],
    ["成绩", profile.overall_score == null ? "未识别" : `${profile.overall_score}/${profile.score_scale}`],
    ["已修学分", profile.completed_credits ?? "未识别"],
    ["课程条目", `${(profile.courses || []).length} 门`],
  ].forEach(([label, value]) => {
    const row = document.createElement("div");
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = label;
    dd.textContent = value;
    row.append(dt, dd);
    facts.append(row);
  });
  const notice = document.createElement("small");
  notice.textContent = "解析字段必须由你确认后才能用于申请评估。";
  elements.transcriptResult.append(heading, message, facts, notice);
  if (profile.institution) {
    elements.undergraduateInstitution.value = profile.institution;
  }
  if (profile.overall_score != null) {
    elements.admissionScore.value = profile.overall_score;
    elements.admissionScale.value = String(profile.score_scale || 100);
  }
}

async function parseTranscript() {
  const file = elements.transcriptFile.files[0];
  if (!file) {
    showToast("请先选择 PDF 成绩单。", "error");
    return;
  }
  elements.parseTranscriptButton.disabled = true;
  elements.parseTranscriptButton.textContent = "读取中";
  const form = new FormData();
  form.append("file", file);
  try {
    const payload = await api("/api/admissions/transcripts/parse?provider=local_pdf", {
      method: "POST",
      body: form,
    });
    renderTranscriptResult(payload);
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    elements.parseTranscriptButton.disabled = false;
    elements.parseTranscriptButton.textContent = "读取成绩单";
  }
}

function renderAdmissionResult(payload, titleText = "申请分析结果") {
  elements.admissionEmpty.classList.add("hidden");
  elements.admissionResult.classList.remove("hidden");
  elements.admissionResult.replaceChildren();
  const heading = document.createElement("div");
  heading.className = "result-heading";
  const title = document.createElement("strong");
  title.textContent = titleText;
  const status = document.createElement("span");
  status.textContent = payload.status || payload.error_code || "COMPLETED";
  heading.append(title, status);
  const message = document.createElement("p");
  message.textContent = payload.message || "已生成候选结果。";
  elements.admissionResult.append(heading, message);
  renderProgramRecommendations(elements.admissionResult, payload);
  renderChatEvidence(elements.admissionResult, payload.evidence || []);
  if (payload.missing_fields?.length) {
    const missing = document.createElement("p");
    missing.className = "result-notice";
    missing.textContent = `仍需补充：${payload.missing_fields.join("、")}`;
    elements.admissionResult.append(missing);
  }
}

async function recommendAdmissionPrograms() {
  const score = elements.admissionScore.value;
  const goal = elements.admissionGoal.value.trim();
  const prompt = [
    goal,
    elements.undergraduateMajor.value && `本科专业：${elements.undergraduateMajor.value}`,
    score && `当前成绩：${score}/${elements.admissionScale.value}`,
  ].filter(Boolean).join("；") || "请根据我的背景推荐澳洲八大授课型硕士项目";
  elements.recommendAdmissionButton.disabled = true;
  elements.recommendAdmissionButton.textContent = "Pia 分析中";
  try {
    const request = {
      prompt,
      university: elements.admissionUniversity.value || null,
      undergraduate_major: elements.undergraduateMajor.value || null,
      career_goal: goal || null,
      score_value: score ? Number(score) : null,
      score_scale: score ? Number(elements.admissionScale.value) : null,
      max_results: 3,
    };
    const payload = await api("/api/admissions/recommend", {
      method: "POST",
      body: JSON.stringify(request),
    });
    renderAdmissionResult(payload, "Pia 推荐的候选项目");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    elements.recommendAdmissionButton.disabled = false;
    elements.recommendAdmissionButton.textContent = "让 Pia 推荐项目";
  }
}

async function evaluateAdmission(event) {
  event.preventDefault();
  if (!elements.admissionUniversity.value || !elements.admissionProgram.value) {
    showToast("请先选择目标学校和具体项目；不确定时先让 Pia 推荐。", "error");
    return;
  }
  const score = elements.admissionScore.value;
  const scale = Number(elements.admissionScale.value);
  const request = {
    university: elements.admissionUniversity.value,
    program: elements.admissionProgram.value,
    discipline_id: elements.admissionDiscipline.value,
    undergraduate_institution: elements.undergraduateInstitution.value || null,
    undergraduate_major: elements.undergraduateMajor.value || null,
    score_value: score ? Number(score) : null,
    score_scale: score ? scale : null,
    score_basis: score ? (scale === 100 ? "RAW_PERCENT" : "GPA") : null,
  };
  elements.evaluateAdmissionButton.disabled = true;
  elements.evaluateAdmissionButton.textContent = "核对中";
  try {
    const payload = await api("/api/admissions/evaluate", {
      method: "POST",
      body: JSON.stringify(request),
    });
    renderAdmissionResult(payload);
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    elements.evaluateAdmissionButton.disabled = false;
    elements.evaluateAdmissionButton.textContent = "核对公开门槛";
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
elements.chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  sendChatMessage(elements.chatInput.value);
});
elements.chatInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    elements.chatForm.requestSubmit();
  }
});
elements.chatSuggestions.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-prompt]");
  if (button) {
    sendChatMessage(button.dataset.prompt);
  }
});
elements.clearChatButton.addEventListener("click", resetChat);
elements.admissionUniversity.addEventListener("change", loadAdmissionPrograms);
elements.admissionDiscipline.addEventListener("change", loadAdmissionPrograms);
elements.parseTranscriptButton.addEventListener("click", parseTranscript);
elements.recommendAdmissionButton.addEventListener("click", recommendAdmissionPrograms);
elements.admissionForm.addEventListener("submit", evaluateAdmission);
document.querySelectorAll(".nav-button").forEach((button) => {
  button.addEventListener("click", () => switchView(button.dataset.view));
});

loadCatalog();
checkHealth();
