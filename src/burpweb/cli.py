"""burpweb command line: browse a Burp Suite HTTP history export offline."""

from __future__ import annotations

import argparse
import asyncio
import collections
import signal
import sys
from pathlib import Path

from burpweb.addon import Replay
from burpweb.burp_xml import BurpXmlError, LoadResult, load
from burpweb.matcher import Matcher


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="burpweb", description="Browse a Burp Suite HTTP history export offline.")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the replay proxy")
    serve.add_argument("export", type=Path, help="Burp XML from Proxy > HTTP history > Save items")
    serve.add_argument("--port", type=int, default=8081, help="proxy port (default: %(default)s)")
    serve.add_argument("--browser", action="store_true", help="open a Firefox profile preconfigured for the proxy")
    serve.add_argument(
        "--confdir",
        type=Path,
        default=Path("~/.mitmproxy"),
        help="mitmproxy config and CA directory (default: %(default)s)",
    )

    show = sub.add_parser("list", help="show the captured origins")
    show.add_argument("export", type=Path, help="Burp XML from Proxy > HTTP history > Save items")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = load(args.export)
    except BurpXmlError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if not result.records:
        print(
            f"error: no usable items in {args.export}. Export with Proxy > HTTP history > "
            "select items > Save items, and make sure the items have responses.",
            file=sys.stderr,
        )
        return 1
    print(load_summary(result), flush=True)
    if args.command == "list":
        print(format_hosts(result))
        return 0
    return serve(result, port=args.port, confdir=args.confdir.expanduser().resolve(), browser=args.browser)


def load_summary(result: LoadResult) -> str:
    origins = {r.origin for r in result.records}
    lines = [
        f"Loaded {len(result.records)} items across {len(origins)} origin(s); "
        f"skipped {result.skipped_no_response} without a response, {len(result.malformed)} malformed."
    ]
    lines += [f"  malformed item #{index}: {reason}" for index, reason in result.malformed]
    return "\n".join(lines)


def format_hosts(result: LoadResult) -> str:
    counts: collections.Counter[str] = collections.Counter()
    paths: dict[str, set[str]] = collections.defaultdict(set)
    for rec in result.records:
        counts[rec.origin] += 1
        paths[rec.origin].add(rec.path)
    lines = [f"{'ITEMS':>6} {'PATHS':>6}  ORIGIN"]
    lines += [f"{n:>6} {len(paths[origin]):>6}  {origin}" for origin, n in counts.most_common()]
    return "\n".join(lines)


def serve(result: LoadResult, *, port: int, confdir: Path, browser: bool) -> int:
    addons: list = [Replay(Matcher(result.records))]
    if browser:
        from burpweb.browser import FirefoxLauncher

        addons.append(FirefoxLauncher(port=port, confdir=confdir, start_url=result.records[0].url))
    print(
        f"Replay proxy on http://127.0.0.1:{port}  (CA: {confdir / 'mitmproxy-ca-cert.pem'})  Ctrl-C to stop.",
        flush=True,
    )
    try:
        asyncio.run(run_proxy(addons, port=port, confdir=confdir))
    except SystemExit as e:  # mitmproxy exits like this when startup fails, e.g. port in use
        if e.code:
            print(f"error: the proxy failed to start (see above). If port {port} is busy, pick another with --port.", file=sys.stderr)
            return 1
    return 0


async def run_proxy(addons: list, *, port: int, confdir: Path) -> None:
    from mitmproxy.options import Options
    from mitmproxy.tools.dump import DumpMaster

    master = DumpMaster(
        Options(listen_host="127.0.0.1", listen_port=port, confdir=str(confdir)),
        with_termlog=True,
        with_dumper=False,
    )
    # lazy + no upstream cert: mitmproxy never opens a connection to the real server.
    master.options.update(connection_strategy="lazy", upstream_cert=False, http3=False, termlog_verbosity="warn")
    master.addons.add(*addons)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, master.shutdown)
    await master.run()
