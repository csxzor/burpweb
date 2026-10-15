"""burpweb command line: browse a Burp Suite HTTP history export offline."""

from __future__ import annotations

import argparse
import asyncio
import collections
import signal
import sys
from pathlib import Path

from burpweb.addon import Replay
from burpweb.burp_xml import BurpXmlError, LoadResult, load_many
from burpweb.matcher import Matcher


EXPORTS_HELP = "Burp XML from Proxy > HTTP history > Save items; several files are combined, later ones win"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="burpweb", description="Browse a Burp Suite HTTP history export offline.")
    sub = parser.add_subparsers(dest="command")
    parser.set_defaults(command="ui", port=8765, no_open=False)  # a bare `burpweb` opens the control page

    ui = sub.add_parser("ui", help="open the control page in a browser (default)")
    ui.add_argument("--port", type=int, default=8765, help="control page port (default: %(default)s)")
    ui.add_argument("--no-open", action="store_true", help="print the URL instead of opening a browser")

    serve = sub.add_parser("serve", help="run the replay proxy")
    serve.add_argument("exports", type=Path, nargs="+", help=EXPORTS_HELP)
    serve.add_argument("--port", type=int, default=8081, help="proxy port (default: %(default)s)")
    serve.add_argument("--browser", action="store_true", help="open a Firefox profile preconfigured for the proxy")
    serve.add_argument(
        "--confdir",
        type=Path,
        default=Path("~/.mitmproxy"),
        help="mitmproxy config and CA directory (default: %(default)s)",
    )

    show = sub.add_parser("list", help="show the captured origins")
    show.add_argument("exports", type=Path, nargs="+", help=EXPORTS_HELP)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "ui":
        from burpweb.webapp import run

        try:
            run(port=args.port, open_browser=not args.no_open)
        except KeyboardInterrupt:
            pass
        return 0
    try:
        result = load_many(args.exports)
    except BurpXmlError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if not result.records:
        print(
            f"error: no usable items in {', '.join(map(str, args.exports))}. Export with Proxy > HTTP history > "
            "select items > Save items, and make sure the items have responses.",
            file=sys.stderr,
        )
        return 1
    print(load_summary(result, files=len(args.exports)), flush=True)
    if args.command == "list":
        print(format_hosts(result))
        return 0
    return serve(result, port=args.port, confdir=args.confdir.expanduser().resolve(), browser=args.browser)


def load_summary(result: LoadResult, files: int = 1) -> str:
    origins = {r.origin for r in result.records}
    from_files = f" from {files} files" if files > 1 else ""
    lines = [
        f"Loaded {len(result.records)} items across {len(origins)} origin(s){from_files}; "
        f"skipped {result.skipped_no_response} without a replayable response, {len(result.malformed)} malformed."
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
    # lazy + no upstream cert + no raw TCP: mitmproxy has no reason to open a connection to the real
    # server; Replay.server_connect refuses any that it still attempts.
    master.options.update(
        connection_strategy="lazy", upstream_cert=False, http3=False, rawtcp=False, termlog_verbosity="warn"
    )
    master.addons.add(*addons)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, master.shutdown)
    await master.run()
