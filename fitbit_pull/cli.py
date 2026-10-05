"""Command-line entry point: `fitbit-pull`."""

import argparse
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

from oauthlib.oauth2 import OAuth2Error

from . import auth
from .client import ApiError, HealthClient
from .datatypes import DATA_TYPES, DEFAULT_TYPES, resolve, scopes_for
from .export import export_csv
from .pull import pull


def _types_arg(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _client(args: argparse.Namespace) -> HealthClient:
    from google.auth.transport.requests import AuthorizedSession

    return HealthClient(AuthorizedSession(auth.load(args.token)))


def cmd_login(args: argparse.Namespace) -> None:
    pending = args.token.with_name(args.token.name + ".pending")
    if args.redirect_url:
        auth.finish_manual_login(args.client_secret, pending, args.token, args.redirect_url)
        print(f"Saved token to {args.token}")
        return
    types = resolve(args.types)
    if args.manual:
        url = auth.start_manual_login(args.client_secret, pending, scopes_for(types))
        print("1. Open this URL, sign in and click Allow:\n")
        print(url)
        print("\n2. Your browser will land on a localhost page that doesn't load.")
        print("   Copy that page's full URL and run:")
        print("   fitbit-pull login --redirect-url '<pasted URL>'")
        return
    auth.login(args.client_secret, args.token, scopes_for(types), port=args.port)
    print(f"Saved token to {args.token}")


def cmd_types(args: argparse.Namespace) -> None:
    for key, dt in DATA_TYPES.items():
        default = "" if key in DEFAULT_TYPES else "  (opt-in)"
        print(f"{key:38} {dt.scope.rsplit('.', 2)[-2]}{default}")


def cmd_devices(args: argparse.Namespace) -> None:
    print(json.dumps(_client(args).get("users/me/pairedDevices"), indent=2))


def cmd_pull(args: argparse.Namespace) -> None:
    types = resolve(args.types)
    counts = pull(_client(args), types, args.out, args.start, args.end)
    for key, n in counts.items():
        print(f"{key:38} {n:>10,} points")


def cmd_export_csv(args: argparse.Namespace) -> None:
    for dt in resolve(args.types):
        n = export_csv(dt, args.out / "raw", args.out / "csv" / f"{dt.key}.csv")
        if n:
            print(f"{dt.key:38} {n:>10,} rows")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fitbit-pull", description="Pull your Fitbit data from the Google Health API."
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--token", type=Path, default=Path("token.json"),
                        help="cached OAuth token (default: token.json)")
    sub = parser.add_subparsers(dest="command", required=True)

    types_help = "comma-separated data types (default: all non-opt-in types)"

    p = sub.add_parser("login", help="authorize access in your browser")
    p.add_argument("--client-secret", type=Path, default=Path("client_secret.json"))
    p.add_argument("--types", type=_types_arg, help=types_help + "; sets requested scopes")
    p.add_argument("--port", type=int, default=0, help="local redirect port (default: random)")
    p.add_argument("--manual", action="store_true",
                   help="no local browser: print a URL to open elsewhere")
    p.add_argument("--redirect-url",
                   help="finish a --manual login with the localhost URL the browser landed on")
    p.set_defaults(func=cmd_login)

    p = sub.add_parser("types", help="list available data types")
    p.set_defaults(func=cmd_types)

    p = sub.add_parser("devices", help="list paired devices (quick connectivity check)")
    p.set_defaults(func=cmd_devices)

    p = sub.add_parser("pull", help="download data points to <out>/raw as JSONL")
    p.add_argument("--types", type=_types_arg, help=types_help)
    p.add_argument("--start", type=date.fromisoformat,
                   help="YYYY-MM-DD; required on first run, otherwise resumes")
    p.add_argument("--end", type=date.fromisoformat,
                   default=date.today() + timedelta(days=1),
                   help="YYYY-MM-DD, exclusive (default: tomorrow)")
    p.add_argument("--out", type=Path, default=Path("data"))
    p.set_defaults(func=cmd_pull)

    p = sub.add_parser("export-csv", help="flatten pulled JSONL into <out>/csv/<type>.csv")
    p.add_argument("--types", type=_types_arg, help=types_help)
    p.add_argument("--out", type=Path, default=Path("data"))
    p.set_defaults(func=cmd_export_csv)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(message)s",
    )
    try:
        args.func(args)
    except (ApiError, OAuth2Error, ValueError, FileNotFoundError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
