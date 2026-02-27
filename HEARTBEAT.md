# 会话启动与心跳协议

## 会话启动流程（每次新会话）

### Step 1: 执行仪表盘检查

```bash
cd <SKILL_DIR> && python scripts/check_status.py --auto-e2ee
```

### Step 2: 解析状态 → 决定下一步

| 状态条件 | 推荐行动 |
|----------|----------|
| `identity.status == "no_identity"` | 引导创建身份：`setup_identity.py --name "<名称>"` |
| `identity.status == "no_jwt"` | 执行 `setup_identity.py --load default` 刷新 JWT |
| `identity.status == "jwt_refresh_failed"` | 告知用户刷新失败，建议删除凭证重新创建 |
| `inbox.text_messages > 0` | 展示消息摘要，提示用户查看 |
| `inbox.has_pending_handshakes == true` | 告知用户有 E2EE 握手请求（已由 --auto-e2ee 处理） |
| `e2ee_auto.processed > 0` | 汇报自动处理结果 |
| 全部正常 | "DID 身份正常，无未读消息。" |

### Step 3: 汇报摘要（格式）

```
DID 身份状态：[名称] ([DID缩写]) - JWT 有效/已刷新
收件箱：[N] 条未读消息
  - [发送者]: [数量] 条（最近: [时间]）
E2EE：[active] 活跃 / [pending] 握手中
```

如有 E2EE 自动处理：
```
E2EE 自动处理：已自动接受来自 [DID] 的加密通信请求
```

### Step 4: 检查 Profile 完整性

若用户尚未设置 Profile（`get_profile.py` 返回空或缺少昵称/简介），适时建议：
> "建议完善您的 Profile，参考模板：[PROFILE_TEMPLATE.md](references/PROFILE_TEMPLATE.md)"

通过 `update_profile.py` 分步设置：`--nick-name` / `--bio` / `--tags` / `--profile-md`。

## 心跳检查（每 15 分钟）

### 触发条件

距上次 `check_status.py` 执行超过 15 分钟，且用户发来新消息时，在处理用户请求前先执行。

### 状态跟踪

Agent 应在 memory 中维护：
- `last_did_check_at`：上次检查的 ISO 时间戳
- `consecutive_failures`：连续失败次数

### 静默判断规则

仅当以下任一为 true 时通知用户，否则完全静默：
- `inbox.text_messages > 0`
- `e2ee_auto.processed > 0`
- `identity.jwt_refreshed == true`
- `identity.status != "ok"`

### 退避策略

- 成功：failures 归零
- 失败 1-2 次：正常重试
- 失败 >= 3 次：暂停自动心跳，告知用户
- 用户确认后：重置 failures，恢复心跳

## E2EE 自动处理策略

**自动处理（无需确认）：**
- `e2ee_hello` → 自动回复握手
- `e2ee_finished` → 自动激活会话
- `e2ee_error` → 记录错误

**通知用户：**
- "已自动接受来自 [DID] 的加密通信请求"
- "与 [DID] 的 E2EE 通道已建立"

**不自动执行（需用户指示）：**
- 发起握手、发送加密消息、解密消息

**设计依据：** E2EE 协议无拒绝机制，握手消息 5 分钟超时。自动接受避免超时，通知用户保持透明。

## check_status.py 输出字段参考

| 字段路径 | 类型 | 说明 |
|----------|------|------|
| `timestamp` | string | UTC ISO 时间戳 |
| `identity.status` | string | `"ok"` / `"no_identity"` / `"no_jwt"` / `"jwt_refresh_failed"` |
| `identity.did` | string\|null | DID 标识符 |
| `identity.name` | string\|null | 身份名称 |
| `identity.jwt_valid` | bool | JWT 是否有效 |
| `identity.jwt_refreshed` | bool | 本次是否刷新了 JWT（仅刷新时出现） |
| `identity.error` | string | 错误描述（仅 jwt_refresh_failed 时出现） |
| `inbox.status` | string | `"ok"` / `"no_identity"` / `"error"` / `"skipped"` |
| `inbox.total` | int | 收件箱总消息数 |
| `inbox.text_messages` | int | 纯文本未读数（排除 E2EE 协议消息） |
| `inbox.text_by_sender` | object | `{did: {count: int, latest: string}}` |
| `inbox.has_pending_handshakes` | bool | 是否有待处理的 E2EE 握手 |
| `inbox.e2ee_handshake_pending` | list | 发起握手的 DID 列表 |
| `inbox.e2ee_encrypted_from` | list | 发送加密消息的 DID 列表 |
| `inbox.by_type` | object | 按消息类型统计 `{type: count}` |
| `e2ee_auto.status` | string | `"ok"` / `"no_identity"` / `"error"`（仅 --auto-e2ee） |
| `e2ee_auto.processed` | int | 本次自动处理数（仅 --auto-e2ee） |
| `e2ee_auto.details` | list | 处理明细（仅 --auto-e2ee） |
| `e2ee_auto.error` | string | 错误描述（仅 status 为 error 时出现） |
| `e2ee_sessions.active` | int | 活跃 E2EE 会话数 |
| `e2ee_sessions.pending` | int | 握手中的 E2EE 会话数 |
