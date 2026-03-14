"""Register a Handle (human-readable DID alias) with a verification code.

Usage:
    # Step 1: Send a verification code to the phone number
    python scripts/send_verification_code.py --phone +8613800138000

    # Step 2: Register a Handle with the received code
    python scripts/register_handle.py --handle alice --phone +8613800138000 --otp-code 123456

    # Short handles (<= 4 chars) also require an invite code
    python scripts/register_handle.py --handle bob --phone +8613800138000 --otp-code 123456 --invite-code ABC123

    # Specify credential name
    python scripts/register_handle.py --handle alice --phone +8613800138000 --otp-code 123456 --credential myhandle

[INPUT]: SDK (handle registration), credential_store (save identity),
         logging_config, pre-issued verification code
[OUTPUT]: Register Handle + DID identity and save credentials
[POS]: Non-interactive CLI for Handle registration with a pre-issued
       verification code

[PROTOCOL]:
1. Update this header when logic changes
2. Check the folder's CLAUDE.md after updating
"""

import argparse
import asyncio
import logging

from utils import SDKConfig, create_user_service_client, register_handle
from utils.logging_config import configure_logging
from credential_store import save_identity

logger = logging.getLogger(__name__)


def _require_otp_code(otp_code: str | None) -> str:
    """Return a normalized verification code or raise a usage error."""
    if otp_code is None or not otp_code.strip():
        raise ValueError(
            "Verification code is required. First run "
            "'python scripts/send_verification_code.py --phone <number>' "
            "and then retry with '--otp-code <code>'."
        )
    return otp_code.strip()


async def do_register(
    handle: str,
    phone: str,
    otp_code: str | None,
    invite_code: str | None = None,
    name: str | None = None,
    credential_name: str = "default",
) -> None:
    """Register a Handle using a pre-issued verification code."""
    normalized_otp_code = _require_otp_code(otp_code)
    logger.info(
        "Registering handle handle=%s credential=%s invite_code_present=%s",
        handle,
        credential_name,
        bool(invite_code),
    )
    config = SDKConfig()
    print(f"Service configuration:")
    print(f"  user-service: {config.user_service_url}")
    print(f"  DID domain  : {config.did_domain}")

    async with create_user_service_client(config) as client:
        print(f"\nRegistering Handle '{handle}'...")
        identity = await register_handle(
            client=client,
            config=config,
            phone=phone,
            otp_code=normalized_otp_code,
            handle=handle,
            invite_code=invite_code,
            name=name or handle,
            is_public=True,
        )

        print(f"  Handle    : {handle}.{config.did_domain}")
        print(f"  DID       : {identity.did}")
        print(f"  unique_id : {identity.unique_id}")
        print(f"  user_id   : {identity.user_id}")
        print(f"  JWT token : {identity.jwt_token[:50]}...")

        # 3. Save credential
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


def main() -> None:
    configure_logging(console_level=None, mirror_stdio=True)

    parser = argparse.ArgumentParser(
        description="Register a Handle (human-readable DID alias) with a pre-issued "
        "verification code"
    )
    parser.add_argument("--handle", required=True, type=str,
                        help="Handle local-part (e.g., alice)")
    parser.add_argument("--phone", required=True, type=str,
                        help="Phone number in international format with country code "
                             "(e.g., +8613800138000 for China, +14155552671 for US). "
                             "China local 11-digit numbers are auto-prefixed with +86. "
                             "Non-mainland China numbers MUST include the country code to receive SMS.")
    parser.add_argument("--otp-code", type=str, default=None,
                        help="Verification code from scripts/send_verification_code.py")
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
    try:
        asyncio.run(do_register(
            handle=args.handle,
            phone=args.phone,
            otp_code=args.otp_code,
            invite_code=args.invite_code,
            name=args.name,
            credential_name=args.credential,
        ))
    except ValueError as exc:
        parser.exit(status=2, message=f"Error: {exc}\n")


if __name__ == "__main__":
    main()
