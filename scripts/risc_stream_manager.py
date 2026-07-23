#!/usr/bin/env python3
"""Manage Google RISC stream configuration.

Usage examples:
  python scripts/risc_stream_manager.py token --service-account /path/key.json
  python scripts/risc_stream_manager.py update --service-account /path/key.json --receiver-url https://api.example.com/api/v1/auth/risc/events
  python scripts/risc_stream_manager.py get --service-account /path/key.json
  python scripts/risc_stream_manager.py verify --service-account /path/key.json --state "probe-123"
  python scripts/risc_stream_manager.py status --service-account /path/key.json --value disabled
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import jwt
import requests

RISC_AUDIENCE = "https://risc.googleapis.com/google.identity.risc.v1beta.RiscManagementService"
RISC_BASE = "https://risc.googleapis.com/v1beta"

DEFAULT_EVENTS = [
    "https://schemas.openid.net/secevent/risc/event-type/sessions-revoked",
    "https://schemas.openid.net/secevent/oauth/event-type/tokens-revoked",
    "https://schemas.openid.net/secevent/oauth/event-type/token-revoked",
    "https://schemas.openid.net/secevent/risc/event-type/account-disabled",
    "https://schemas.openid.net/secevent/risc/event-type/account-credential-change-required",
    "https://schemas.openid.net/secevent/risc/event-type/verification",
]


def load_service_account(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"Service account file not found: {path}")
    data = json.loads(p.read_text(encoding="utf-8"))
    required = ["client_email", "private_key", "private_key_id"]
    missing = [k for k in required if not data.get(k)]
    if missing:
        raise SystemExit(f"Invalid service account JSON, missing: {', '.join(missing)}")
    return data


def make_bearer_token(service_account: dict[str, Any]) -> str:
    now = int(time.time())
    payload = {
        "iss": service_account["client_email"],
        "sub": service_account["client_email"],
        "aud": RISC_AUDIENCE,
        "iat": now,
        "exp": now + 3600,
    }
    token = jwt.encode(
        payload,
        service_account["private_key"],
        algorithm="RS256",
        headers={"kid": service_account["private_key_id"]},
    )
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token


def auth_headers(bearer: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {bearer}",
        "Content-Type": "application/json",
    }


def post_json(url: str, bearer: str, payload: dict[str, Any]) -> dict[str, Any]:
    resp = requests.post(url, headers=auth_headers(bearer), json=payload, timeout=20)
    if resp.status_code >= 400:
        raise SystemExit(f"HTTP {resp.status_code} calling {url}: {resp.text}")
    return resp.json() if resp.text.strip() else {}


def get_json(url: str, bearer: str) -> dict[str, Any]:
    resp = requests.get(url, headers=auth_headers(bearer), timeout=20)
    if resp.status_code >= 400:
        raise SystemExit(f"HTTP {resp.status_code} calling {url}: {resp.text}")
    return resp.json() if resp.text.strip() else {}


def cmd_token(args: argparse.Namespace) -> None:
    sa = load_service_account(args.service_account)
    print(make_bearer_token(sa))


def cmd_update(args: argparse.Namespace) -> None:
    if not args.receiver_url.startswith("https://"):
        raise SystemExit("receiver_url must be HTTPS")

    sa = load_service_account(args.service_account)
    bearer = make_bearer_token(sa)
    events = args.events or DEFAULT_EVENTS

    payload = {
        "delivery": {
            "delivery_method": "https://schemas.openid.net/secevent/risc/delivery-method/push",
            "url": args.receiver_url,
        },
        "events_requested": events,
    }

    data = post_json(f"{RISC_BASE}/stream:update", bearer, payload)
    print(json.dumps(data, indent=2, ensure_ascii=True))


def cmd_get(args: argparse.Namespace) -> None:
    sa = load_service_account(args.service_account)
    bearer = make_bearer_token(sa)
    data = get_json(f"{RISC_BASE}/stream", bearer)
    print(json.dumps(data, indent=2, ensure_ascii=True))


def cmd_verify(args: argparse.Namespace) -> None:
    sa = load_service_account(args.service_account)
    bearer = make_bearer_token(sa)
    state = args.state or f"verify-{int(time.time())}"
    data = post_json(f"{RISC_BASE}/stream:verify", bearer, {"state": state})
    print(json.dumps(data, indent=2, ensure_ascii=True))


def cmd_status(args: argparse.Namespace) -> None:
    if args.value not in {"enabled", "disabled"}:
        raise SystemExit("status must be 'enabled' or 'disabled'")

    sa = load_service_account(args.service_account)
    bearer = make_bearer_token(sa)
    data = post_json(f"{RISC_BASE}/stream/status:update", bearer, {"status": args.value})
    print(json.dumps(data, indent=2, ensure_ascii=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Google RISC stream manager")
    sub = parser.add_subparsers(dest="command", required=True)

    p_token = sub.add_parser("token", help="Generate a bearer token for RISC API")
    p_token.add_argument("--service-account", required=True, help="Path to service account JSON")
    p_token.set_defaults(func=cmd_token)

    p_update = sub.add_parser("update", help="Create/update stream config")
    p_update.add_argument("--service-account", required=True, help="Path to service account JSON")
    p_update.add_argument("--receiver-url", required=True, help="HTTPS receiver URL")
    p_update.add_argument(
        "--events",
        nargs="+",
        help="Space-separated event type URIs. If omitted, uses secure defaults.",
    )
    p_update.set_defaults(func=cmd_update)

    p_get = sub.add_parser("get", help="Get current stream config")
    p_get.add_argument("--service-account", required=True, help="Path to service account JSON")
    p_get.set_defaults(func=cmd_get)

    p_verify = sub.add_parser("verify", help="Send verification event")
    p_verify.add_argument("--service-account", required=True, help="Path to service account JSON")
    p_verify.add_argument("--state", help="Opaque string echoed back in verification event")
    p_verify.set_defaults(func=cmd_verify)

    p_status = sub.add_parser("status", help="Enable or disable stream")
    p_status.add_argument("--service-account", required=True, help="Path to service account JSON")
    p_status.add_argument("--value", required=True, choices=["enabled", "disabled"])
    p_status.set_defaults(func=cmd_status)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
