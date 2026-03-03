"""Send a message to a specified DID.

Usage:
    # Send a text message
    uv run python scripts/send_message.py --to "did:wba:localhost:user:abc123" --content "Hello!"

    # Specify message type
    uv run python scripts/send_message.py --to "did:wba:localhost:user:abc123" --content "hello" --type text

[INPUT]: SDK (RPC calls), credential_store (load identity credentials)
[OUTPUT]: Send result
[POS]: Message sending script

[PROTOCOL]:
1. Update this header when logic changes
2. Check the folder's CLAUDE.md after updating
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from utils import SDKConfig, create_molt_message_client, authenticated_rpc_call
from credential_store import create_authenticator


MESSAGE_RPC = "/message/rpc"


async def send_message(
    receiver_did: str,
    content: str,
    msg_type: str = "text",
    credential_name: str = "default",
) -> None:
    """Send a message to a specified DID."""
    config = SDKConfig()
    auth_result = create_authenticator(credential_name, config)
    if auth_result is None:
        print(f"Credential '{credential_name}' unavailable; please create an identity first")
        sys.exit(1)

    auth, data = auth_result
    async with create_molt_message_client(config) as client:
        result = await authenticated_rpc_call(
            client,
            MESSAGE_RPC,
            "send",
            params={
                "sender_did": data["did"],
                "receiver_did": receiver_did,
                "content": content,
                "type": msg_type,
            },
            auth=auth,
            credential_name=credential_name,
        )
        print("Message sent successfully:")
        print(json.dumps(result, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Send DID message")
    parser.add_argument("--to", required=True, type=str, help="Receiver DID")
    parser.add_argument("--content", required=True, type=str, help="Message content")
    parser.add_argument("--type", type=str, default="text",
                        help="Message type (default: text)")
    parser.add_argument("--credential", type=str, default="default",
                        help="Credential name (default: default)")

    args = parser.parse_args()
    asyncio.run(send_message(args.to, args.content, args.type, args.credential))


if __name__ == "__main__":
    main()
