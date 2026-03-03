"""Check inbox, view chat history, mark messages as read.

Usage:
    # View inbox
    uv run python scripts/check_inbox.py

    # Limit result count
    uv run python scripts/check_inbox.py --limit 5

    # View chat history with a specific DID
    uv run python scripts/check_inbox.py --history "did:wba:localhost:user:abc123"

    # Mark messages as read
    uv run python scripts/check_inbox.py --mark-read msg_id_1 msg_id_2

[INPUT]: SDK (RPC calls), credential_store (load identity credentials)
[OUTPUT]: Inbox message list / chat history / mark-read result
[POS]: Message receiving and processing script

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


async def check_inbox(credential_name: str = "default", limit: int = 20) -> None:
    """View inbox."""
    config = SDKConfig()
    auth_result = create_authenticator(credential_name, config)
    if auth_result is None:
        print(f"Credential '{credential_name}' unavailable; please create an identity first")
        sys.exit(1)

    auth, data = auth_result
    async with create_molt_message_client(config) as client:
        inbox = await authenticated_rpc_call(
            client,
            MESSAGE_RPC,
            "get_inbox",
            params={"user_did": data["did"], "limit": limit},
            auth=auth,
            credential_name=credential_name,
        )
        print(json.dumps(inbox, indent=2, ensure_ascii=False))


async def get_history(
    peer_did: str,
    credential_name: str = "default",
    limit: int = 50,
) -> None:
    """View chat history with a specific DID."""
    config = SDKConfig()
    auth_result = create_authenticator(credential_name, config)
    if auth_result is None:
        print(f"Credential '{credential_name}' unavailable; please create an identity first")
        sys.exit(1)

    auth, data = auth_result
    async with create_molt_message_client(config) as client:
        history = await authenticated_rpc_call(
            client,
            MESSAGE_RPC,
            "get_history",
            params={
                "user_did": data["did"],
                "peer_did": peer_did,
                "limit": limit,
            },
            auth=auth,
            credential_name=credential_name,
        )
        print(json.dumps(history, indent=2, ensure_ascii=False))


async def mark_read(
    message_ids: list[str],
    credential_name: str = "default",
) -> None:
    """Mark messages as read."""
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
            "mark_read",
            params={
                "user_did": data["did"],
                "message_ids": message_ids,
            },
            auth=auth,
            credential_name=credential_name,
        )
        print("Marked as read successfully:")
        print(json.dumps(result, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Check inbox and manage messages")
    parser.add_argument("--history", type=str, help="View chat history with a specific DID")
    parser.add_argument("--mark-read", nargs="+", type=str,
                        help="Mark specified message IDs as read")
    parser.add_argument("--limit", type=int, default=20,
                        help="Result count limit (default: 20)")
    parser.add_argument("--credential", type=str, default="default",
                        help="Credential name (default: default)")

    args = parser.parse_args()

    if args.mark_read:
        asyncio.run(mark_read(args.mark_read, args.credential))
    elif args.history:
        asyncio.run(get_history(args.history, args.credential, args.limit))
    else:
        asyncio.run(check_inbox(args.credential, args.limit))


if __name__ == "__main__":
    main()
