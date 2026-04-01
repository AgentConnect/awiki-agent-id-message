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

    # 下载附件
    python check_email.py --download-attachment <message_id> --attachment-index 0 [--output 文件名]

复用 awiki-agent-id-message 的 credential 体系。
"""

import argparse
import asyncio
import json
import os
import sys

# 添加 utils 到路径
UTILS_DIR = os.path.join(os.path.dirname(__file__), "utils")
if UTILS_DIR not in sys.path:
    sys.path.insert(0, UTILS_DIR)

from credential_store import create_authenticator
from config import SDKConfig


async def check_email(args):
    """查看邮件"""
    config = SDKConfig()

    # 获取 mail_service_url（生产环境建议设置为 https://awiki.ai 或前端网关地址）
    mail_service_url = os.environ.get("E2E_MAIL_SERVICE_URL", "https://awiki.ai")

    # 创建认证器（复用 awiki-agent-id-message 的 credential 体系）
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
        if args.download_attachment:
            # 下载附件
            payload = {
                "jsonrpc": "2.0",
                "method": "mail.getAttachment",
                "params": {
                    "message_id": args.download_attachment,
                    "attachment_index": args.attachment_index,
                },
                "id": "cli-attach-1",
            }
        elif args.read:
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
        if args.download_attachment:
            filename = data.get("filename") or f"attachment_{args.attachment_index}"
            content_b64 = data.get("content_base64") or ""
            content_type = data.get("content_type") or "application/octet-stream"
            size = data.get("size") or 0

            import base64
            from pathlib import Path

            try:
                content = base64.b64decode(content_b64)
            except Exception as e:
                print(f"错误: 附件内容 base64 解码失败: {e}", file=sys.stderr)
                sys.exit(1)

            # 计算输出路径
            if args.output:
                out_path = Path(args.output)
            else:
                out_path = Path(filename)

            try:
                out_path.write_bytes(content)
            except OSError as e:
                print(f"错误: 写入附件文件失败: {e}", file=sys.stderr)
                sys.exit(1)

            print(f"附件已保存: {out_path} ({size} bytes, content-type={content_type})")

        elif args.read:
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
    parser.add_argument(
        "--download-attachment",
        metavar="MESSAGE_ID",
        help="下载指定邮件的附件（需配合 --attachment-index）",
    )
    parser.add_argument(
        "--attachment-index",
        type=int,
        default=0,
        help="要下载的附件索引（从 0 开始，默认 0）",
    )
    parser.add_argument(
        "--output",
        help="附件保存到的文件路径（默认使用服务端返回的文件名）",
    )
    parser.add_argument("--credential", default="default", help="凭证名称（默认 default）")
    args = parser.parse_args()

    # 简单参数校验
    if args.download_attachment and args.mark_read:
        print("错误: --download-attachment 和 --mark-read 不能同时使用", file=sys.stderr)
        sys.exit(1)
    if args.download_attachment and args.account:
        print("错误: --download-attachment 和 --account 不能同时使用", file=sys.stderr)
        sys.exit(1)

    asyncio.run(check_email(args))


if __name__ == "__main__":
    main()
