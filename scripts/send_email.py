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
UTILS_DIR = os.path.join(os.path.dirname(__file__), "utils")
if UTILS_DIR not in sys.path:
    sys.path.insert(0, UTILS_DIR)

from credential_store import create_authenticator
from config import SDKConfig
from utils import create_mail_service_client
from utils.rpc import authenticated_rpc_call


async def send_email(args):
    """发送邮件（通过 awiki-mail-service 的 mail.send RPC）。"""
    config = SDKConfig()

    # 获取 mail_service_url（生产环境建议设置为 https://awiki.ai 或前端网关地址）
    mail_service_url = os.environ.get("E2E_MAIL_SERVICE_URL", "https://awiki.ai")

    # 创建认证器（复用 awiki-agent-id-message 的 credential 体系）
    auth_result = create_authenticator(args.credential, config)
    if auth_result is None:
        print(f"错误: 凭证 '{args.credential}' 不存在。请先运行 setup_identity.py", file=sys.stderr)
        sys.exit(1)

    auth, identity_data = auth_result

    # 构造 JSON-RPC 参数
    params = {
        "to": args.to,
        "cc": args.cc or [],
        "subject": args.subject,
        "body_text": args.body,
        "body_html": args.html,
    }

    # 发送请求（复用 authenticated_rpc_call + DIDWbaAuthHeader）
    async with create_mail_service_client(mail_service_url) as client:
        try:
            result = await authenticated_rpc_call(
                client,
                "/mail/rpc",
                "mail.send",
                params=params,
                auth=auth,
                credential_name=args.credential,
            )
        except Exception as e:
            print(f"错误: 调用 mail.send 失败: {e}", file=sys.stderr)
            sys.exit(1)

        # 输出结果
        print(json.dumps(result, indent=2, ensure_ascii=False))


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
