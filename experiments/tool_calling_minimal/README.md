# 最小 Tool Calling 实验

这个实验是 EduRAG 第一次面向 Agent 的工具化改造。

当前还没有让 LLM 自主选择工具，而是先建立稳定的工具边界：

- `search_faq(query)`
- `search_rag(query, source_filter, timeout_seconds)`

第一版路由策略是确定性的：

```text
search_faq
  -> hit: return FAQ answer
  -> miss: call search_rag and return retrieved context
```

后续会把同一套工具边界接入 LLM Tool Calling、LangChain、LangGraph 和 MCP。

## 运行真实服务实验

From `D:\agentdev\edurag-agent-lab`:

```powershell
$env:EDURAG_PROJECT_ROOT="D:\agentdev\integrated_qa_system"
.\.venv\Scripts\python.exe experiments\tool_calling_minimal\demo.py "AI学科课程大纲内容是什么？" ai
```

## 运行纯路由实验

这个实验不连接 Redis、MySQL 和 Milvus，用固定结果观察 Agent 如何区分 FAQ 命中、RAG 有证据、RAG 空结果、临时故障和不可重试故障：

```powershell
.\.venv\Scripts\python.exe experiments\tool_calling_minimal\routing_demo.py
```

重点观察 `route_trace`、`route_reason`、`answer_source`、`error_type`、`retryable` 和 `next_action`。

## 运行有限重试实验

这个实验对比“首次失败后恢复”和“重试预算耗尽”，并用假的等待函数记录退避时间：

```powershell
.\.venv\Scripts\python.exe experiments\tool_calling_minimal\retry_demo.py
```

重点观察 `rag_call_count`、`retry_count`、`recorded_backoff_seconds` 和最终 `route_reason`。

## 运行退避上限与抖动实验

```powershell
.\.venv\Scripts\python.exe experiments\tool_calling_minimal\backoff_demo.py
```

重点比较 `backoff_cap_seconds` 和 `actual_backoff_seconds`：前者逐步增长并在上限处停止，后者加入抖动后不一定严格递增。

## 运行 Deadline 实验

对比 8 秒预算和 11 秒预算能否允许第二次重试：

```powershell
.\.venv\Scripts\python.exe experiments\tool_calling_minimal\deadline_demo.py
```

重点观察 `rag_call_count`、`retry_count`、`route_reason`、`time_budget.remaining_seconds`
和 `rag_timeout_seconds`。后者展示同一份 Deadline 如何在调用与退避后逐步缩小，
并最终作为 Milvus 检索 Timeout 向下传播。

## 运行 LLM Tool Calling 循环实验

确定性脚本模型会依次选择 FAQ、RAG，再生成最终答案：

```powershell
.\.venv\Scripts\python.exe experiments\tool_calling_minimal\llm_tool_loop_demo.py
```

重点观察：

```text
tool_round_count = 2
trace_tools = ["search_faq", "search_rag"]
route_reason = llm_answered_after_tools
```

## 使用真实 Ollama 选择工具

确保 Ollama 服务已加载支持 Tool Calling 的模型，并且 EduRAG 外部服务可用：

```powershell
$env:EDURAG_OLLAMA_MODEL="qwen3:1.7b"
.\.venv\Scripts\python.exe experiments\tool_calling_minimal\ollama_tool_calling_demo.py "人工智能就业课有哪些阶段？" ai
```

真实模型可能直接回答、只调用 RAG，或先调用 FAQ 再调用 RAG。应用只执行 allowlist 中的工具，并限制最大工具轮次。

## 对比 LLM Agent 的 Deadline 传播与降级

运行对比实验：

```powershell
.\.venv\Scripts\python.exe experiments\tool_calling_minimal\llm_deadline_baseline.py
```

实验使用 Fake Clock 模拟 5 秒预算下的三段耗时：

```text
模型选择工具：1 秒
RAG 检索：3 秒
模型生成答案：2 秒
```

实验比较两种情况：

- 7 秒预算：链路在 6 秒完成，模型依次获得 7 秒和 3 秒，RAG 获得 6 秒。
- 5 秒预算：最终生成只获得剩余 1 秒，超时后使用已有 RAG 资料降级回答。

降级答案会明确提示内容可能不完整，并通过
`answer_source=rag_partial_fallback` 和
`route_reason=llm_deadline_exhausted` 保留可观察性。

## 运行最终生成预算预留实验

```powershell
.\.venv\Scripts\python.exe experiments\tool_calling_minimal\generation_budget_reservation_demo.py
```

实验总预算为 5 秒，并为最终生成预留 2 秒。第一次模型调用耗时 1 秒后，
整个 RAG 操作最多获得 2 秒。RAG 内部首次失败耗时 0.4 秒，退避 0.2 秒，
因此真正留给重试调用的 Timeout 为 1.4 秒。重试在 1.2 秒成功，最终模型
仍获得 2.2 秒并在总耗时 4.8 秒时完成。

## 对比平均值、P95 和 P99 预留策略

```powershell
.\.venv\Scripts\python.exe experiments\tool_calling_minimal\reserve_percentile_comparison.py
```

实验使用 20 条固定请求，对比完整答案、部分降级、缓存降级和浪费的 RAG
时间。它用于说明预算策略需要同时优化质量、延迟和资源，而不是只追求某个
单一成功率。

## 对比不同问题类型的缓存新鲜度策略

```powershell
.\.venv\Scripts\python.exe experiments\tool_calling_minimal\cache_freshness_policy_demo.py
```

实验比较 24 小时课程介绍、2 分钟学费和 24 小时学费。重点观察
`cache_state`、`use_cache` 和 `next_action`，理解答案长度与数据新鲜度是
两个不同的策略维度。

## 运行 RAG 上下文预算装箱实验

```powershell
.\.venv\Scripts\python.exe experiments\tool_calling_minimal\context_budget_packing_demo.py
```

实验在 1896 Token 的 RAG 预算中按相关度选择文档。重点观察
`selected_documents`、`dropped_documents`、`used_tokens` 和
`remaining_tokens`，确认最终答案空间不会被工具结果侵占。

## 运行间接 Prompt Injection 实验

```powershell
.\.venv\Scripts\python.exe experiments\tool_calling_minimal\indirect_prompt_injection_demo.py
```

实验中的恶意文档 B 相关度最高。未防护时它会进入上下文；基线 Guard 会在
装箱前将其隔离，并输出命中的风险信号。关键词 Guard 只是一层可观察防线，
不能替代最小权限、参数约束、人工审批和输出校验。

## 运行副作用工具审批实验

```powershell
.\.venv\Scripts\python.exe experiments\tool_calling_minimal\tool_approval_gate_demo.py
```

实验比较只读检索、创建草稿、批量发信和删除数据库。重点观察自动放行、
人工审批和直接拒绝三种模式，以及审批后修改参数为什么会使原审批失效。
