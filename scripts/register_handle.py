"""Register a Handle (human-readable DID alias) interactively.

Usage:
    # Register with phone (will prompt for OTP)
    uv run python scripts/register_handle.py --handle alice --phone +8613800138000

    # Register with email (email must be verified via activation link first)
    uv run python scripts/register_handle.py --handle alice --email user@example.com

    # With invite code (for short handles <= 4 chars)
    uv run python scripts/register_handle.py --handle bob --phone +8613800138000 --invite-code ABC123

    # Specify credential name
    uv run python scripts/register_handle.py --handle alice --phone +8613800138000 --credential myhandle

[INPUT]: SDK (handle registration, OTP, email verification), credential_store (save identity),
         logging_config
[OUTPUT]: Register Handle + DID identity and save credentials
[POS]: Interactive CLI for Handle registration (supports phone SMS or email verification)

[PROTOCOL]:
1. Update this header when logic changes
2. Check the folder's CLAUDE.md after updating
"""

import argparse
import asyncio
import logging
import sys

import httpx

from utils import SDKConfig, create_user_service_client, send_otp, register_handle
from utils.handle import (
    register_handle_with_email,
    wait_for_email_verification,
)
from utils.logging_config import configure_logging
from credential_store import save_identity

logger = logging.getLogger(__name__)


async def do_register(
    handle: str,
    phone: str | None = None,
    email: str | None = None,
    otp_code: str | None = None,
    invite_code: str | None = None,
    name: str | None = None,
    credential_name: str = "default",
) -> None:
    """Register a Handle interactively (phone or email)."""
    logger.info(
        "Registering handle handle=%s credential=%s phone=%s email=%s invite_code_present=%s",
        handle,
        credential_name,
        bool(phone),
        bool(email),
        bool(invite_code),
    )
    config = SDKConfig.load()
    print(f"Service configuration:")
    print(f"  user-service: {config.user_service_url}")
    print(f"  DID domain  : {config.did_domain}")

    if email and otp_code:
        print("Warning: --otp-code is ignored in email registration mode.")

    async with create_user_service_client(config) as client:
        if email:
            # === Email registration flow ===
            identity = await _register_with_email(
                client, config, handle, email, invite_code, name,
            )
        elif phone:
            # === Phone registration flow (existing) ===
            identity = await _register_with_phone(
                client, config, handle, phone, otp_code, invite_code, name,
            )
        else:
            print("Error: either --phone or --email is required.")
            sys.exit(1)

        print(f"  Handle    : {handle}.{config.did_domain}")
        print(f"  DID       : {identity.did}")
        print(f"  unique_id : {identity.unique_id}")
        print(f"  user_id   : {identity.user_id}")
        print(f"  JWT token : {identity.jwt_token[:50]}...")

        # Save credential
        path = save_identity(
            did=identity.did,
            unique_id=identity.unique_id,
            user_id=identity.user_id,
            private_key_pem=identity.private_key_pem,
            public_key_pem=identity.public_key_pem,
            jwt_token=identity.jwt_token,
            display_name=name or handle,
            handle=handle,
            name=credential_name,
            did_document=identity.did_document,
            e2ee_signing_private_pem=identity.e2ee_signing_private_pem,
            e2ee_agreement_private_pem=identity.e2ee_agreement_private_pem,
        )
        print(f"\nCredential saved to: {path}")
        print(f"Credential name: {credential_name}")


async def _register_with_phone(client, config, handle, phone, otp_code, invite_code, name):
    """Phone-based registration (existing flow)."""
    if otp_code is None:
        print(f"\nSending OTP to {phone}...")
        await send_otp(client, phone)
        print("OTP sent. Check your phone.")
        otp_code = input("Enter OTP code: ").strip()
        if not otp_code:
            print("OTP code is required.")
            sys.exit(1)

    print(f"\nRegistering Handle '{handle}'...")
    return await register_handle(
        client=client,
        config=config,
        phone=phone,
        otp_code=otp_code,
        handle=handle,
        invite_code=invite_code,
        name=name or handle,
        is_public=True,
    )


async def _register_with_email(client, config, handle, email, invite_code, name):
    """Email-based registration (new flow)."""
    try:
        await wait_for_email_verification(client, email)
    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        print(f"Failed to send activation email: {e}")
        sys.exit(1)

    print(f"\nEmail verified. Registering Handle '{handle}'...")
    return await register_handle_with_email(
        client=client,
        config=config,
        email=email,
        handle=handle,
        invite_code=invite_code,
        name=name or handle,
        is_public=True,
    )


def main() -> None:
    configure_logging(console_level=None, mirror_stdio=True)

    parser = argparse.ArgumentParser(description="Register a Handle (human-readable DID alias)")
    parser.add_argument("--handle", required=True, type=str,
                        help="Handle local-part (e.g., alice)")

    # Phone or email (mutually exclusive group)
    auth_group = parser.add_mutually_exclusive_group(required=True)
    auth_group.add_argument("--phone", type=str,
                            help="Phone number in international format with country code "
                                 "(e.g., +8613800138000 for China, +14155552671 for US). "
                                 "China local 11-digit numbers are auto-prefixed with +86.")
    auth_group.add_argument("--email", type=str,
                            help="Email address (will send activation link if not yet verified)")

    parser.add_argument("--otp-code", type=str, default=None,
                        help="OTP code (phone mode only; if already obtained)")
    parser.add_argument("--invite-code", type=str, default=None,
                        help="Invite code (required for short handles <= 4 chars)")
    parser.add_argument("--name", type=str, default=None,
                        help="Display name (defaults to handle)")
    parser.add_argument("--credential", type=str, default="default",
                        help="Credential storage name (default: default)")

    args = parser.parse_args()
    logger.info(
        "register_handle CLI started handle=%s credential=%s",
        args.handle,
        args.credential,
    )
    asyncio.run(do_register(
        handle=args.handle,
        phone=args.phone,
        email=args.email,
        otp_code=args.otp_code,
        invite_code=args.invite_code,
        name=args.name,
        credential_name=args.credential,
    ))


if __name__ == "__main__":
    main()
