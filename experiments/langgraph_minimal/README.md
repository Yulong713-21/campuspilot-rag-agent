# Minimal LangGraph EduRAG Agent

## CampusPilot Handbook RAG Graph

运行：

```powershell
.\.venv\Scripts\python.exe experiments\langgraph_minimal\handbook_rag_graph_demo.py
```

实验比较三条路径：查询改写提升召回、查询改写降低召回、模型答案缺少引用。
重点观察 `effective_query`、`rewritten_result_selected`、`trace_tools` 和
`answer_source`。Graph 不会因为“已经执行过改写”就盲目采用新结果；新召回质量更差时
保留原证据，模型答案无法通过引用校验时回退到可核对的证据摘录。

## CampusPilot 线程 Checkpoint

`campuspilot_thread_checkpoint_demo.py` 会关闭并重新打开 SQLite 连接，模拟服务重启，验证同一 `thread_id` 能恢复项目背景、上一意图和轮次，同时生成三套学习方案。

This experiment turns the previous deterministic tool agent into a LangGraph
state graph.

It still uses the same tools:

- `search_faq`
- `search_rag`

The difference is orchestration:

```text
START
  -> search_faq
  -> faq_hit ? finalize_faq : search_rag
  -> generate_answer
  -> evaluate_answer
  -> supported ? END : rewrite_query or handle_unsupported
  -> END
```

## Why This Matters

The old `RuleBasedToolAgent` used normal Python `if/else`.

LangGraph gives us a more explicit Agent runtime:

- a shared state object
- named nodes
- conditional edges
- traceable execution
- a dedicated answer generation node
- a lightweight answer evaluation node
- room for memory, retries, evaluation, and multi-agent branches later

The demo output includes:

- `answer`: final answer text
- `answer_source`: `faq`, `rag_generated`, or `no_answer`
- `confidence`: `high`, `medium`, or `low`
- `evaluation`: support check result
- `retry_count`: how many times the graph rewrote and retried
- `effective_query`: the query actually used by RAG
- `trace`: tools called during execution

## Branching Experiment

Run these three scenarios and compare `trace_tools`, `answer_source`,
`confidence`, and `next_action`.

FAQ hit:

```powershell
.\.venv\Scripts\python.exe experiments\langgraph_minimal\branching_demo.py faq_hit
```

Expected:

```text
trace_tools: ["search_faq"]
answer_source: faq
confidence: high
next_action: answer_user
```

RAG supported:

```powershell
.\.venv\Scripts\python.exe experiments\langgraph_minimal\branching_demo.py rag_supported
```

Expected:

```text
trace_tools: ["search_faq", "search_rag"]
answer_source: rag_generated
confidence: medium
next_action: answer_user
```

RAG empty:

```powershell
.\.venv\Scripts\python.exe experiments\langgraph_minimal\branching_demo.py rag_empty
```

Expected:

```text
trace_tools: ["search_faq", "search_rag"]
answer_source: fallback
confidence: low
next_action: ask_clarification_or_create_ticket
```

Rewrite succeeds:

```powershell
.\.venv\Scripts\python.exe experiments\langgraph_minimal\branching_demo.py rewrite_success
```

Expected:

```text
trace_tools: ["search_faq", "search_rag", "rewrite_query", "search_rag"]
answer_source: rag_generated
retry_count: 1
next_action: answer_user
```

## Run

From `D:\agentdev\edurag-agent-lab`:

```powershell
$env:EDURAG_PROJECT_ROOT="D:\agentdev\integrated_qa_system"
$env:EDURAG_LIGHT_EMBEDDING="1"
.\.venv\Scripts\python.exe experiments\langgraph_minimal\demo.py "AI学科课程大纲内容是什么？" ai
```

## Run With Ollama

Start Ollama with the model directory:

```powershell
$env:OLLAMA_MODELS="C:\Users\23524\Downloads\ollama-models"
```

Enable local LLM generation:

```powershell
$env:EDURAG_PROJECT_ROOT="D:\agentdev\integrated_qa_system"
$env:EDURAG_LIGHT_EMBEDDING="1"
$env:EDURAG_USE_OLLAMA="1"
$env:EDURAG_OLLAMA_MODEL="qwen3:1.7b"
.\.venv\Scripts\python.exe experiments\langgraph_minimal\demo.py "人工智能就业课课程大纲有哪些阶段和模块？" ai
```

Expected:

```text
answer_source: rag_llm
confidence: medium
evaluation.supported: true
```

If the machine reports an Ollama out-of-memory error, lower `num_ctx`. The code
currently uses `num_ctx=2048` for `qwen3:1.7b`.

## Human Approval Interrupt

Run the pause/resume experiment:

```powershell
.\.venv\Scripts\python.exe experiments\langgraph_minimal\approval_interrupt_demo.py
```

Observe:

```text
paused.execution_count = 0
paused.next_nodes = ["review_action"]
approved.status = executed
approved.execution_count = 1
rejected.status = rejected
rejected.execution_count = 0
```

The experiment uses `MemorySaver`, which is suitable only for local learning.
A production service needs a durable checkpointer so another request or process
can resume the same `thread_id`.

## Short-Term State vs Long-Term Memory

```powershell
.\.venv\Scripts\python.exe experiments\langgraph_minimal\memory_scope_demo.py
```

The experiment compares:

- two messages in the same thread
- a new thread for the same user
- a new thread for another user

The same thread retains its message state. A new thread starts with empty
history, while the same user's explicit answer-style preference is loaded from
the Store. Another user cannot read that preference.

## Long-Term Memory Write Policy

```powershell
.\.venv\Scripts\python.exe experiments\langgraph_minimal\memory_write_policy_demo.py
```

Compare a one-turn instruction, an explicit future preference, a preference
claimed by a RAG document, and a model inference. The policy decides whether to
persist, keep only in thread state, request confirmation, or reject.

## Memory Preference Precedence

```powershell
.\.venv\Scripts\python.exe experiments\langgraph_minimal\memory_precedence_demo.py
```

The experiment shows that a current-turn request overrides a long-term
preference without rewriting it. On the next turn, the long-term preference is
used again. System safety and permission constraints are evaluated before this
preference resolver and cannot be overridden.

## Long-Term Memory Retrieval

```powershell
.\.venv\Scripts\python.exe experiments\langgraph_minimal\memory_retrieval_demo.py
```

### Memory consolidation and conflict demo

```powershell
.\.venv\Scripts\python.exe experiments\langgraph_minimal\memory_consolidation_demo.py
```

Observe that an explicit user update supersedes the old version while preserving
history. A conflicting model inference cannot replace the active user fact.

### Agent state boundary demo

```powershell
.\.venv\Scripts\python.exe experiments\langgraph_minimal\state_boundaries_demo.py
```

Compare FAQ hit, supported RAG, and empty RAG scenarios. Each execution is
projected separately into checkpoint, prompt, trace, and long-term memory planes.

### Safe context pipeline demo

```powershell
.\.venv\Scripts\python.exe experiments\langgraph_minimal\safe_context_pipeline_demo.py
```

Compare a normal document, a high-scoring injection document, and documents
that exceed the available context budget.

### Memory and RAG shared-budget demo

```powershell
.\.venv\Scripts\python.exe experiments\langgraph_minimal\memory_context_budget_demo.py
```

The experiment gives Memory at most 20% of a 100-token budget and shows when
unused or blocking Memory budget is returned to factual RAG evidence.

### Evidence-first residual repacking demo

```powershell
.\.venv\Scripts\python.exe experiments\langgraph_minimal\evidence_first_repacking_demo.py
```

Compare the old `RAG A only` result with the improved `RAG A + Memory M2`
combination under the same 200-token budget.

### Unified LangGraph Deadline demo

```powershell
.\.venv\Scripts\python.exe experiments\langgraph_minimal\langgraph_deadline_demo.py
```

Compare sufficient budget, final-generation timeout, and RAG timeout while
observing the timeout propagated to each downstream call.

### Agent regression evaluation demo

```powershell
.\.venv\Scripts\python.exe experiments\langgraph_minimal\agent_regression_eval_demo.py
```

Run six full graph scenarios and compare the clean baseline with a simulated
Prompt Injection leakage regression that must fail the safety release gate.

### Agent harness lifecycle demo

```powershell
.\.venv\Scripts\python.exe experiments\langgraph_minimal\agent_harness_lifecycle_demo.py
```

Compare a healthy baseline, an Agent product regression, and a broken test
fixture. Observe that `harness_healthy` describes whether cases executed, while
the evaluation report describes whether successfully executed Agent behavior
met the product contract.

The retriever first filters expired, untrusted, sensitive, and irrelevant
memories. It then combines relevance, importance, confidence, and recency
before packing the selected memories into a dedicated Token budget.

### Structured intent graph demo

```powershell
.\.venv\Scripts\python.exe experiments\langgraph_minimal\structured_intent_graph_demo.py
```

观察高置信模型意图、低置信回退和模型超时三个场景。重点查看模型调用次数、
`intent_candidate`、`source`、`validation_error` 与最终 `route`。
