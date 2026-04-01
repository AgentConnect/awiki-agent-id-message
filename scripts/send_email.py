#!/usr/bin/env python3
"""AWiki Mail - 发送邮件 CLI 工具。

用法:
    python send_email.py --to bob@example.com \\
        --subject "Hello" --body "Message content" \\
        [--html "<p>HTML body</p>"] \\
        [--cc cc@example.com] \\
        [--credential default]

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


async def send_email(args):
    """发送邮件"""
    config = SDKConfig()

    # 获取 mail_service_url（从环境变量或默认值）
    mail_service_url = os.environ.get("E2E_MAIL_SERVICE_URL", "http://localhost:9899")

    # 创建认证器（复用 awiki-agent-id-message 的 credential 体系）
    auth_result = create_authenticator(args.credential, config)
    if auth_result is None:
        print(f"错误: 凭证 '{args.credential}' 不存在。请先运行 setup_identity.py", file=sys.stderr)
        sys.exit(1)

    auth_header, identity_data = auth_result

    # 发送请求
    import httpx

    async with httpx.AsyncClient(timeout=30) as client:
        headers = {"Content-Type": "application/json"}

        # 添加认证头
        if auth_header:
            for key, value in auth_header.items():
                headers[key] = value

        # 构造 JSON-RPC 请求
        payload = {
            "jsonrpc": "2.0",
            "method": "mail.send",
            "params": {
                "to": args.to,
                "cc": args.cc or [],
                "subject": args.subject,
                "body_text": args.body,
                "body_html": args.html,
            },
            "id": "cli-send-1",
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

        # 输出结果
        print(json.dumps(result["result"], indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description="AWiki Mail - 发送邮件")
    parser.add_argument("--to", required=True, nargs="+", help="收件人地址")
    parser.add_argument("--cc", nargs="*", default=[], help="抄送地址")
    parser.add_argument("--subject", required=True, help="邮件主题")
    parser.add_argument("--body", required=True, help="纯文本正文")
    parser.add_argument("--html", default=None, help="HTML 正文")
    parser.add_argument("--credential", default="default", help="凭证名称（默认 default）")
    args = parser.parse_args()

    asyncio.run(send_email(args))


if __name__ == "__main__":
    main()
