# Phase 2：Tool Calling 改造计划

目标：把 EduRAG 从固定 RAG pipeline 改造成具备工具调用能力的 Agent 原型。

## 1. 为什么下一步做 Tool Calling

当前 EduRAG 流程是代码写死的：

```text
先查 FAQ -> 未命中再查 RAG -> 生成答案
```

Tool Calling 改造后，模型可以根据用户问题选择工具：

```text
用户问题
  -> LLM 判断需要哪个工具
  -> 调用 FAQ / RAG / 评估 / 工单工具
  -> 观察工具结果
  -> 生成最终答案
```

这一步是从“RAG 应用”走向“Agent 应用”的关键。

## 2. 第一批工具设计

先只封装两个工具，不贪多：

### 2.1 `search_faq`

输入：

```json
{
  "query": "用户问题"
}
```

输出：

```json
{
  "hit": true,
  "answer": "FAQ 答案",
  "need_rag": false,
  "source": "faq"
}
```

职责：

- 调用 `BM25Search.search()`。
- 命中时返回 FAQ 答案。
- 未命中时告诉 Agent 需要 RAG。

### 2.2 `search_rag`

输入：

```json
{
  "query": "用户问题",
  "source_filter": "ai"
}
```

输出：

```json
{
  "documents": [
    {
      "content": "召回的父块内容",
      "source": "ai"
    }
  ],
  "source": "rag"
}
```

职责：

- 调用 `VectorStore.hybrid_search_with_rerank()`。
- 返回候选上下文，不直接生成最终答案。

## 3. 最小 Tool Calling Agent 流程

第一版不用一上来接真实大模型工具调用 API，可以先写一个可控 demo：

```text
用户问题
  -> 调用 search_faq
      -> 命中：返回 FAQ 答案
      -> 未命中：调用 search_rag
  -> 把 RAG 文档交给 LLM 生成最终答案
```

这仍然是规则路由，但工具边界已经拆出来了。第二版再让 LLM 自己选择工具。

## 4. 建议新增文件

```text
src/agent_runtime/
  __init__.py
  tools.py
  tool_agent.py
  schemas.py
experiments/tool_calling_minimal/
  README.md
  demo.py
```

## 5. 验收标准

- 能单独调用 `search_faq()`。
- 能单独调用 `search_rag()`。
- `tool_agent.py` 能根据 FAQ 命中与否决定是否调用 RAG。
- 每次工具调用都有结构化日志。
- 文档能讲清楚“固定 pipeline”和“Tool Calling Agent”的区别。

## 5.1 当前第一次运行记录

执行命令：

```powershell
$env:EDURAG_PROJECT_ROOT="D:\BaiduNetdiskDownload\eduRAG项目资料\资料\完整代码\integrated_qa_system"
py experiments\tool_calling_minimal\demo.py "AI学科课程大纲内容是什么？" ai
```

结果：

```json
{
  "answer": null,
  "answer_source": "rag_context",
  "documents": [],
  "trace": [
    {
      "tool": "search_faq",
      "ok": false,
      "data": {
        "hit": false,
        "answer": null,
        "need_rag": true
      },
      "error": "No module named 'pymysql'"
    },
    {
      "tool": "search_rag",
      "ok": false,
      "data": {
        "documents": [],
        "count": 0,
        "source": "rag"
      },
      "error": "No module named 'torch'"
    }
  ]
}
```

结论：

- 工具封装和 trace 结构已经跑通。
- 当前失败原因是运行 demo 的 Python 环境缺少原项目依赖。
- `search_faq` 依赖 `pymysql`。
- `search_rag` 依赖 `torch`、`pymilvus`、`sentence-transformers` 等 AI 依赖。

下一步：

```text
使用原项目已跑通的虚拟环境执行 demo，或在学习仓库中创建 Python 3.10/3.11 虚拟环境并安装原项目 requirements。
```

## 6. 设计问答

问题：为什么 Tool Calling 是 Agent 的关键能力？

回答：

Tool Calling 让模型不只生成文本，而是可以选择并调用外部工具完成任务。普通 RAG 系统通常是固定流程，输入问题后按预设链路检索和生成；Agent 则可以根据目标动态选择工具、观察工具结果、继续推理并生成最终输出。工程上，Tool Calling 需要定义工具 schema、输入校验、权限控制、超时重试、调用日志和错误兜底。
