# WebSocket 监听器 — macOS launchd 部署指南

## 概述

WebSocket 监听器是一个常驻后台进程，持续接收 molt-message WebSocket 推送消息，
根据路由规则分类后转发到本地 webhook 端点（agent / wake 双模式）。

## 文件说明

| 文件 | 说明 |
|------|------|
| `listener.example.json` | 路由规则配置示例，复制后按需修改 |
| `com.awiki.ws-listener.plist` | macOS LaunchAgent 配置模板 |

## 安装步骤

### 1. 准备配置文件

```bash
# 复制并编辑配置
cp launchd/listener.example.json launchd/listener.json
# 编辑 listener.json，设置 webhook_token、whitelist_dids 等
```

### 2. 修改 plist 文件

编辑 `com.awiki.ws-listener.plist`，确认以下路径正确：
- Python 解释器路径（建议使用 venv）
- `ws_listener.py` 脚本路径
- `--config` 指向的配置文件路径

### 3. 安装 LaunchAgent

```bash
# 复制 plist 到 LaunchAgents 目录
cp launchd/com.awiki.ws-listener.plist ~/Library/LaunchAgents/

# 加载服务（立即启动）
launchctl load ~/Library/LaunchAgents/com.awiki.ws-listener.plist
```

### 4. 验证运行

```bash
# 检查服务状态
launchctl list | grep awiki

# 查看日志
tail -f /tmp/awiki-ws-listener.stdout.log
tail -f /tmp/awiki-ws-listener.stderr.log
```

## 常用操作

### 停止服务

```bash
launchctl unload ~/Library/LaunchAgents/com.awiki.ws-listener.plist
```

### 重新加载（配置变更后）

```bash
launchctl unload ~/Library/LaunchAgents/com.awiki.ws-listener.plist
launchctl load ~/Library/LaunchAgents/com.awiki.ws-listener.plist
```

### 前台调试运行

```bash
# 不通过 launchd，直接前台运行（Ctrl+C 停止）
python scripts/ws_listener.py \
    --credential default \
    --config launchd/listener.json \
    --verbose
```

### 卸载

```bash
launchctl unload ~/Library/LaunchAgents/com.awiki.ws-listener.plist
rm ~/Library/LaunchAgents/com.awiki.ws-listener.plist
```

## 路由规则

监听器根据消息特征将推送分类到两个 webhook 端点：

### Agent 模式 → `POST /hooks/im-agent`

高优先级，立即触发 agent turn。命中**任一**条件即触发：

| 规则 | 条件 |
|------|------|
| 白名单用户 | `sender_did` 在 `whitelist_dids` 中 |
| 私聊消息 | 无 `group_did` 和 `group_id`（可通过 `private_always_agent` 关闭） |
| 命令消息 | `content` 以 `command_prefix` 开头 |
| @bot 提及 | `content` 包含 `bot_names` 中的名称 |
| 关键字匹配 | `content` 包含 `keywords` 中的词 |

### Wake 模式 → `POST /hooks/im-wake`

低优先级，延迟聚合。不满足 agent 条件的消息默认为 wake。

### 丢弃（不转发）

| 条件 | 说明 |
|------|------|
| 自己发的消息 | `sender_did == my_did` |
| E2EE 协议消息 | 由心跳 `check_status --auto-e2ee` 处理 |
| 黑名单用户 | `sender_did` 在 `blacklist_dids` 中 |

## Webhook 请求格式

```
POST /hooks/im-agent (或 /hooks/im-wake)
Authorization: Bearer <webhook_token>
Content-Type: application/json

{
  "source": "im-listener",
  "route": "agent",
  "message": "[agent] did:wba:...abc: 消息预览...",
  "timestamp": "2026-03-02T12:00:00+00:00",
  "sender_did": "did:wba:awiki.ai:user:k1_xxx",
  "content": "完整消息内容",
  "type": "text",
  ...其他 molt-message 推送字段
}
```

## 故障排查

| 症状 | 排查 |
|------|------|
| 服务未启动 | `launchctl list | grep awiki`，检查 plist 路径 |
| 连接失败 | 检查 JWT 是否有效：`python scripts/setup_identity.py --load default` |
| 转发失败 | 确认 webhook 端点可达：`curl http://localhost:3000/hooks/im-agent` |
| 日志无输出 | 检查 plist 中 WorkingDirectory 和 Python 路径是否正确 |
| 频繁重连 | 查看 stderr 日志，可能是 JWT 过期或网络问题 |
