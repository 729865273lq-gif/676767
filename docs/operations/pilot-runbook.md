# 外贸销售平台 V1 · 试点运营手册（Runbook）

> 面向使用者的实操手册。目标：让一位非工程背景的运营同学，也能完成邮箱接入、日常跟进闭环、故障排查和备份恢复。
> 本手册只描述操作，不涉及代码修改。所有邮件均为**人工触发**发送，系统绝不自动外发。

---

## 1. 邮箱接入（QQ 邮箱 IMAP/SMTP）

平台通过 IMAP 轮询收件箱，把客户回复拉进「收件箱」面板，并用规则判断意向（有兴趣 / 询价 / 暂缓 / 已拒绝 / 自动回复 / 其他）。

### 1.1 在 QQ 邮箱开启服务并生成授权码

1. 登录 [QQ 邮箱](https://mail.qq.com)，进入「**设置**」→「**账户**」。
2. 找到「**POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV 服务**」区块，点击「**开启服务**」。
3. 至少开启「**IMAP/SMTP 服务**」（收件箱轮询需要 IMAP；后续真实发信需要 SMTP）。
4. 开启时 QQ 会要求短信验证，验证通过后给出一个「**授权码**」（16 位字母组合，形如 `abcdefghijklmnop`）。
   - ⚠️ 授权码**不是** QQ 密码。请复制并妥善保存，它只显示一次（忘记需重新生成）。

### 1.2 在 `.env` 中配置

在项目根目录的 `.env` 中，把邮箱相关变量改成真实值：

```bash
# 收件（IMAP，只读拉取客户回复）
IMAP_HOST=imap.qq.com
IMAP_PORT=993
IMAP_USERNAME=你的邮箱地址@qq.com
IMAP_PASSWORD=上一步生成的授权码
IMAP_SENT_MAILBOX=
INBOX_POLL_SECONDS=120

# 发件（SMTP，仅人工审批后手动/队列发送，绝不自动）
SMTP_HOST=smtp.qq.com
SMTP_PORT=587
SMTP_USERNAME=你的邮箱地址@qq.com
SMTP_PASSWORD=同一个授权码
SMTP_FROM_EMAIL=你的邮箱地址@qq.com
SMTP_FROM_NAME=Trade Axis
SMTP_USE_TLS=true
```

### 1.3 重启后端生效

配置改动需要**重启后端**才生效：

```bash
# 若用 docker-compose 启动
docker compose restart backend

# 若本地直接跑 uvicorn，先停掉再启动（示例）
# Ctrl+C 停止后，重新执行启动命令
```

### 1.4 手动验证

重启后，以管理员身份登录工作台，进入「**收件箱**」面板，点击「**立即同步**」：

- 成功：面板顶部出现「**同步完成，新增 N 封邮件**」。
- 失败：出现后端返回的错误信息（常见原因见第 4 节）。

也可以直接调接口验证（需管理员身份）：

```bash
curl -X POST "http://localhost:8000/organizations/{organization_id}/inbox/sync" \
  -H "Authorization: Bearer <access_token>"
```

> 没有邮件是正常状态：收件箱没有新回复时，面板会显示「暂无邮件回复」的提示，不会报错。

---

## 2. 组织入驻流程（新客户上线）

按顺序完成以下 6 步，新组织即可跑通从搜索到跟进的完整闭环：

| 步骤 | 操作 | 界面位置 |
| --- | --- | --- |
| 1. 注册组织 | 注册账号并创建组织 | 登录页 → 注册入口 |
| 2. 设为管理员 | 首个注册用户默认为管理员（`organization_role = admin`） | 左侧栏底部「租户角色」显示 |
| 3. 邀请成员 | 邀请销售/运营成员加入组织 | 组织管理页（V1 由管理员在后台配置成员） |
| 4. 配置产品线 | 填写产品线名称、关键词、买家画像、目标市场 | 工作台「产品线配置」面板 |
| 5. 配置搜索 API 密钥 | 至少启用一个客户搜索来源并填密钥 | 「API 接口状态」页 → 网站 API 接口列表 |
| 6. 配置 IMAP | 按第 1 节配置邮箱授权码并重启 | `.env` + 收件箱面板「立即同步」验证 |

> 只有第 6 步「IMAP 配置」后，客户回复才会进入收件箱；在此之前系统功能（客户搜索、CRM、开发信草稿）都可正常使用。

---

## 3. 日常操作：从客户发现到跟进闭环

每日核心闭环共 5 步，每步对应界面位置如下：

| 环节 | 操作 | 界面位置 |
| --- | --- | --- |
| ① 客户发现 | 选产品线 + 目标市场 → 启动搜索 → 查看线索评分与证据 | 工作台「客户搜索 Agent」面板 |
| ② 保存 CRM | 勾选合格线索 → 保存到 CRM | 搜索结果的勾选框 +「保存到 CRM」按钮 |
| ③ 开发信（质量门） | 在客户详情页为联系人生成开发信，系统自动做质量检查 | 客户详情抽屉 → 联系人 →「生成开发信」 |
| ④ 人工审批发送 | 逐封查看、修改、**人工审批**；批准后进入「待发送」，再**手动**点发送 | 「邮件审核」面板 / 审核抽屉 |
| ⑤ 收件箱跟进闭环 | 查看客户回复的意向与建议回复 → 复制 → 必要时「标记完成」 | 「收件箱」面板 → 邮件详情抽屉 |

补充说明：

- 第 ④ 步是**安全红线**：批准（approve）只把草稿推进到「待发送（ready_to_send）」状态，**不会**自动发信；真正外发必须再点一次「发送」。
- 第 ⑤ 步里，AI 对每条回复给出「意向 + 置信度 + 分析依据 + 建议回复」，建议回复可直接点「复制」粘贴到邮件中。
- 有跟进任务的回复会显示「待跟进」和「N 天后到期」；处理完点「标记完成」。

---

## 4. 故障恢复

### 4.1 IMAP 授权失败 / 登录失败怎么查

收件箱「立即同步」报错时，先看**后端日志**。日志里搜 `imap`、`IMAP`、`authorization`、`login`：

```bash
# docker-compose 场景
docker compose logs backend --tail=200 | grep -i imap

# 本地日志文件（项目根目录）
# 查看 backend-api.log 或 backend-api-live.log 中近期 imap 相关记录
```

常见根因与处理：

- **授权码错误**：`.env` 里 `IMAP_PASSWORD` 不是 QQ 密码而是授权码；重新生成并重启。
- **授权码过期/失效**：QQ 里重新生成授权码，替换 `.env` 后重启。
- **登录态被 QQ 风控拦截**：用网页版登录一次 QQ 邮箱确认账号正常，必要时换用 SMTP 同款授权码重试。
- **端口/主机不通**：确认 `IMAP_HOST=imap.qq.com`、`IMAP_PORT=993`（SSL）。

后端同步失败会返回 **502**（IMAP 连接失败）或 **503**（`IMAP inbox is not configured`，即 `.env` 未配置），据此可快速定位是「配置缺失」还是「配置错误」。

### 4.2 游标重置（手动全量重扫）

收件箱轮询通过 `mailbox_cursors` 表记录「上次读到哪封」（last_uid）。若出现漏信/需要重新拉取，可重置游标做全量重扫：

```sql
-- 删除指定组织的 INBOX 游标，下次同步会从第 1 封重新扫（幂等，重复邮件不会重复入库）
DELETE FROM mailbox_cursors WHERE organization_id = '<organization_id>' AND mailbox = 'INBOX';
```

删除后回到收件箱点「立即同步」，或等待下一个 `INBOX_POLL_SECONDS` 轮询周期自动重扫。

### 4.3 数据库备份恢复

备份（pg_dump）：

```bash
# 单库导出（推荐每日执行）
pg_dump "postgresql://postgres:postgres@localhost:5432/foreign_trade" \
  --clean --if-exists --format=custom \
  --file="backups/foreign-trade-$(date +%Y%m%d-%H%M).sql"
```

恢复（pg_restore）：

```bash
# 恢复到同一库（会先清理已有对象）
pg_restore --clean --if-exists --no-owner \
  --dbname "postgresql://postgres:postgres@localhost:5432/foreign_trade" \
  "backups/foreign-trade-20260815-1255.sql"
```

> 若 docker-compose 里数据库在容器内，把连接串中的 `localhost` 换成容器服务名（如 `postgres`），或在容器内执行。

### 4.4 `.env` 丢失的恢复

1. 以仓库内的 `.env.example` 为模板，复制为 `.env`。
2. 重新填入：数据库连接、`APP_SECRET`、`CREDENTIAL_ENCRYPTION_KEY`、搜索/客户开发 API 密钥、SMTP/IMAP、Embedding/LLM 等。
3. ⚠️ `APP_SECRET` 与 `CREDENTIAL_ENCRYPTION_KEY` 是**不可随意更换**的敏感值：更换后，已有用户的登录态（JWT）会失效，且用旧密钥加密的凭证无法解密。请优先从备份/密码管理器找回原值。
4. 填好后重启后端并跑一次冒烟验证（登录 → 收件箱「立即同步」）。

---

## 5. 备份策略

- **每日 pg_dump**：建议每日收盘后（或凌晨）执行一次第 4.3 节的自定义格式导出，命名带日期，保留最近 30 份。
- **云盘同步**：项目已有 `backups/` 目录惯例（存放 `foreign-trade-*.sql`）。把该目录同步到云盘（本项目已放于 OneDrive），实现异地备份。
- **定时任务**：可用系统 cron / 任务计划程序每日执行备份脚本，失败时告警。
- **恢复演练**：每月做一次 `pg_restore` 到临时库，确认备份可恢复（备份不演练等于没有备份）。

---

## 6. 支持升级：常见错误码含义

| 错误码 | 场景 | 含义与处理 |
| --- | --- | --- |
| 401 | 任意接口 | 未登录 / 登录态失效。重新登录；若全员掉线，检查 `APP_SECRET` 是否被误改。 |
| 403 | 组织内接口 | 无权限（如普通成员调用「立即同步」）。同步仅管理员可用。 |
| 404 | 详情/详情操作 | 资源不存在（邮件、线索、草稿等 ID 不对或已删除）。 |
| 409 | 开发信审批 | **质量门未通过**：草稿未通过预审（缺少产品证据 / 客户证据 / 发件人信息等）。返回体是问题清单，逐条按 `suggestion` 修正后重新审批。 |
| 409 | 收件箱「标记完成」 | 该邮件没有跟进任务（无 `follow_up_task_id`），无需标记。 |
| 413 | 知识库上传 | 文件超过 25 MB 上限（`file exceeds the 25 MB upload limit`）。压缩/拆分后重传。 |
| 502 | 收件箱同步 | IMAP 连接/登录失败（授权码错误、被风控、网络不通）。见第 4.1 节。 |
| 503 | 收件箱同步 | `IMAP inbox is not configured`：`.env` 未配置 IMAP。按第 1 节配置。 |
| 503 | 知识库检索 | `embedding provider is not configured`：未配置 `EMBEDDING_API_BASE`/`EMBEDDING_API_KEY`/`EMBEDDING_MODEL`。 |

> 通用排查顺序：看 HTTP 状态码 → 看返回体 `detail` → 看后端日志 → 按上表定位。

---

## 7. 安全红线（务必遵守）

1. **邮件绝不自动发送**：系统没有「自动外发」路径。开发信必须经过「生成 → 人工审批 → 手动点发送」；批准只进入待发送箱，不触发外发。任何绕过人工审批的行为都属违规。
2. **授权码只放 `.env`**：IMAP/SMTP 授权码、各类 API 密钥只存放在服务器 `.env` 中，禁止写进代码、提交到 git、发到聊天群或截图外传。
3. **IMAP 轮询只读收件箱**：平台对收件箱只做「读取」，不会删除、移动或标记客户邮件；`IMAP_SENT_MAILBOX` 留空即可。
4. **密钥最小权限**：搜索/客户开发 API 用最小权限密钥，定期轮换。
5. **生产前替换默认值**：`APP_SECRET`、`CREDENTIAL_ENCRYPTION_KEY`、数据库密码等必须替换 `.env.example` 的占位值，否则默认值可被直接利用。
