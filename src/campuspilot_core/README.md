# CampusPilot 确定性领域核心

该目录实现课程培养方案的结构化建模与规则校验，不调用 LLM，也不依赖前端。
LLM/RAG 后续只能负责理解问题、检索原文和解释结果，不能代替这里的学分计算。

## 能力

- 按 `ProgramVersion + Specialisation` 读取培养要求；
- 判断同一课程在不同培养方案中的角色；
- 校验 AND/OR/N-of-M 先修关系；
- 计算已获、在修和计划学分；
- 校验总学分、必修、选修组上下限、互斥和重复计入；
- 按学期顺序校验学习方案。

所有规则结论统一返回：

```json
{
  "passed": false,
  "error_code": "PREREQUISITE_NOT_MET",
  "message": "可读说明",
  "evidence": []
}
```

## 安装

```powershell
cd D:\agentdev\edurag-agent-lab
.\.venv\Scripts\python.exe -m pip install -r requirements-persistence.txt
```

## 轻量 SQLite 演示

```powershell
$env:CAMPUSPILOT_DATABASE_URL="sqlite:///logs/campuspilot_domain.sqlite3"
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe scripts\seed_campuspilot_domain.py
.\.venv\Scripts\python.exe experiments\campuspilot\domain_rule_core_demo.py
```

种子数据是明确标记的 `synthetic_test`，仅用于验证规则，不代表任何澳洲高校的官方培养方案。

## MySQL 迁移

先创建空数据库和账号，再设置连接串：

```sql
CREATE DATABASE campuspilot
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;
```

```powershell
$env:CAMPUSPILOT_DATABASE_URL="mysql+pymysql://campuspilot:你的密码@127.0.0.1:3306/campuspilot?charset=utf8mb4"
.\.venv\Scripts\alembic.exe upgrade head
```

查看版本和回滚：

```powershell
.\.venv\Scripts\alembic.exe current
.\.venv\Scripts\alembic.exe downgrade base
```

## 测试

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_campuspilot_domain_core -v
```

领域核心本身没有 Web 服务需要“启动”。后续 FastAPI、LangGraph 或 Dify 通过
`DegreeAuditService` 调用同一套确定性接口即可。
