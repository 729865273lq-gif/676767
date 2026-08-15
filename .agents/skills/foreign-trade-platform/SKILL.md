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
- 分工:DSH 负责继续开发与提交;Codex 如需操作本仓库,先确认本会话已结束或改用只读方式

## 流程纪律(硬规则)

- **提交纪律**:每个特性完成并通过验证后立即提交;**每次会话结束时 `git status` 必须干净**;积压未提交改动是最常见的事故源(曾积压两周 40+ 文件)
- **评审分级**:核心后端(知识库/邮箱同步/权限边界)走完整双阶段评审(规格→代码质量);纯 UI 文案/样式改动可只做一次质量评审
- **TDD**:先写失败测试再实现;测试文件同时充当接口契约(中断后可零损耗接续)
- 子代理一律后台运行,避免阻塞对话

## 备份与远程(当前最大风险)

- remote 是 GitHub 公开仓库 `729865273lq-gif/676767`,**历史上有大量提交未推送**(2026-08 曾落后 17+ 提交);github.com 直连可能被重置(GFW),api.github.com 时通时断
- 每次里程碑后推送;推送失败时改用 Gitee 私有仓库或代理;**仓库若含业务逻辑,建议转为私有**
- 数据库备份:`docker exec foreigntrade-postgres-1 pg_dump -U postgres foreign_trade > backups/xxx.sql`,并同步到云盘实现离机备份
- `backups/` 已 gitignore,不会入库

## 已知坑(踩过,别重踩)

- **docker compose 在中文目录名会报 `project name must not be empty`**:必须显式 `-p foreigntrade`(postgres/redis/minio 容器名与数据卷都以此为准)
- **`npm run build` 会清 `.next` 顶掉正在跑的 dev server**:先停 dev 再 build,或 build 完成后重启 `npm run dev`
- **alembic 迁移测试要求从 `backend` 目录启动**;从项目根目录跑会找不到 `../database/alembic`
- **SQLite 测试覆盖不到 pgvector**:向量检索改动后,除单测外必须做一次真实 Postgres 检索冒烟
- **OneDrive 会破坏 `.next`**:`npm run build` 后再跑 dev 可能报 `EINVAL readlink .next\server\vendor-chunks\@swc.js`,页面也可能报 `Cannot find module './NNN.js'`(webpack-runtime 找不到分块)——都是 `.next` 被云同步/构建交叉搞坏,删掉 `frontend\.next` 后重启 `npm run dev` 即可;浏览器端如仍报错,硬刷新(Ctrl+F5)
- PowerShell 传中文给 Python 脚本会变乱码:临时验证脚本里用 Unicode 转义,浏览器/UTF-8 通道不受影响
