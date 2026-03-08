"""Recover a Handle by rebinding it to a new DID.

Usage:
    uv run python scripts/recover_handle.py --handle alice --phone +8613800138000

[INPUT]: SDK (handle OTP + recovery RPC), credential_store, local_store, e2ee_store
[OUTPUT]: Handle recovery result with local credential backup and cache migration
[POS]: Recovery CLI for users who lost the old DID private key but still control
       the original Handle phone number

[PROTOCOL]:
1. Update this header when logic changes
2. Check the folder's CLAUDE.md after updating
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from typing import Any

import local_store
from credential_store import (
    backup_identity,
    load_identity,
    prune_unreferenced_credential_dir,
    save_identity,
)
from e2ee_store import delete_e2ee_state
from utils import SDKConfig, create_user_service_client, recover_handle, send_otp
from utils.logging_config import configure_logging

logger = logging.getLogger(__name__)


def _migrate_local_cache(
    *,
    credential_name: str,
    old_did: str,
    new_did: str,
) -> dict[str, Any]:
    """Rebind local messages/contacts and clear stale E2EE artifacts."""
    conn = local_store.get_connection()
    local_store.ensure_schema(conn)
    try:
        rebound = local_store.rebind_owner_did(
            conn,
            old_owner_did=old_did,
            new_owner_did=new_did,
        )
        cleared = local_store.clear_owner_e2ee_data(
            conn,
            owner_did=old_did,
            credential_name=credential_name,
        )
    finally:
        conn.close()

    deleted_state = delete_e2ee_state(credential_name)
    return {
        "messages_rebound": rebound["messages"],
        "contacts_rebound": rebound["contacts"],
        "e2ee_outbox_cleared": cleared["e2ee_outbox"],
        "e2ee_state_deleted": deleted_state,
    }


async def do_recover(
    *,
    handle: str,
    phone: str,
    otp_code: str | None,
    credential_name: str,
) -> None:
    """Recover a Handle with phone OTP verification."""
    logger.info(
        "Recovering handle handle=%s credential=%s otp_provided=%s",
        handle,
        credential_name,
        otp_code is not None,
    )
    config = SDKConfig()
    old_credential = load_identity(credential_name)
    old_did = str(old_credential["did"]) if old_credential and old_credential.get("did") else None
    old_unique_id = (
        str(old_credential["unique_id"])
        if old_credential and old_credential.get("unique_id")
        else None
    )

    async with create_user_service_client(config) as client:
        if otp_code is None:
            print(f"Sending OTP to {phone}...")
            await send_otp(client, phone)
            print("OTP sent. Check your phone.")
            otp_code = input("Enter OTP code: ").strip()
            if not otp_code:
                print("OTP code is required.")
                sys.exit(1)

        identity, recover_result = await recover_handle(
            client,
            config,
            phone=phone,
            otp_code=otp_code,
            handle=handle,
        )

    backup_path = backup_identity(credential_name) if old_credential is not None else None
    if backup_path is not None:
        print(f"Existing credential backed up to: {backup_path}")

    save_identity(
        did=identity.did,
        unique_id=identity.unique_id,
        user_id=identity.user_id,
        private_key_pem=identity.private_key_pem,
        public_key_pem=identity.public_key_pem,
        jwt_token=identity.jwt_token,
        display_name=old_credential.get("name") if old_credential else handle,
        handle=handle,
        name=credential_name,
        did_document=identity.did_document,
        e2ee_signing_private_pem=identity.e2ee_signing_private_pem,
        e2ee_agreement_private_pem=identity.e2ee_agreement_private_pem,
        replace_existing=True,
    )

    cache_migration: dict[str, Any] | None = None
    if old_did and old_did != identity.did:
        cache_migration = _migrate_local_cache(
            credential_name=credential_name,
            old_did=old_did,
            new_did=identity.did,
        )
    if old_unique_id and old_unique_id != identity.unique_id:
        prune_unreferenced_credential_dir(old_unique_id)

    print("Handle recovered successfully:")
    print(
        json.dumps(
            {
                "did": identity.did,
                "user_id": identity.user_id,
                "handle": recover_result.get("handle", handle),
                "full_handle": recover_result.get("full_handle"),
                "credential_name": credential_name,
                "message": recover_result.get("message", "OK"),
                "local_backup_path": str(backup_path) if backup_path else None,
                "local_cache_migration": cache_migration,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


def main() -> None:
    """CLI entry point."""
    configure_logging(console_level=None, mirror_stdio=True)

    parser = argparse.ArgumentParser(description="Recover a Handle with phone OTP")
    parser.add_argument("--handle", required=True, type=str, help="Handle local-part")
    parser.add_argument("--phone", required=True, type=str, help="Phone number")
    parser.add_argument("--otp-code", type=str, default=None, help="OTP code")
    parser.add_argument(
        "--credential",
        type=str,
        default="default",
        help="Credential storage name (default: default)",
    )
    args = parser.parse_args()

    asyncio.run(
        do_recover(
            handle=args.handle,
            phone=args.phone,
            otp_code=args.otp_code,
            credential_name=args.credential,
        )
    )


if __name__ == "__main__":
    main()
