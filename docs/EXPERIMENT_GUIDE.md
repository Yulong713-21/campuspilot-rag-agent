# EduRAG Agent 实验手册

## 1. 使用方式

所有命令默认在以下目录执行：

```powershell
cd D:\agentdev\edurag-agent-lab
```

先验证环境：

```powershell
.\scripts\run_project_checks.ps1
```

实验分三类：

```text
A 类：纯本地策略实验，不需要外部服务
B 类：需要本地 Ollama
C 类：需要原 EduRAG 的 MySQL / Redis / Milvus
```

## 2. 最终小程序验收

启动：

```powershell
.\scripts\run_agent_api.ps1
```

另开终端：

```powershell
.\.venv\Scripts\python.exe experiments\langgraph_minimal\fastapi_thread_authorization_demo.py `
  --thread-id acceptance-001
```

观察：

| 场景 | 预期 |
| --- | --- |
| 未认证读取 | 401 |
| Alice 创建 | 200 + pending |
| Bob 越权读取 | 404 |
| Bob 越权恢复 | 404 |
| Alice 读取 | 200 + pending |
| Alice 恢复 | 200 + executed |
| Alice 重复恢复 | 409 |

## 3. 推荐必跑实验

### 3.1 FAQ/RAG 路由

```powershell
.\.venv\Scripts\python.exe experiments\tool_calling_minimal\routing_demo.py
```

观察：

- FAQ 命中时 `trace_tools=["search_faq"]`；
- FAQ 未命中时才出现 `search_rag`；
- RAG 返回资料时 `next_action=generate_answer_from_context`。

### 3.2 有限重试与 Deadline

```powershell
.\.venv\Scripts\python.exe experiments\tool_calling_minimal\retry_demo.py
.\.venv\Scripts\python.exe experiments\tool_calling_minimal\deadline_demo.py
```

观察：

- 总调用次数与重试次数不同；
- 空结果不重试；
- 网络错误只在剩余预算允许时重试；
- Deadline 不足时第一次重试也不能开始。

### 3.3 退避与 Jitter

```powershell
.\.venv\Scripts\python.exe experiments\tool_calling_minimal\backoff_demo.py
```

观察：

- 未封顶指数值；
- `max_backoff` 后的上限；
- Jitter 后的实际等待；
- 为什么多个实例不能同时醒来。

### 3.4 生成预算预留

```powershell
.\.venv\Scripts\python.exe experiments\tool_calling_minimal\generation_budget_reservation_demo.py
.\.venv\Scripts\python.exe experiments\tool_calling_minimal\reserve_percentile_comparison.py
```

观察：

- 平均值、P95、P99 预留的差异；
- 完整答案率；
- 缓存降级次数；
- RAG 无效耗时。

### 3.5 Context Token 装箱

```powershell
.\.venv\Scripts\python.exe experiments\tool_calling_minimal\context_budget_packing_demo.py
.\.venv\Scripts\python.exe experiments\langgraph_minimal\evidence_first_repacking_demo.py
```

观察：

- selected / dropped documents；
- used / remaining tokens；
- Memory 挤掉 top RAG 后是否释放；
- 最终能否形成 `RAG A + Memory M2`。

### 3.6 间接 Prompt Injection

```powershell
.\.venv\Scripts\python.exe experiments\tool_calling_minimal\indirect_prompt_injection_demo.py
.\.venv\Scripts\python.exe experiments\langgraph_minimal\safe_context_pipeline_demo.py
```

观察：

- 可疑文档进入 quarantine；
- Prompt 只读取 selected documents；
- 恶意文档不会触发工具执行。

### 3.7 Human Approval

```powershell
.\.venv\Scripts\python.exe experiments\tool_calling_minimal\tool_approval_gate_demo.py
.\.venv\Scripts\python.exe experiments\langgraph_minimal\approval_interrupt_demo.py
```

观察：

- 只读工具和副作用工具的审批差异；
- Interrupt 后 `next_nodes`；
- 同一 `thread_id` 恢复；
- 拒绝时 `execution_count=0`。

### 3.8 Memory

```powershell
.\.venv\Scripts\python.exe experiments\langgraph_minimal\memory_scope_demo.py
.\.venv\Scripts\python.exe experiments\langgraph_minimal\memory_write_policy_demo.py
.\.venv\Scripts\python.exe experiments\langgraph_minimal\memory_precedence_demo.py
.\.venv\Scripts\python.exe experiments\langgraph_minimal\memory_retrieval_demo.py
.\.venv\Scripts\python.exe experiments\langgraph_minimal\memory_consolidation_demo.py
```

观察：

- 同一 thread 与同一 user 的区别；
- 当前轮、长期偏好和系统规则优先级；
- RAG 内容不能定义用户偏好；
- 冲突事实如何 supersede；
- active 版本如何进入 Prompt。

### 3.9 State 数据边界

```powershell
.\.venv\Scripts\python.exe experiments\langgraph_minimal\state_boundaries_demo.py
```

观察：

- Checkpoint 投影；
- Prompt 投影；
- Trace 投影；
- Memory write candidate；
- 哪些字段被主动排除。

### 3.10 Agent 回归评估

```powershell
.\.venv\Scripts\python.exe experiments\langgraph_minimal\agent_regression_eval_demo.py
```

覆盖：

- FAQ 路由；
- RAG 有据回答；
- 空资料降级；
- 注入隔离；
- Deadline；
- Memory 个性化。

### 3.11 RAG 质量诊断

```powershell
.\.venv\Scripts\python.exe experiments\langgraph_minimal\rag_quality_diagnosis_demo.py
```

观察：

- retrieval precision / recall；
- reciprocal rank；
- answer completeness；
- answer groundedness；
- 故障属于检索层、生成层还是评估层。

### 3.12 Judge 校准

固定回放：

```powershell
.\.venv\Scripts\python.exe experiments\langgraph_minimal\judge_calibration_demo.py
```

真实 Ollama：

```powershell
.\.venv\Scripts\python.exe experiments\langgraph_minimal\live_ollama_judge_demo.py `
  --repeats 3 `
  --output logs\live-judge.json
```

观察：

- alignment rate；
- false pass / false reject；
- JSON Schema 错误；
- 同一输入重复投票；
- 稳定是否等于正确。

### 3.13 SQLite 跨进程恢复

```powershell
.\.venv\Scripts\python.exe experiments\langgraph_minimal\sqlite_checkpoint_recovery_demo.py `
  start --thread-id sqlite-demo-001

.\.venv\Scripts\python.exe experiments\langgraph_minimal\sqlite_checkpoint_recovery_demo.py `
  resume --thread-id sqlite-demo-001 --approved true
```

观察：

- 两个 PID 不同；
- 第二个进程开始前仍是 pending；
- 最终 executed；
- checkpoint 数量增加。

### 3.14 副作用幂等

```powershell
.\.venv\Scripts\python.exe experiments\langgraph_minimal\idempotent_side_effect_demo.py
```

观察：

```text
无幂等键：节点尝试 2 次，投递 2 次
相同幂等键：节点尝试 2 次，投递 1 次
```

## 4. 需要 Ollama 的实验

模型目录：

```text
D:\ollama-models
```

启动：

```powershell
.\scripts\start_ollama_d.ps1
```

检查：

```powershell
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

Tool Calling：

```powershell
.\.venv\Scripts\python.exe experiments\tool_calling_minimal\ollama_tool_calling_demo.py
```

本地模型能力弱时，失败也是实验结果，不能把固定回放标签冒充真实模型指标。

## 5. 需要原 EduRAG 服务的实验

设置：

```powershell
$env:EDURAG_PROJECT_ROOT="D:\agentdev\integrated_qa_system"
$env:EDURAG_LIGHT_EMBEDDING="1"
```

运行：

```powershell
.\.venv\Scripts\python.exe experiments\langgraph_minimal\demo.py `
  "人工智能就业课课程大纲有哪些阶段和模块？" ai
```

依赖：

- MySQL；
- Redis；
- Milvus；
- 原项目配置和知识库集合。

## 6. MCP 只读工具实验

无需外部服务验证 stdio 协议：

```powershell
.\.venv\Scripts\python.exe experiments\mcp_readonly\demo_client.py
```

观察：

```text
protocol_version
transport
tool_names
trace_tools
faq_result
rag_result
security
next_action
```

启动 Streamable HTTP：

```powershell
$env:EDURAG_MCP_DEMO="1"
$env:EDURAG_MCP_TRANSPORT="streamable-http"
$env:PYTHONPATH="$PWD\src"
.\.venv\Scripts\python.exe -m agent_runtime.mcp_server
```

另开终端验证发现：

```powershell
.\.venv\Scripts\python.exe experiments\mcp_readonly\streamable_http_client.py
```

实验必须证明客户端只能发现 `search_faq` 和 `search_rag`，而不是仅证明服务进程
可以启动。

## 7. 实验报告模板

每次实验至少记录：

```text
实验目标
输入场景
配置与版本
trace_tools
answer_source
route_reason
retry_count
time_budget
预期结果
实际结果
偏差与解释
是否允许发布
```

不要只记录“命令成功”。Agent 实验要证明路由、权限、预算和降级语义符合设计。

## 8. CI/验收标准

```text
所有单元测试通过
pip check 通过
安全与跨用户隔离失败数为 0
核心路由回归通过
Deadline 不突破样例上限
Judge 失败不能被平均准确率掩盖
工作区不包含模型、缓存、SQLite 运行数据和密钥
```
