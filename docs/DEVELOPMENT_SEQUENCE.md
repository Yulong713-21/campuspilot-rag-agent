# CampusPilot 公开开发顺序

本仓库按“先确定性事实，再检索与 Agent，最后产品化和运维”的顺序维护。目录按职责组织，
Git 提交按可验证增量推进，不用 `day-XX` 作为公开分支结构。

## 开发阶段

1. **领域与数据契约**
   - `src/campuspilot_core/`：课程、录取、院校和规划领域模型。
   - `migrations/`、`data/`：数据库迁移与经过整理的版本化公开数据。
2. **知识采集与检索**
   - `src/agent_runtime/handbook_*`、`source_sync.py`：来源归档、解析、切块和检索。
   - `scripts/`：建库、覆盖率、数据质量与检索验证入口。
3. **Agent 编排与可靠性**
   - `src/agent_runtime/graph_agent.py`、`campuspilot_conversation_graph.py`：LangGraph 编排。
   - `tools.py`、`memory_*`、`approval_*`、`evaluation.py`：工具、记忆、审批和评估边界。
4. **模型接入与降级**
   - `ollama_client.py`、`openai_compatible_client.py`：本地和 OpenAI 兼容模型客户端。
   - Deadline、限流、上下文预算和 fallback 保证模型不可用时仍能返回确定性结果。
5. **产品接口与界面**
   - `src/agent_runtime/api.py`：FastAPI 产品接口。
   - `static/`：用户工作台和受保护的本地模型管理页。
   - `java-gateway/`、`integrations/`：可选企业网关与工作流集成。
6. **验证、部署与运维**
   - `tests/`、`eval/`、`experiments/`：单元、回归和可观察实验。
   - `deploy/`、`Dockerfile*`、`.github/workflows/`：部署、容器和持续集成。

## Git 分支框架

```text
main                         # 唯一公开、可部署的稳定主线
├── feature/<scope>          # 一个可测试的产品能力
├── fix/<scope>              # 缺陷修复
├── ops/<scope>              # 部署、配置和运维
└── release/<version>        # 可选发布准备分支

local only（禁止推送）
├── private/*                # 私人资料归档
├── learning/*               # 个人学习过程
└── notes/*                  # 日记、面试、简历与求职准备
```

每个公开提交必须能映射到以上六个阶段之一，并至少通过相关测试。合并顺序保持：

```text
领域/数据 -> 检索 -> Agent -> 模型 -> API/UI -> 验证/部署
```

## 公开边界

- 只提交产品代码、公开来源数据、测试、实验和部署文档。
- 不提交个人学习笔记、面试题、简历、求职准备、mentor 记录、密钥、模型权重或运行日志。
- 产品功能中引用的官方招生面试条件和校园招聘事实属于业务数据，不属于个人资料。
- `python scripts/check_public_repository.py` 会检查 Git 已跟踪路径；GitHub Actions 也执行同一门禁。
