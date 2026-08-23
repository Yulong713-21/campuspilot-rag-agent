function messageArticle(role, text, { requestId = "" } = {}) {
  const article = document.createElement("article");
  article.className = `message ${role === "user" ? "user-message" : "assistant-message"}`;

  if (role === "assistant") {
    const avatar = document.createElement("span");
    avatar.className = "avatar";
    avatar.setAttribute("aria-hidden", "true");
    avatar.textContent = "P";
    article.append(avatar);
  }

  const body = document.createElement("div");
  const label = document.createElement("strong");
  const content = document.createElement("p");
  label.textContent = role === "user" ? "你" : "Pia";
  content.textContent = text;
  body.append(label, content);
  if (requestId) {
    const meta = document.createElement("small");
    meta.className = "message-meta";
    meta.textContent = `Request ${requestId}`;
    body.append(meta);
  }
  article.append(body);
  return article;
}

export function createConversation(container) {
  const history = [];

  function append(role, text, options = {}) {
    const normalized = String(text || "").trim();
    if (!normalized) return;
    container.append(messageArticle(role, normalized, options));
    container.lastElementChild.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function remember(role, text) {
    const normalized = String(text || "").trim();
    if (!normalized) return;
    history.push({ role, content: normalized.slice(0, 2000) });
    if (history.length > 6) history.splice(0, history.length - 6);
  }

  function addUser(text) {
    append("user", text);
    remember("user", text);
  }

  function addAssistant(text, options = {}) {
    append("assistant", text, options);
    remember("assistant", text);
  }

  return {
    addUser,
    addAssistant,
    history: () => history.map((message) => ({ ...message })),
  };
}

export function assistantText(payload) {
  if (typeof payload.message === "string" && payload.message.trim()) return payload.message;
  if (typeof payload.answer === "string" && payload.answer.trim()) return payload.answer;
  if (payload.status === "needs_clarification") return "还需要补充项目和方向信息，我才能继续规划。";
  return "我已经完成这次处理。你可以继续补充目标或课程信息。";
}
