# CampusPilot Dify 可选接入

CampusPilot 的结构化课程规则、学分计算和方案校验仍由本仓库负责。Dify 可以作为可替换的
Workflow/Chatflow 编排层，用于需求澄清、自然语言解释或运营人员可视化调试，但不是本地
演示的硬依赖。

## 环境变量

```powershell
$env:CAMPUSPILOT_DIFY_API_BASE_URL="https://api.dify.ai/v1"
$env:CAMPUSPILOT_DIFY_API_KEY="app-..."
$env:CAMPUSPILOT_DIFY_TIMEOUT_SECONDS="30"
```

API Key 只能保存在服务端，不能写入浏览器 JavaScript。

## 调用契约

`DifyWorkflowClient` 使用已发布 Workflow 的阻塞接口：

```text
POST {api_base_url}/workflows/run
Authorization: Bearer {api_key}
```

请求包含：

```json
{
  "inputs": {"query": "..."},
  "response_mode": "blocking",
  "user": "stable-end-user-id"
}
```

`user` 必须使用服务端认证后的稳定用户 ID。Dify 调用失败时，核心规划 API 仍可使用本地
LangGraph 与结构化规则运行。

官方资料：

- https://docs.dify.ai/en/api-reference/workflow-runs/run-workflow
- https://docs.dify.ai/en/api-reference/guides/human-input-flow
