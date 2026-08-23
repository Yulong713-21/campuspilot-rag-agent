export class ApiError extends Error {
  constructor(message, { status = 0, requestId = "" } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.requestId = requestId;
  }
}

export async function requestJson(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, { ...options, headers });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof payload.detail === "string"
      ? payload.detail
      : payload.error?.message || "请求未完成，请稍后重试。";
    throw new ApiError(detail, {
      status: response.status,
      requestId: response.headers.get("X-Request-ID") || payload.error?.request_id || "",
    });
  }
  return payload;
}

export async function runButtonTask(button, pendingLabel, task) {
  const originalLabel = button.textContent;
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  button.textContent = pendingLabel;
  try {
    return await task();
  } finally {
    button.disabled = false;
    button.removeAttribute("aria-busy");
    button.textContent = originalLabel;
  }
}
