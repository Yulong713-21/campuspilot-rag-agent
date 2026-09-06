export const verifiedPrompt = "我想尽快毕业，帮我规划一下";

export function buildPlannerRequest(elements) {
  const completedCourses = [...elements.completedCourses.querySelectorAll("input:checked")]
    .map((input) => input.value);
  return {
    program_variant_id: elements.programVariant.value,
    handbook_year: 2026,
    study_stream: elements.studyStream.value,
    completed_courses: completedCourses,
    max_courses_per_semester: Number(elements.maxLoad.value),
    preserve_policy_flexibility: elements.policyFlexibility.checked,
    start_semester: elements.startSemester.value,
  };
}

export function verifiedChatRequest(elements, conversationHistory = []) {
  return {
    message: verifiedPrompt,
    ...buildPlannerRequest(elements),
    conversation_history: conversationHistory.slice(-6),
  };
}
