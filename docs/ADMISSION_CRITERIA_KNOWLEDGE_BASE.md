# CampusPilot 录取标准数据底座

## 1. 当前范围

第一批数据来自 Monash University 2026 官方 Handbook：

- 39 个硕士项目；
- 67 条录取路径；
- 商科、计算机、工程、数学与科学相关项目；
- 39 份面向 RAG 的专用录取文档；
- Milvus 集合 `campuspilot_admissions_v1`，共 159 个子块。

官方来源示例：

- <https://handbook.monash.edu/2026/courses/C6001>
- <https://handbook.monash.edu/2026/courses/B6022>
- <https://handbook.monash.edu/2026/courses/E6011>
- <https://handbook.monash.edu/2026/courses/S6003>

## 2. 为什么同时使用 SQL 和向量库

SQL 保存可计算的硬条件，例如项目年份、标准学制、学分、最低均分、相关专业背景、
工作经验和补充材料。后续申请匹配先由确定性代码比较这些字段。

向量库保存官方原文和解释性条件，用于回答“为什么”“还有什么替代路径”等问题。
Agent 不能从向量相似度直接推出录取结论，也不能让 LLM 自己发明 GPA 门槛。

## 3. 数据流

```text
官方 Handbook 快照
  -> 定位 Minimum entry requirements
  -> 按录取路径拆分
  -> AdmissionCriterion 入库
  -> 生成中文检索文档
  -> 父子块切分
  -> BM25 + dense 混合检索
```

## 4. 用户语言

前端不展示 `Entry Level 1/2/3`，而展示：

- `1年制项目（48学分）`；
- `1.5年制项目（72学分）`；
- `2年制项目（96学分）`。

开学批次统一显示为 `2026S1`、`2026S2`。当前 Handbook 录取页没有可靠给出全部
intake，因此数据库中的 `available_intakes` 暂为空；后续必须从官方 Course Finder
单独采集，不能默认所有项目都有 S1 和 S2。

## 5. 运行与验证

```powershell
.\.venv\Scripts\python.exe scripts\extract_admission_criteria.py
.\.venv\Scripts\python.exe scripts\build_admission_vector_index.py
.\.venv\Scripts\python.exe -m unittest tests.test_admission_criteria -v
```

## 6. 风险边界

- 达到最低分不等于保证录取；
- 海外成绩换算不能只做线性百分比转换；
- 相关专业背景需要课程级证据，不能只看本科专业名称；
- 实习、GMAT/GRE 只有在官方路径明确允许时才能作为补充条件；
- 学分减免与最终学制以学校正式评估为准。
