# Changelog

本项目记录可验证的产品与运行时变化。完整提交历史以 Git 为准。

## Unreleased

- 将仓库展示路径明确拆分为 production、frontend、deployment、experiments 和 optional integrations。
- 将 Java Gateway 移入 `integrations/`，保持可选适配器定位。
- 为版本化数据、manifest、样例与 ignored runtime 数据建立 source-of-truth 契约。

## 2026-08 — Demo-first C6001 Planner

- 将首页从 Chat-first 调整为 C6001 Planner Demo-first vertical slice。
- 拆分前端 ES modules，移除全局 busy 状态，并将官方 Evidence 作为一等结果卡片。
- 增加 Planner 部署烟测以及 `feature -> develop -> main -> container` 发布门禁。
