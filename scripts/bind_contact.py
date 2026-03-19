"""Bind additional contact info (email or phone) to an existing account.

Usage:
    # Bind email (for user who registered with phone)
    uv run python scripts/bind_contact.py --bind-email user@example.com

    # Bind phone (for user who registered with email)
    uv run python scripts/bind_contact.py --bind-phone +8613800138000

    # Specify credential name
    uv run python scripts/bind_contact.py --bind-email user@example.com --credential alice

[INPUT]: SDK (binding functions, email verification), credential_store (load identity)
[OUTPUT]: Bind email or phone to existing account
[POS]: Interactive CLI for post-registration identity binding

[PROTOCOL]:
1. Update this header when logic changes
2. Check the folder's CLAUDE.md after updating
"""

import argparse
import asyncio
import logging
import sys

import httpx

from utils import SDKConfig, create_user_service_client
from utils.handle import (
    bind_email_send,
    bind_phone_send_otp,
    bind_phone_verify,
    wait_for_email_verification,
)
from utils.logging_config import configure_logging
from credential_store import load_identity

logger = logging.getLogger(__name__)


async def do_bind(
    bind_email: str | None = None,
    bind_phone: str | None = None,
    credential_name: str = "default",
) -> None:
    """Execute the binding flow."""
    config = SDKConfig.load()

    # Load existing identity (must have JWT)
    identity = load_identity(credential_name)
    if identity is None:
        print(f"No credential found for '{credential_name}'. Register first.")
        sys.exit(1)
    jwt_token = identity.get("jwt_token")
    if not jwt_token:
        print("No JWT token found. Please run check_status.py to refresh your identity first.")
        sys.exit(1)

    async with create_user_service_client(config) as client:
        if bind_email:
            if "@" not in bind_email:
                print(f"Invalid email format: {bind_email} (must contain '@')")
                sys.exit(1)
            await _bind_email(client, bind_email, jwt_token)
        elif bind_phone:
            await _bind_phone(client, bind_phone, jwt_token)


async def _bind_email(client, email: str, jwt_token: str) -> None:
    """Bind email to existing account via activation link."""
    try:
        await wait_for_email_verification(
            client,
            email,
            send_fn=lambda: bind_email_send(client, email, jwt_token),
        )
    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        print(f"Failed to send activation email: {e}")
        sys.exit(1)

    print(f"Email {email} bound successfully.")


async def _bind_phone(client, phone: str, jwt_token: str) -> None:
    """Bind phone to existing account via OTP."""
    # 1. Send OTP
    print(f"\nSending OTP to {phone}...")
    try:
        await bind_phone_send_otp(client, phone, jwt_token)
        print("OTP sent.")
    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        print(f"Failed to send OTP: {e}")
        sys.exit(1)

    # 2. Prompt for code
    otp_code = input("Enter the OTP code: ").strip()
    if not otp_code:
        print("No OTP code provided.")
        sys.exit(1)

    # 3. Verify and bind
    try:
        result = await bind_phone_verify(client, phone, otp_code, jwt_token)
        if result.get("success"):
            print(f"Phone {result.get('phone', phone)} bound successfully.")
        else:
            print("Binding failed.")
            sys.exit(1)
    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        print(f"Binding failed: {e}")
        sys.exit(1)


def main() -> None:
    configure_logging(console_level=None, mirror_stdio=True)

    parser = argparse.ArgumentParser(
        description="Bind additional contact info (email or phone) to an existing account"
    )

    bind_group = parser.add_mutually_exclusive_group(required=True)
    bind_group.add_argument(
        "--bind-email", type=str, metavar="EMAIL",
        help="Email address to bind (will send activation link)",
    )
    bind_group.add_argument(
        "--bind-phone", type=str, metavar="PHONE",
        help="Phone number to bind (e.g., +8613800138000)",
    )

    parser.add_argument(
        "--credential", type=str, default="default",
        help="Credential storage name (default: default)",
    )

    args = parser.parse_args()
    logger.info(
        "bind_contact CLI started email=%s phone=%s credential=%s",
        args.bind_email,
        args.bind_phone,
        args.credential,
    )
    asyncio.run(do_bind(
        bind_email=args.bind_email,
        bind_phone=args.bind_phone,
        credential_name=args.credential,
    ))


if __name__ == "__main__":
    main()
