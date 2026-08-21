# CampusPilot MySQL 表结构

## 1. 技术约定

- MySQL 8，字符集 `utf8mb4`；
- SQLAlchemy 2.0 typed declarative；
- Alembic 管理结构版本；
- 枚举使用字符串列加 `CHECK`，便于 SQLite 测试与 MySQL 迁移保持一致；
- JSON 字段保存来源快照标识和规则证据，不承担可查询的核心业务关系。

初始化迁移：

`migrations/versions/49badc8f2e42_initial_campuspilot_domain_schema.py`

## 2. 表清单

| 表 | 主要字段 | 作用 |
|---|---|---|
| `universities` | `code`, `name`, `country_code` | 学校 |
| `programs` | `university_id`, `code`, `award_type` | 稳定项目身份 |
| `program_versions` | `program_id`, `handbook_year`, `total_credits` | 年份化培养方案 |
| `admission_criteria` | `program_version_id`, `pathway_code`, `duration_months`, `minimum_average_percent` | 版本化录取路径与学制 |
| `program_catalog_profiles` | `program_version_id`, `discipline_id`, `available_intakes`, `release_stage` | 项目发现与发布状态 |
| `admission_rules` | `criterion_id`, `applicant_condition`, `minimum_value`, `scale_max` | 条件化硬规则 |
| `alternative_admission_pathways` | `program_version_id`, `pathway_type`, `tuition_amount` | 官方补偿或桥梁路径 |
| `admission_evidence` | `source_type`, `source_url`, `verified_at`, `hard_decision_allowed` | 规则证据与审核门禁 |
| `specialisations` | `program_version_id`, `code`, `required_credits` | 版本内方向 |
| `courses` | `university_id`, `code`, `canonical_name` | 稳定课程身份 |
| `course_versions` | `course_id`, `handbook_year`, `credit_points` | 年份化课程数据 |
| `requirement_groups` | `program_version_id`, `specialisation_id`, `min_credits`, `max_credits` | 学分要求组 |
| `requirement_group_courses` | `requirement_group_id`, `course_version_id`, `role` | 课程在方案中的角色 |
| `prerequisite_groups` | `course_id`, `group_index`, `minimum_satisfied` | 先修逻辑组 |
| `prerequisite_options` | `prerequisite_group_id`, `prerequisite_course_id` | 组内候选课 |
| `course_exclusions` | `course_id`, `excluded_course_id` | 互斥课程对 |
| `student_profiles` | `program_version_id`, `specialisation_id` | 学生培养方案作用域 |
| `student_course_records` | `student_id`, `course_id`, `status`, `attempt_number` | 修读历史 |
| `study_plans` | `student_id`, `status`, `objective` | 学习方案 |
| `study_plan_terms` | `study_plan_id`, `term_code`, `sequence_number` | 计划学期 |
| `study_plan_courses` | `study_plan_term_id`, `course_id` | 学期计划课 |

## 3. 关键约束

- 学校内项目代码唯一：`programs(university_id, code)`。
- 学校内课程代码唯一：`courses(university_id, code)`。
- 项目年份唯一：`program_versions(program_id, handbook_year)`。
- 同一项目版本内录取路径唯一：`admission_criteria(program_version_id, pathway_code)`。
- 同一录取路径内规则代码唯一：`admission_rules(criterion_id, rule_code)`。
- 同一项目版本只有一条目录展示档案。
- 同一项目版本内替代路径代码唯一。
- 课程年份唯一：`course_versions(course_id, handbook_year)`。
- 方向只属于一个版本：`specialisations(program_version_id, code)`。
- 同一要求组不能重复关联同一课程版本。
- 先修组内不能重复候选课。
- 互斥规则不能引用课程自身。
- 学生同一课程允许多次尝试，但 `attempt_number` 唯一。
- 同一方案内学期编号、学期代码唯一。
- 同一学期不能重复安排同一课程。

项目级 `requirement_groups.specialisation_id` 为 `NULL`。由于 MySQL 唯一索引允许多行
`NULL`，导入服务还必须执行“同一版本的项目级 group code 唯一”校验；不能只依赖数据库。

## 4. 为什么不用一张课程规则大表

把课程、方向、先修和学生状态塞进一张表会导致：

- 每个年份复制课程基础信息；
- 同一课程多角色难以表达；
- 方向和项目规则互相覆盖；
- 更新 Handbook 时无法保留旧学生规则；
- 证据粒度太粗，错误无法指出具体规则。

当前模型把稳定身份、年份快照、课程角色和学生事实分开，代价是表更多，但规则边界清楚，
也更适合自动化回归。

## 5. 迁移命令

```powershell
$env:CAMPUSPILOT_DATABASE_URL="mysql+pymysql://campuspilot:密码@127.0.0.1:3306/campuspilot?charset=utf8mb4"
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe current
```

只生成 MySQL DDL，不连接数据库：

```powershell
.\.venv\Scripts\alembic.exe upgrade head --sql
```

迁移已同时通过 SQLite 实际升级/回滚和 MySQL 离线 DDL 编译验证。
