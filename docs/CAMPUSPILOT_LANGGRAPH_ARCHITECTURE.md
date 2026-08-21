# CampusPilot LangGraph 架构

## Handbook RAG 子图（当前已实现）

```mermaid
flowchart TD
    A["prepare_query"] --> B["search_handbook"]
    B --> C["assess_retrieval"]
    C -->|中等且可改写| D["rewrite_query"]
    D --> E["search_rewritten"]
    C -->|高或低| F["prepare_evidence"]
    E --> F
    F -->|无可靠证据| G["controlled_no_answer"]
    F -->|无模型客户端| H["extractive_fallback"]
    F -->|有模型客户端| I["generate_grounded_answer"]
    I --> J["validate_grounding"]
    J -->|引用有效| K["finalize_llm_answer"]
    J -->|生成失败或引用无效| H
```

这个子图只允许一次查询改写。第二次检索质量不低于第一次才采用，否则保留原查询和原证据。
模型生成后必须包含有效的 `[1]`、`[2]` 证据编号；校验失败时不展示未经约束的模型答案。

## 当前可运行主图

```mermaid
flowchart TD
    UI["Vue 对话页<br/>sessionStorage 保存 thread_id"] --> JAVA["Java Campus API<br/>透传用户与项目上下文"]
    JAVA --> API["FastAPI /api/agent/chat"]
    API --> CP[("SQLite Checkpointer<br/>按 thread_id 保存状态")]
    CP --> N["normalize_request<br/>默认值 + 线程背景 + 本轮输入"]
    N --> U["understand_current_turn<br/>识别当前意图"]
    U --> R{"conversation_route"}
    R -->|structured| S["结构化业务工具"]
    R -->|grounded_qa| G["有据问答"]
    R -->|capabilities| C["能力说明"]
    R -->|ambiguous| A["模糊请求解释/澄清"]
    S --> O["统一回答 + trace + thread_state"]
    G --> O
    C --> O
    A --> O
    O --> CP
    O --> JAVA
    JAVA --> UI
```

`normalize_request` 的合并顺序是：

```text
产品默认值 < Checkpoint 中已确认的规划背景 < 当前请求
```

当前轮出现明确意图时绝不使用旧意图。只有上一轮正在等待补充字段，或本轮是“那……呢”“再均衡一点”“继续”等短追问时，才允许继承 `last_intent`。这条限制用于防止旧话题污染新问题。

## 结构化规划子图

```mermaid
flowchart LR
    S["study_plan"] --> L["load_program_rules"]
    L --> P["calculate_credit_progress"]
    P --> D["generate_study_plan"]
    D --> V["validate_study_plan"]
    V --> J{"所有候选方案有效？"}
    J -->|是| N["生成面向用户的说明"]
    J -->|否| F["调整约束或受控失败"]
```

课程位置、学分、先修、开课学期和 Capstone 顺序由确定性规则计算。LLM 可以解释方案，但不能移动课程或篡改校验结果。

## 有据问答分支

```mermaid
flowchart LR
    Q["handbook_qa / recruitment_qa"] --> F{"FAQ 高精度命中？"}
    F -->|是| FA["FAQ 直接回答"]
    F -->|否| H["混合检索知识库"]
    H --> E{"证据质量"}
    E -->|高/中| L["LLM 基于证据自然语言生成"]
    E -->|低| P["标注不完整的相关片段"]
    L --> C["引用与有据性检查"]
    P --> C
```

该图表达业务流程；其中 FAQ、检索、生成和校验当前封装在专业 Agent 内，并非全部拆成外层图节点。后续只有在需要独立重试、超时、并行或观测时，才继续拆节点。

## 线程状态边界

Checkpoint 当前只长期保存本线程继续执行所需的数据：

- `planning_context`：项目版本、Handbook Year、方向、已修课、学期容量等；
- `last_intent` 和 `last_course_code`：供受限追问继承；
- `pending_fields`：上一轮还在等待哪些字段；
- `turn_count`：便于联调观察；
- 图执行状态：由 LangGraph Checkpointer 管理。

不同 `thread_id` 完全隔离。当前浏览器使用 `sessionStorage` 保存线程号；生产环境还必须由 Java 服务校验 `thread_id` 的用户归属，不能只相信客户端传值。
