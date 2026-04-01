#!/usr/bin/env python3
"""AWiki Mail - 查看邮件 CLI 工具。

用法:
    # 查看收件箱
    python check_email.py

    # 查看指定文件夹
    python check_email.py --folder sent

    # 只看未读
    python check_email.py --unread

    # 查看邮件详情
    python check_email.py --read <message_id>

    # 标记已读
    python check_email.py --mark-read <message_id>

    # 查看账户信息
    python check_email.py --account

复用 awiki-agent-id-message 的 credential 体系。
"""

import argparse
import asyncio
import json
import os
import sys

# 添加 utils 到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "utils"))

from auth import create_authenticator
from config import SDKConfig


async def check_email(args):
    """查看邮件"""
    config = SDKConfig()

    # 获取 mail_service_url
    mail_service_url = os.environ.get("E2E_MAIL_SERVICE_URL", "http://localhost:9899")

    # 创建认证器
    auth_result = create_authenticator(args.credential, config)
    if auth_result is None:
        print(f"错误: 凭证 '{args.credential}' 不存在", file=sys.stderr)
        sys.exit(1)

    auth_header, identity_data = auth_result

    import httpx

    async with httpx.AsyncClient(timeout=30) as client:
        headers = {"Content-Type": "application/json"}
        if auth_header:
            for key, value in auth_header.items():
                headers[key] = value

        # 根据参数选择操作
        if args.read:
            # 查看邮件详情
            payload = {
                "jsonrpc": "2.0",
                "method": "mail.getMessage",
                "params": {"message_id": args.read},
                "id": "cli-get-1",
            }
        elif args.mark_read:
            # 标记已读
            payload = {
                "jsonrpc": "2.0",
                "method": "mail.markRead",
                "params": {"message_ids": args.mark_read, "is_read": True},
                "id": "cli-mark-1",
            }
        elif args.account:
            # 查看账户信息
            payload = {
                "jsonrpc": "2.0",
                "method": "mail.getMailbox",
                "params": {},
                "id": "cli-account-1",
            }
        else:
            # 列出邮件
            params = {
                "folder": args.folder,
                "limit": args.limit,
                "offset": args.offset,
                "unread_only": args.unread,
            }
            payload = {
                "jsonrpc": "2.0",
                "method": "mail.getInbox",
                "params": params,
                "id": "cli-list-1",
            }

        resp = await client.post(f"{mail_service_url}/mail/rpc", json=payload, headers=headers)

        if resp.status_code != 200:
            print(f"错误: HTTP {resp.status_code}", file=sys.stderr)
            print(resp.text, file=sys.stderr)
            sys.exit(1)

        result = resp.json()

        if "error" in result:
            print(f"错误: {result['error']}", file=sys.stderr)
            sys.exit(1)

        data = result["result"]

        # 格式化输出
        if args.read:
            # 邮件详情
            print(f"发件人: {data['from_addr']}")
            if data.get("from_name"):
                print(f"        ({data['from_name']})")
            print(f"收件人: {data['to_addr']}")
            if data.get("cc_addr"):
                print(f"抄送:   {data['cc_addr']}")
            print(f"主题:   {data['subject']}")
            print(f"时间:   {data['sent_at']}")
            print(f"状态:   {'已读' if data['is_read'] else '未读'}")
            print("-" * 60)
            print(data.get("body_text", "(无纯文本正文)"))
        elif args.mark_read:
            print(f"已标记 {data['updated']} 封邮件为已读")
        elif args.account:
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            # 邮件列表
            total = data["total"]
            unread = data["unread_count"]
            messages = data["messages"]

            print(f"总计: {total} 封 | 未读: {unread} 封 | 当前页: {len(messages)} 封")
            print("-" * 80)

            for msg in messages:
                flag = "*" if not msg["is_read"] else " "
                att = "[附]" if msg.get("has_attachments") else "   "
                time = msg["sent_at"][:16] if msg.get("sent_at") else msg["created_at"][:16]
                from_addr = msg["from_addr"][:30]
                subject = (msg["subject"] or "(无主题)")[:40]

                print(f" {flag} {att} {time}  {from_addr:<30} {subject}")

            print("-" * 80)


def main():
    parser = argparse.ArgumentParser(description="AWiki Mail - 查看邮件")
    parser.add_argument("--folder", default="inbox", help="文件夹（默认 inbox）")
    parser.add_argument("--unread", action="store_true", help="仅显示未读邮件")
    parser.add_argument("--limit", type=int, default=20, help="返回数量（默认 20）")
    parser.add_argument("--offset", type=int, default=0, help="偏移量（默认 0）")
    parser.add_argument("--read", metavar="MESSAGE_ID", help="查看邮件详情")
    parser.add_argument("--mark-read", nargs="+", metavar="MESSAGE_ID", help="标记已读")
    parser.add_argument("--account", action="store_true", help="显示邮箱账户信息")
    parser.add_argument("--credential", default="default", help="凭证名称（默认 default）")
    args = parser.parse_args()

    asyncio.run(check_email(args))


if __name__ == "__main__":
    main()
