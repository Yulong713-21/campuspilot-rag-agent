const $ = (id) => document.getElementById(id);
const authPanel = $("authPanel");
const adminContent = $("adminContent");
const notice = $("notice");
let originalConfig = null;

function adminToken() {
  return sessionStorage.getItem("campuspilotAdminToken") || "";
}

async function adminFetch(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("X-CampusPilot-Admin-Token", adminToken());
  if (options.body) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...options, headers });
  let payload = {};
  try { payload = await response.json(); } catch (_) { payload = {}; }
  if (!response.ok) throw new Error(payload.detail || `请求失败：${response.status}`);
  return payload;
}

function setRuntime(ok, text) {
  $("runtimeDot").className = `status-dot ${ok ? "ok" : "error"}`;
  $("runtimeText").textContent = text;
}

function showNotice(message, kind = "info") {
  notice.hidden = false;
  notice.className = `notice ${kind === "info" ? "" : kind}`.trim();
  notice.textContent = message;
}

function fillForm(config, runtime) {
  originalConfig = structuredClone(config);
  $("cloudEnabled").checked = config.cloud_llm_enabled;
  $("baseUrl").value = config.openai_base_url;
  $("modelName").value = config.openai_model;
  $("apiKey").value = "";
  $("apiKeyHint").textContent = config.api_key_configured
    ? `已配置密钥 ${config.api_key_hint || ""}，留空保持不变`
    : "尚未配置 API Key";
  $("timeoutSeconds").value = config.openai_timeout_seconds;
  $("retrievalMode").value = config.retrieval_mode;
  $("vectorEnabled").checked = config.vector_search_enabled;
  $("rerankerEnabled").checked = config.reranker_enabled;
  $("rateLimit").value = config.rate_limit_per_minute;
  $("maxUploadMb").value = Math.round(config.max_upload_bytes / 1024 / 1024);
  $("envFilePath").textContent = config.env_file;
  $("saveState").textContent = "配置已同步";
  setRuntime(runtime.llm_client_active, runtime.llm_client_active
    ? `运行中 · ${runtime.model}`
    : "模型客户端未启用");
}

async function loadConfig() {
  const payload = await adminFetch("/api/admin/config");
  fillForm(payload.config, payload.runtime);
  authPanel.hidden = true;
  adminContent.hidden = false;
}

function collectConfig() {
  return {
    cloud_llm_enabled: $("cloudEnabled").checked,
    openai_base_url: $("baseUrl").value.trim(),
    openai_model: $("modelName").value.trim(),
    api_key: $("apiKey").value.trim() || null,
    openai_timeout_seconds: Number($("timeoutSeconds").value),
    retrieval_mode: $("retrievalMode").value,
    vector_search_enabled: $("vectorEnabled").checked,
    reranker_enabled: $("rerankerEnabled").checked,
    rate_limit_per_minute: Number($("rateLimit").value),
    max_upload_bytes: Number($("maxUploadMb").value) * 1024 * 1024,
  };
}

async function saveConfig() {
  $("saveButton").disabled = true;
  try {
    const payload = await adminFetch("/api/admin/config", {
      method: "PUT",
      body: JSON.stringify(collectConfig()),
    });
    const needsRestart = payload.restart_required_fields.length > 0;
    showNotice(
      needsRestart
        ? `${payload.message} 需重启：${payload.restart_required_fields.join("、")}`
        : `${payload.message} 已热更新：${payload.hot_applied_fields.join("、") || "无运行时变更"}`,
      needsRestart ? "warning" : "info",
    );
    await loadConfig();
  } catch (error) {
    showNotice(error.message, "error");
  } finally {
    $("saveButton").disabled = false;
  }
}

function renderUsage(usage, elapsedMs) {
  const entries = [
    ["输入 Token", usage.prompt_tokens ?? "-"],
    ["输出 Token", usage.completion_tokens ?? "-"],
    ["耗时", `${elapsedMs} ms`],
  ];
  $("usageGrid").replaceChildren(...entries.map(([label, value]) => {
    const wrapper = document.createElement("div");
    const term = document.createElement("dt");
    const detail = document.createElement("dd");
    term.textContent = label;
    detail.textContent = value;
    wrapper.append(term, detail);
    return wrapper;
  }));
}

async function testLlm() {
  $("testButton").disabled = true;
  $("testOutput").textContent = "正在请求模型…";
  $("testMeta").textContent = "测试中";
  try {
    const payload = await adminFetch("/api/admin/llm/test", {
      method: "POST",
      body: JSON.stringify({
        prompt: $("testPrompt").value.trim(),
        temperature: Number($("temperature").value),
        max_tokens: Number($("maxTokens").value),
      }),
    });
    $("testOutput").textContent = payload.content || "模型返回了空内容。";
    $("testMeta").textContent = payload.model || "未知模型";
    renderUsage(payload.usage || {}, payload.elapsed_ms);
    setRuntime(true, `连接正常 · ${payload.model}`);
  } catch (error) {
    $("testOutput").textContent = error.message;
    $("testMeta").textContent = "测试失败";
    $("usageGrid").replaceChildren();
    setRuntime(false, "模型连接失败");
  } finally {
    $("testButton").disabled = false;
  }
}

$("connectButton").addEventListener("click", async () => {
  sessionStorage.setItem("campuspilotAdminToken", $("adminToken").value);
  try { await loadConfig(); } catch (error) {
    sessionStorage.removeItem("campuspilotAdminToken");
    showNotice(error.message, "error");
  }
});
$("saveButton").addEventListener("click", saveConfig);
$("reloadButton").addEventListener("click", () => loadConfig().catch((error) => showNotice(error.message, "error")));
$("testButton").addEventListener("click", testLlm);
$("temperature").addEventListener("input", () => { $("temperatureValue").textContent = $("temperature").value; });
document.querySelectorAll(".nav-item").forEach((button) => button.addEventListener("click", () => {
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.remove("active"));
  button.classList.add("active");
  $(button.dataset.target).scrollIntoView({ behavior: "smooth", block: "start" });
}));
document.querySelectorAll("input, select, textarea").forEach((input) => input.addEventListener("change", () => {
  if (originalConfig) $("saveState").textContent = "有未保存修改";
}));

if (adminToken()) {
  loadConfig().catch(() => sessionStorage.removeItem("campuspilotAdminToken"));
}
