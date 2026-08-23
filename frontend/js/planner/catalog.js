import { requestJson } from "../core/api.js";

export async function loadPlannerCatalog() {
  const catalog = await requestJson("/api/catalog");
  const programs = catalog.programs
    .filter((program) => program.program_code === "C6001")
    .sort((left, right) => left.entry_level - right.entry_level);
  if (!programs.length) {
    throw new Error("C6001 培养方案尚未加载。请检查 catalog 配置。");
  }
  return { ...catalog, programs };
}

export function programLabel(program) {
  return `Entry Level ${program.entry_level} · ${program.credits_to_complete} cp · ${program.duration_years} 年`;
}

export function renderProgramOptions(select, programs) {
  select.replaceChildren();
  programs.forEach((program) => {
    const option = document.createElement("option");
    option.value = program.program_variant_id;
    option.textContent = programLabel(program);
    select.append(option);
  });
  select.disabled = false;
}

export function renderStreamOptions(select, program, previous = "") {
  select.replaceChildren();
  program.study_streams.forEach((stream) => {
    const option = document.createElement("option");
    option.value = stream;
    option.textContent = stream === "Industry Experience" ? "Industry Experience · 行业项目" : "Research · 研究路径";
    select.append(option);
  });
  select.value = program.study_streams.includes(previous) ? previous : program.study_streams[0];
  select.disabled = false;
}

export function renderCompletedCourses(container, courses) {
  container.replaceChildren();
  courses.forEach((course) => {
    const label = document.createElement("label");
    const input = document.createElement("input");
    const text = document.createElement("span");
    const code = document.createElement("strong");
    const name = document.createElement("small");
    input.type = "checkbox";
    input.value = course.course_code;
    code.textContent = course.course_code;
    name.textContent = course.course_name;
    text.append(code, name);
    label.append(input, text);
    container.append(label);
  });
}
