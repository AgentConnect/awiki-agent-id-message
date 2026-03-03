#!/usr/bin/env python3
"""WebSocket listener: long-running background process that receives molt-message pushes and routes to webhooks.

[INPUT]: credential_store (DID identity), SDKConfig, WsClient, ListenerConfig, E2eeHandler
[OUTPUT]: WebSocket -> HTTP webhook bridge (agent/wake dual endpoints) + launchd lifecycle management
[POS]: Standalone background process managed by launchd, reuses utils/ core tool layer

[PROTOCOL]:
1. Update this header when logic changes
2. Check the folder's CLAUDE.md after updating

Core pipeline:
  molt-message WS push -> listener receives -> E2EE intercept/decrypt -> route classification -> POST webhook

Subcommands:
  run       Run in foreground (for debugging)
  install   Install launchd service and start
  uninstall Uninstall launchd service
  start     Start an installed service
  stop      Stop a running service
  status    Show service status
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure scripts/ is in sys.path (consistent with other scripts)
_scripts_dir = os.path.dirname(os.path.abspath(__file__))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

import httpx

from credential_store import create_authenticator, load_identity, update_jwt
from e2ee_handler import E2eeHandler
from listener_config import ROUTING_MODES, ListenerConfig
from utils.config import SDKConfig
from utils.identity import DIDIdentity
from utils.ws import WsClient

logger = logging.getLogger("ws_listener")

# launchd constants
_PLIST_LABEL = "com.awiki.ws-listener"
_LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
_PLIST_DEST = _LAUNCH_AGENTS_DIR / f"{_PLIST_LABEL}.plist"
_PLIST_TEMPLATE = Path(__file__).resolve().parent.parent / "launchd" / f"{_PLIST_LABEL}.plist"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


# --- Utility Functions --------------------------------------------------------

def _truncate_did(did: str) -> str:
    """Abbreviate DID for display (first and last 8 characters)."""
    if len(did) <= 20:
        return did
    return f"{did[:8]}...{did[-8:]}"


# --- Route Classification ----------------------------------------------------

def classify_message(
    params: dict[str, Any],
    my_did: str,
    cfg: ListenerConfig,
) -> str | None:
    """Classify a message for routing.

    Args:
        params: The params field from a WebSocket push notification.
        my_did: The DID of the current listener itself.
        cfg: Listener configuration.

    Returns:
        "agent" -- high priority, trigger agent turn immediately.
        "wake"  -- low priority, deferred aggregation.
        None    -- drop, do not forward.
    """
    sender_did = params.get("sender_did", "")
    content = params.get("content", "")
    msg_type = params.get("type", "text")
    group_did = params.get("group_did")
    group_id = params.get("group_id")
    is_private = group_did is None and group_id is None

    # === Drop conditions (common to all modes) ===
    if sender_did == my_did:
        return None
    if msg_type in cfg.ignore_types:
        return None
    if sender_did in cfg.routing.blacklist_dids:
        return None

    # === Mode determination ===
    if cfg.mode == "agent-all":
        return "agent"
    if cfg.mode == "wake-all":
        return "wake"

    # === Smart mode: rule engine (any match -> agent) ===
    if sender_did in cfg.routing.whitelist_dids:
        return "agent"
    if is_private and cfg.routing.private_always_agent:
        return "agent"
    if isinstance(content, str) and content.startswith(cfg.routing.command_prefix):
        return "agent"
    if isinstance(content, str):
        for name in cfg.routing.bot_names:
            if name and name in content:
                return "agent"
        for kw in cfg.routing.keywords:
            if kw in content:
                return "agent"

    # === Default: Wake ===
    return "wake"


# --- Forwarding + Heartbeat --------------------------------------------------

async def _forward(
    http: httpx.AsyncClient,
    url: str,
    token: str,
    params: dict[str, Any],
    route: str,
    cfg: ListenerConfig,
) -> bool:
    """Forward a message to an OpenClaw webhook endpoint.

    Constructs different payloads based on route:
    - agent -> POST /hooks/agent  {"message": "...", "name": "IM", "wakeMode": "now"}
    - wake  -> POST /hooks/wake   {"text": "...", "mode": "now"}
    """
    sender = _truncate_did(params.get("sender_did", "unknown"))
    content = str(params.get("content", ""))
    content_preview = content[:50]
    msg_type = params.get("type", "text")
    group_did = params.get("group_did")
    is_private = group_did is None and params.get("group_id") is None
    e2ee_tag = "[E2EE] " if params.get("_e2ee") else ""

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    if route == "agent":
        # OpenClaw /hooks/agent format
        context = "DM" if is_private else f"Group({_truncate_did(group_did or '')})"
        body: dict[str, Any] = {
            "message": (
                f"[IM {context}] {sender} ({msg_type}):\n{content}"
            ),
            "name": cfg.agent_hook_name,
            "wakeMode": "now",
        }
    else:
        # OpenClaw /hooks/wake format
        body = {
            "text": f"[IM] {sender}: {content_preview}",
            "mode": "next-heartbeat",
        }

    try:
        resp = await http.post(url, json=body, headers=headers)
        if resp.is_success:
            logger.info(
                "%sForward success route=%s sender=%s -> %s [%d]",
                e2ee_tag, route, sender, url, resp.status_code,
            )
            return True
        logger.warning(
            "%sForward failed route=%s -> %s [%d] %s",
            e2ee_tag, route, url, resp.status_code, resp.text[:200],
        )
        return False
    except httpx.HTTPError as exc:
        logger.error("Forward error route=%s -> %s: %s", route, url, exc)
        return False


async def _heartbeat_task(ws: WsClient, interval: float) -> None:
    """Periodically send application-layer heartbeats."""
    while True:
        await asyncio.sleep(interval)
        try:
            ok = await ws.ping()
            if ok:
                logger.debug("Heartbeat pong OK")
            else:
                logger.warning("Heartbeat pong abnormal")
        except Exception as exc:
            logger.warning("Heartbeat failed: %s", exc)
            raise


# --- Identity + JWT -----------------------------------------------------------

def _build_identity(cred_data: dict[str, Any]) -> DIDIdentity:
    """Build a DIDIdentity from credential data."""
    private_key_pem = cred_data["private_key_pem"]
    if isinstance(private_key_pem, str):
        private_key_pem = private_key_pem.encode("utf-8")
    public_key_pem = cred_data.get("public_key_pem", b"")
    if isinstance(public_key_pem, str):
        public_key_pem = public_key_pem.encode("utf-8")

    return DIDIdentity(
        did=cred_data["did"],
        did_document=cred_data.get("did_document", {}),
        private_key_pem=private_key_pem,
        public_key_pem=public_key_pem,
        user_id=cred_data.get("user_id"),
        jwt_token=cred_data.get("jwt_token"),
    )


async def _refresh_jwt(
    credential_name: str,
    config: SDKConfig,
) -> str | None:
    """Attempt to refresh JWT via WBA authentication."""
    result = create_authenticator(credential_name, config)
    if result is None:
        return None
    auth, cred_data = result

    try:
        from utils.auth import get_jwt_via_wba
        from utils.client import create_user_service_client

        identity = _build_identity(cred_data)
        async with create_user_service_client(config) as client:
            token = await get_jwt_via_wba(client, identity, config.did_domain)
            update_jwt(credential_name, token)
            return token
    except Exception as exc:
        logger.error("JWT refresh failed: %s", exc)
        return None


# --- Main Listen Loop ---------------------------------------------------------

async def listen_loop(
    credential_name: str,
    cfg: ListenerConfig,
    config: SDKConfig | None = None,
) -> None:
    """Main listen loop. Infinite loop: connect -> receive -> classify -> forward, with automatic reconnection."""
    if config is None:
        config = SDKConfig()

    delay = cfg.reconnect_base_delay

    # E2EE handler initialization
    e2ee_handler: E2eeHandler | None = None
    if cfg.e2ee_enabled:
        e2ee_handler = E2eeHandler(
            credential_name,
            save_interval=cfg.e2ee_save_interval,
            decrypt_fail_action=cfg.e2ee_decrypt_fail_action,
        )

    async with httpx.AsyncClient(timeout=10.0, trust_env=False) as http:
        while True:
            cred_data = load_identity(credential_name)
            if cred_data is None:
                logger.error("Credential '%s' not found, retrying in %.0fs", credential_name, delay)
                await asyncio.sleep(delay)
                continue

            identity = _build_identity(cred_data)
            my_did = identity.did

            if not identity.jwt_token:
                logger.warning("Credential missing JWT, attempting refresh...")
                token = await _refresh_jwt(credential_name, config)
                if token:
                    identity.jwt_token = token
                else:
                    logger.error("JWT acquisition failed, retrying in %.0fs", delay)
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, cfg.reconnect_max_delay)
                    continue

            # E2EE handler lazy initialization (requires my_did)
            if e2ee_handler is not None and not e2ee_handler.is_ready:
                if not await e2ee_handler.initialize(my_did):
                    logger.warning("E2EE initialization failed, running in non-E2EE mode")
                    e2ee_handler = None

            logger.info("Connecting to WebSocket... DID=%s mode=%s e2ee=%s",
                        _truncate_did(my_did), cfg.mode,
                        e2ee_handler is not None and e2ee_handler.is_ready)

            heartbeat: asyncio.Task | None = None
            try:
                async with WsClient(config, identity) as ws:
                    delay = cfg.reconnect_base_delay
                    logger.info("WebSocket connected successfully")

                    heartbeat = asyncio.create_task(
                        _heartbeat_task(ws, cfg.heartbeat_interval),
                    )

                    while True:
                        notification = await ws.receive_notification(timeout=5.0)
                        if notification is None:
                            if e2ee_handler is not None:
                                await e2ee_handler.maybe_save_state()
                            continue

                        method = notification.get("method", "")
                        if method != "new_message":
                            logger.debug("Ignoring non-message notification: method=%s", method)
                            continue

                        params = notification.get("params", {})
                        msg_type = params.get("type", "text")

                        # E2EE message interception (before classify_message)
                        if (e2ee_handler is not None
                                and e2ee_handler.is_ready
                                and e2ee_handler.is_e2ee_type(msg_type)):
                            sender_did = params.get("sender_did", "")
                            if sender_did == my_did:
                                continue

                            if e2ee_handler.is_protocol_type(msg_type):
                                responses = await e2ee_handler.handle_protocol_message(params)
                                if responses:
                                    for resp_type, resp_content in responses:
                                        await ws.send_message(
                                            receiver_did=sender_did,
                                            content=json.dumps(resp_content),
                                            msg_type=resp_type,
                                        )
                                await e2ee_handler.maybe_save_state()
                                continue

                            if msg_type == "e2ee_msg":
                                decrypted = await e2ee_handler.decrypt_message(params)
                                if decrypted is None:
                                    continue
                                params = decrypted
                                await e2ee_handler.maybe_save_state()

                        # Original routing logic
                        route = classify_message(params, my_did, cfg)

                        if route is None:
                            logger.debug(
                                "Dropping message: sender=%s type=%s",
                                _truncate_did(params.get("sender_did", "")),
                                params.get("type", ""),
                            )
                            continue

                        url = cfg.agent_webhook_url if route == "agent" else cfg.wake_webhook_url
                        await _forward(http, url, cfg.webhook_token, params, route, cfg)

            except asyncio.CancelledError:
                if e2ee_handler is not None:
                    await e2ee_handler.force_save_state()
                logger.info("Listen loop cancelled")
                raise
            except Exception as exc:
                logger.warning("Connection lost: %s, reconnecting in %.0fs", exc, delay)
            finally:
                if heartbeat and not heartbeat.done():
                    heartbeat.cancel()
                    try:
                        await heartbeat
                    except (asyncio.CancelledError, Exception):
                        pass
                if e2ee_handler is not None:
                    await e2ee_handler.force_save_state()

            new_token = await _refresh_jwt(credential_name, config)
            if new_token:
                logger.info("JWT refreshed")

            await asyncio.sleep(delay)
            delay = min(delay * 2, cfg.reconnect_max_delay)


# --- launchd Lifecycle Management ---------------------------------------------

def _find_python() -> str:
    """Find the current venv or system Python path."""
    # Prefer venv
    venv_python = _PROJECT_ROOT / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def _generate_plist(
    credential: str,
    config_path: str | None,
    mode: str | None,
) -> str:
    """Generate launchd plist XML content."""
    python_path = _find_python()
    script_path = str(Path(__file__).resolve())

    args = [python_path, script_path, "run",
            "--credential", credential]
    if config_path:
        args.extend(["--config", str(Path(config_path).resolve())])
    if mode:
        args.extend(["--mode", mode])

    args_xml = "\n        ".join(f"<string>{a}</string>" for a in args)

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{_PLIST_LABEL}</string>

    <key>ProgramArguments</key>
    <array>
        {args_xml}
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>ThrottleInterval</key>
    <integer>10</integer>

    <key>WorkingDirectory</key>
    <string>{_PROJECT_ROOT}</string>

    <key>StandardOutPath</key>
    <string>/tmp/awiki-ws-listener.stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/awiki-ws-listener.stderr.log</string>
</dict>
</plist>
"""


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    """Run a launchctl command."""
    return subprocess.run(
        ["launchctl", *args],
        capture_output=True, text=True,
    )


def cmd_install(args: argparse.Namespace) -> None:
    """Install and start the launchd service."""
    if _PLIST_DEST.exists():
        print(f"Service already installed: {_PLIST_DEST}")
        print("To reinstall, run first: python scripts/ws_listener.py uninstall")
        return

    _LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)

    plist_content = _generate_plist(args.credential, args.config, args.mode)
    _PLIST_DEST.write_text(plist_content, encoding="utf-8")
    print(f"plist written to: {_PLIST_DEST}")

    result = _launchctl("load", str(_PLIST_DEST))
    if result.returncode == 0:
        print("Service installed and started")
        print(f"  Logs: tail -f /tmp/awiki-ws-listener.stderr.log")
    else:
        print(f"launchctl load failed: {result.stderr.strip()}")


def cmd_uninstall(args: argparse.Namespace) -> None:
    """Uninstall the launchd service."""
    if not _PLIST_DEST.exists():
        print("Service not installed")
        return

    result = _launchctl("unload", str(_PLIST_DEST))
    if result.returncode != 0:
        print(f"launchctl unload warning: {result.stderr.strip()}")

    _PLIST_DEST.unlink()
    print("Service uninstalled")


def cmd_start(args: argparse.Namespace) -> None:
    """Start an installed service."""
    if not _PLIST_DEST.exists():
        print("Service not installed, run first: python scripts/ws_listener.py install")
        return

    result = _launchctl("load", str(_PLIST_DEST))
    if result.returncode == 0:
        print("Service started")
    else:
        print(f"Start failed: {result.stderr.strip()}")


def cmd_stop(args: argparse.Namespace) -> None:
    """Stop a running service."""
    if not _PLIST_DEST.exists():
        print("Service not installed")
        return

    result = _launchctl("unload", str(_PLIST_DEST))
    if result.returncode == 0:
        print("Service stopped")
    else:
        print(f"Stop failed: {result.stderr.strip()}")


def cmd_status(args: argparse.Namespace) -> None:
    """Show service status."""
    output: dict[str, Any] = {
        "installed": _PLIST_DEST.exists(),
        "plist_path": str(_PLIST_DEST),
    }

    if _PLIST_DEST.exists():
        result = _launchctl("list")
        running = _PLIST_LABEL in result.stdout
        output["running"] = running

        # Read plist to extract configuration info
        try:
            plist_text = _PLIST_DEST.read_text(encoding="utf-8")
            # Simple extraction of mode (if present)
            if "--mode" in plist_text:
                # Find the value after --mode
                parts = plist_text.split("--mode")
                if len(parts) > 1:
                    import re
                    match = re.search(r"<string>(\w[\w-]*)</string>", parts[1])
                    if match:
                        output["mode"] = match.group(1)
        except Exception:
            pass

        # Log file info
        stderr_log = Path("/tmp/awiki-ws-listener.stderr.log")
        stdout_log = Path("/tmp/awiki-ws-listener.stdout.log")
        if stderr_log.exists():
            output["log_size_bytes"] = stderr_log.stat().st_size
            output["log_path"] = str(stderr_log)
    else:
        output["running"] = False

    print(json.dumps(output, indent=2, ensure_ascii=False))


def cmd_run(args: argparse.Namespace) -> None:
    """Run the listener in foreground."""
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    cfg = ListenerConfig.load(args.config, mode_override=args.mode)
    logger.info(
        "Config loaded: mode=%s agent=%s wake=%s",
        cfg.mode, cfg.agent_webhook_url, cfg.wake_webhook_url,
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    task: asyncio.Task | None = None

    def _shutdown(signum: int, frame: Any) -> None:
        logger.info("Received signal %d, shutting down...", signum)
        if task and not task.done():
            task.cancel()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        task = loop.create_task(listen_loop(args.credential, cfg))
        loop.run_until_complete(task)
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("Listener stopped")
    finally:
        loop.close()


# --- CLI ----------------------------------------------------------------------

def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="WebSocket listener: receive molt-message pushes and route to webhooks",
    )
    subparsers = parser.add_subparsers(dest="command", help="subcommands")

    # --- run ---
    p_run = subparsers.add_parser("run", help="Run in foreground (for debugging)")
    p_run.add_argument("--credential", default="default", help="Credential name")
    p_run.add_argument("--config", default=None, help="JSON config file path")
    p_run.add_argument("--mode", choices=ROUTING_MODES, default=None,
                       help="Routing mode (overrides config file)")
    p_run.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    p_run.set_defaults(func=cmd_run)

    # --- install ---
    p_install = subparsers.add_parser("install", help="Install launchd service and start")
    p_install.add_argument("--credential", default="default", help="Credential name")
    p_install.add_argument("--config", default=None, help="JSON config file path")
    p_install.add_argument("--mode", choices=ROUTING_MODES, default=None,
                           help="Routing mode")
    p_install.set_defaults(func=cmd_install)

    # --- uninstall ---
    p_uninstall = subparsers.add_parser("uninstall", help="Uninstall launchd service")
    p_uninstall.set_defaults(func=cmd_uninstall)

    # --- start ---
    p_start = subparsers.add_parser("start", help="Start an installed service")
    p_start.set_defaults(func=cmd_start)

    # --- stop ---
    p_stop = subparsers.add_parser("stop", help="Stop a running service")
    p_stop.set_defaults(func=cmd_stop)

    # --- status ---
    p_status = subparsers.add_parser("status", help="Show service status")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
