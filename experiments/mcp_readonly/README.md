# EduRAG Read-only MCP

This experiment exposes the existing FAQ and RAG wrappers through the official
MCP Python SDK without moving business logic into the protocol layer.

## Architecture

```text
MCP Client
  -> stdio or Streamable HTTP
  -> EduRAG MCP Server
  -> argument validation and tool allowlist
  -> existing EduRAGTools
      -> MySQL / Redis FAQ
      -> Milvus hybrid retrieval and reranking
```

The first version is intentionally read-only. It exposes:

- `search_faq`
- `search_rag`
- `edurag://capabilities`

## Deterministic client demo

The client launches the server over stdio in demo mode, lists the tools, and
calls both tools without requiring MySQL, Redis, or Milvus:

```powershell
.\.venv\Scripts\python.exe experiments\mcp_readonly\demo_client.py
```

Observe:

- `protocol_version`
- `transport`
- `tool_names`
- `trace_tools`
- `faq_result`
- `rag_result`
- `security`
- `next_action`

## Real stdio server

```powershell
$env:EDURAG_PROJECT_ROOT="D:\agentdev\integrated_qa_system"
$env:PYTHONPATH="$PWD\src"
.\.venv\Scripts\python.exe -m agent_runtime.mcp_server
```

## Streamable HTTP server

```powershell
$env:EDURAG_PROJECT_ROOT="D:\agentdev\integrated_qa_system"
$env:EDURAG_MCP_TRANSPORT="streamable-http"
$env:PYTHONPATH="$PWD\src"
.\.venv\Scripts\python.exe -m agent_runtime.mcp_server
```

The endpoint is `http://127.0.0.1:8020/mcp`.

Verify discovery from a second PowerShell:

```powershell
.\.venv\Scripts\python.exe experiments\mcp_readonly\streamable_http_client.py
```

Observe that `transport=streamable-http` and the tool list contains only
`search_faq` and `search_rag`.

## Safety boundary

- The MCP layer only exposes an explicit allowlist.
- Model-supplied query length, `k`, timeout, and source filter are bounded.
- No ingestion, database mutation, or other side-effect tool is exposed.
- Authentication is still required before remote or multi-user deployment.
