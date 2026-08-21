# Agent 项目完成指南

这份文档根据当前资料中的任务列表整理而成，目标是指导你从零完成一个可演示、可训练、可测试的 Agent 项目。项目建议聚焦在“面向私有知识或业务任务的智能助手”，并用课程中的大模型微调、LoRA、LLaMA-Factory、模型评估与部署流程逐步落地。

## 1. 项目目标

完成一个具备以下能力的 Agent：

- 能接收用户问题或任务指令。
- 能按照指定格式输出结果，例如摘要、分类、JSON 或业务建议。
- 能结合私有数据或领域数据提升回答质量。
- 能通过提示词、情境学习、思维链或 LoRA 微调逐步优化效果。
- 能提供基本测试、评估和部署说明。

推荐项目方向：

- 文档摘要 Agent：输入长文本，输出结构化摘要。
- 电商评论分析 Agent：输入评论，输出情感标签、风险点、处理建议。
- 课程问答 Agent：基于课程资料回答问题。
- 客服分流 Agent：识别用户意图并输出处理路径。

如果你还没有明确业务场景，建议选择“文档摘要 Agent”，因为它最贴合任务列表中的 Qwen 文本摘要微调案例。

## 2. 推荐目录结构

```text
agent-project/
  README.md
  requirements.txt
  .env.example
  configs/
    train_lora.yaml
    inference.yaml
  data/
    raw/
    processed/
    train.jsonl
    valid.jsonl
    test.jsonl
  src/
    app.py
    agent/
      prompts.py
      workflow.py
      tools.py
    data/
      prepare_data.py
      validate_data.py
    eval/
      evaluate.py
    inference/
      predict.py
  outputs/
    checkpoints/
    logs/
    predictions/
  docs/
    task_checklist.md
    experiment_log.md
    deployment.md
```

最小可交付版本可以先保留 `README.md`、`data/`、`src/`、`configs/`、`outputs/` 五个核心部分。

## 3. 阶段一：确定 Agent 场景

你需要先写清楚四件事：

- 输入是什么：用户问题、长文本、评论、工单、课程问题等。
- 输出是什么：自然语言、标签、JSON、摘要、建议等。
- 判断好坏的标准是什么：准确率、格式正确率、人工评分、F1、召回率等。
- 是否需要微调：如果提示词已经够用，优先不微调；如果格式、领域知识或稳定性不够，再进入 LoRA 微调。

建议在 `README.md` 中补充：

```md
## 项目说明

本项目实现一个文档摘要 Agent。用户输入一段业务文本，Agent 输出结构化摘要，包括核心结论、关键事实、风险提醒和下一步建议。

## 输入格式

纯文本或 Markdown 文档。

## 输出格式

JSON：
{
  "summary": "",
  "key_points": [],
  "risks": [],
  "next_actions": []
}
```

验收标准：

- 至少定义 1 个明确业务场景。
- 至少定义 1 种固定输出格式。
- 至少准备 10 条人工测试样例。

## 4. 阶段二：准备环境

课程任务列表中的环境要求包括 Python、PyTorch、CUDA、Hugging Face、Transformers、Datasets 和 LLaMA-Factory。

本地开发建议：

```bash
python -m venv .venv
.venv\Scripts\activate
pip install torch transformers datasets accelerate peft sentencepiece
pip install fastapi uvicorn python-dotenv pydantic
```

如果要使用 LLaMA-Factory：

```bash
git clone https://github.com/hiyouga/LLaMA-Factory.git
cd LLaMA-Factory
pip install -e ".[torch,metrics]"
```

GPU 云服务器建议使用：

- CUDA 可用的环境。
- 至少能运行 7B 级别模型的显存配置。
- 显存不足时优先选择 LoRA、QLoRA 或 INT4 量化模型。

验收标准：

- `python --version` 能正常输出。
- `python -c "import torch; print(torch.cuda.is_available())"` 能检测 GPU；没有 GPU 时也要记录为 CPU 调试模式。
- 能成功导入 `transformers`、`datasets`、`peft`。

## 5. 阶段三：准备数据

任务列表强调“样本、特征、标签、训练集、验证集、测试集”。对于 Agent 项目，建议把数据整理成指令微调格式。

推荐 JSONL 格式：

```json
{"instruction":"请总结下面的文本，并输出 JSON。","input":"这里是原始文本。","output":"{\"summary\":\"...\",\"key_points\":[\"...\"],\"risks\":[],\"next_actions\":[\"...\"]}"}
```

数据处理步骤：

1. 收集原始文本，放入 `data/raw/`。
2. 清洗无效字符、重复文本和过短文本。
3. 人工编写高质量答案，形成 `instruction/input/output`。
4. 划分数据集：训练集 80%，验证集 10%，测试集 10%。
5. 保存为 `data/train.jsonl`、`data/valid.jsonl`、`data/test.jsonl`。

数据质量要求：

- 输出格式必须稳定。
- 每条样本只训练一个清晰任务。
- 不要把测试集样本混入训练集。
- 先追求 100 条高质量样本，再考虑扩充到 1000 条以上。

验收标准：

- 至少有 30 条可运行样本。
- 每条样本包含 `instruction`、`input`、`output`。
- 能用脚本检查 JSONL 每一行都可解析。

## 6. 阶段四：先用提示词实现 Agent

任务列表中提到“无需调整模型参数优先考虑”“情境学习”“思维链”。因此项目第一版不要直接微调，先做 Prompt Agent。

建议实现 `src/agent/prompts.py`：

```python
SYSTEM_PROMPT = """
你是一个严谨的文档摘要 Agent。
你必须只输出 JSON，不要输出解释性文字。
字段包括 summary、key_points、risks、next_actions。
"""

USER_TEMPLATE = """
请处理下面的文本：

{text}
"""
```

Agent 工作流：

1. 接收用户输入。
2. 拼接 system prompt 和 user prompt。
3. 调用模型接口或本地模型。
4. 校验输出是否为合法 JSON。
5. 如果格式错误，自动要求模型修复一次。
6. 返回最终结果。

验收标准：

- 能处理 10 条测试样例。
- JSON 格式正确率达到 80% 以上。
- 对失败案例有记录。

## 7. 阶段五：判断是否需要微调

满足以下情况时再进入 LoRA 微调：

- 模型经常不按格式输出。
- 模型不理解你的领域术语。
- 相同输入多次输出不稳定。
- 少样本提示词无法覆盖目标任务。
- 需要在固定业务风格下生成答案。

如果只是缺少私有知识，优先考虑知识库检索；如果是输出风格、格式和任务行为不稳定，再考虑微调。

决策表：

| 问题 | 优先方案 |
| --- | --- |
| 缺少最新资料 | RAG/知识库 |
| 输出格式不稳定 | Prompt 约束 + JSON 校验 |
| 业务风格不统一 | 少样本提示词 |
| 领域任务长期稳定 | LoRA 微调 |
| 推理成本太高 | 量化或小模型 |

## 8. 阶段六：使用 LoRA 微调

任务列表中 AR 模型微调重点是 PEFT 和 LoRA。推荐使用 LLaMA-Factory 完成训练。

训练前准备：

- 选择基座模型，例如 Qwen 系列小参数模型。
- 准备 `data/train.jsonl` 和 `data/valid.jsonl`。
- 配置训练 yaml。
- 明确训练目标：不是让模型记住知识，而是让模型学会任务格式和回答风格。

示例 `configs/train_lora.yaml`：

```yaml
stage: sft
do_train: true
finetuning_type: lora
lora_target: all
dataset: agent_summary
template: qwen
cutoff_len: 2048
learning_rate: 2.0e-4
num_train_epochs: 3
per_device_train_batch_size: 1
gradient_accumulation_steps: 8
logging_steps: 10
save_steps: 100
output_dir: outputs/checkpoints/agent-summary-lora
```

训练命令示例：

```bash
llamafactory-cli train configs/train_lora.yaml
```

训练完成后需要做：

- 保存 adapter 权重。
- 导出或合并模型。
- 用测试集预测。
- 对比微调前后的格式正确率和任务效果。

验收标准：

- 训练过程没有报错。
- `outputs/checkpoints/` 下生成权重文件。
- 微调后至少在 20 条测试样例上有结果。
- 记录训练参数、数据量、显存占用、训练时间和效果变化。

## 9. 阶段七：评估与测试

课程任务列表中提到准确率、精确率、召回率、F1。生成式 Agent 可以额外评估格式和人工质量。

建议评估指标：

- JSON 格式正确率。
- 必填字段完整率。
- 摘要是否覆盖关键信息。
- 是否产生幻觉。
- 输出是否符合业务语气。
- 人工评分，1 到 5 分。

建议在 `src/eval/evaluate.py` 中输出：

```text
total: 100
json_valid_rate: 0.94
required_fields_rate: 0.91
avg_human_score: 4.2
```

测试清单：

- 正常长文本。
- 极短文本。
- 空输入。
- 包含无关内容的文本。
- 包含敏感或不确定信息的文本。
- 超过模型上下文长度的文本。

验收标准：

- 至少完成 20 条测试样例评估。
- 有微调前后对比。
- 有失败案例分析和下一轮优化计划。

## 10. 阶段八：部署最小 Demo

最小部署可以使用 FastAPI。

建议接口：

```text
POST /agent/summarize
GET /health
```

请求示例：

```json
{
  "text": "需要处理的文本"
}
```

响应示例：

```json
{
  "summary": "...",
  "key_points": ["..."],
  "risks": [],
  "next_actions": ["..."]
}
```

启动命令：

```bash
uvicorn src.app:app --host 0.0.0.0 --port 8000
```

验收标准：

- `/health` 返回正常。
- `/agent/summarize` 能返回结构化结果。
- README 中写明启动方式。
- 至少保留 3 个 curl 或 Python 调用示例。

## 11. 最终交付物清单

完成项目时至少提交：

- `README.md`：项目说明、安装、运行、测试、效果。
- `data/`：示例数据和数据格式说明。
- `src/`：Agent 主流程、推理、评估脚本。
- `configs/`：训练配置和推理配置。
- `outputs/predictions/`：测试集预测结果。
- `docs/experiment_log.md`：实验记录。
- `docs/deployment.md`：部署说明。

最终演示建议包含：

1. 展示输入文本。
2. 展示 Prompt 版本输出。
3. 展示 LoRA 微调后输出。
4. 展示评估指标对比。
5. 展示 API 调用结果。

## 12. 推荐完成顺序

- 第 1 天：确定场景、输出格式、目录结构。
- 第 2 天：准备 30 到 100 条样本数据。
- 第 3 天：完成 Prompt Agent 和 JSON 校验。
- 第 4 天：完成测试集和评估脚本。
- 第 5 天：接入 LLaMA-Factory，跑通 LoRA 小规模训练。
- 第 6 天：微调模型预测、对比效果、整理失败案例。
- 第 7 天：完成 FastAPI Demo、README 和最终汇报材料。

## 13. 常见问题

### 什么时候不用微调？

如果提示词加少量示例已经能稳定完成任务，就先不用微调。微调会增加数据准备、训练、部署和维护成本。

### 数据少能不能微调？

可以，但要谨慎。少量高质量数据更适合让模型学习输出格式和风格，不适合注入大量事实知识。

### 显存不够怎么办？

优先使用更小的基座模型、LoRA/QLoRA、INT4 量化、减小 batch size、增加梯度累积。

### Agent 和微调是什么关系？

Agent 是完整应用流程，包含提示词、工具调用、记忆、校验、接口和业务逻辑。微调只是其中一种优化模型行为的方法。

## 14. 当前项目下一步

建议你现在先做三件事：

1. 新建 `agent-project/` 项目目录。
2. 选择一个明确场景，推荐“文档摘要 Agent”。
3. 准备第一批 30 条 `instruction/input/output` 样本。

完成这三步后，再进入 Prompt Agent 编码和 LoRA 微调。
