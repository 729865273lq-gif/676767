---
name: foreign-trade-platform
description: AI 外贸销售平台(AI Foreign Trade Sales Platform)项目专属技能。在该项目目录内工作时,涉及启动服务、运行测试、邮件外发流程、架构约定、延续 superpowers 实施计划时使用。
---

# 外贸平台项目技能

## 项目概况

- 多租户外贸销售工作台:证据驱动的潜客发现 + 人工审批的邮件外发 + CRM 跟进
- 架构:Next.js 15 前端(`frontend/`) + FastAPI 后端(`backend/`) + PostgreSQL(pgvector)/Redis/MinIO/Celery(`docker-compose.yml`)
- 端口:前端 3000,API 8000,健康检查 `/health`
- 模块边界:后端按 platform / workflow / connectors / agents / crm / knowledge / dashboard 划分

## 本地启动

1. 完整运行时:`docker compose up --build`
2. 只起后端:参考 `backend/local_api_launcher.py`(venv 已存在:`backend\.venv`)
3. 前端:`cd frontend; npm.cmd install; npm run dev`

## 测试与质量

- 后端:`cd backend; .\.venv\Scripts\python.exe -m pytest`
- Lint:`cd backend; .\.venv\Scripts\python.exe -m ruff check`
- 前端 e2e:Playwright(`frontend/e2e/`)
- 遵循 superpowers 的 TDD 流程:先写测试再实现

## 红线(不可违反)

- **邮件草稿绝不自动发送**:必须人工审核批准后才通过 SMTP(`.env` 凭据)发送
- 凭据/密钥只在 `.env`,`env` 不入库

## 实施计划与进度

- 完整计划(含任务勾选进度):`docs/superpowers/plans/2026-07-14-ai-foreign-trade-sales-platform-v1.md`
- 相关计划:`docs/superpowers/plans/2026-07-15-product-lines-discovery-entry.md`
- 设计文档:`docs/superpowers/specs/*-design.md`
- 延续开发时先读计划文档,按 superpowers 的 `subagent-driven-development` / `executing-plans` 流程逐任务推进,更新文档中的复选框

## 协作约定(与 Codex 互不打扰)

- 同一个 git 仓库同一时间只用一侧(Codex / DSH)直接改动;需要并行隔离时用 `git worktree`(见 superpowers 的 `using-git-worktrees`)
- 本地服务端口冲突时,谁开发谁启动
