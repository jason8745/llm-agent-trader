import argparse
import json
import sys

from trader import __version__, fmt, runner, store


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="llm-agent-trader")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("mcp", help="run the MCP server on stdio")

    bt = sub.add_parser("backtest", help="backtest a strategy file")
    bt.add_argument("strategy")
    bt.add_argument("symbol")
    bt.add_argument("start")
    bt.add_argument("end")
    bt.add_argument("--hypothesis", required=True)
    bt.add_argument("--params", type=json.loads, default=None, help="JSON, e.g. '{\"fast\": 5}'")
    bt.add_argument("--cash", type=float, default=runner.DEFAULT_CASH)

    show = sub.add_parser("show", help="print one run")
    show.add_argument("run_id", type=int)
    sub.add_parser("runs", help="list runs in this workspace")
    search = sub.add_parser("search", help="find a Taiwan stock or ETF")
    search.add_argument("query")

    args = parser.parse_args(argv)
    from trader.mcp_server import VIEWER_PORT

    ws = runner.workspace()
    if args.cmd == "mcp":
        from trader.mcp_server import main as serve

        serve()
    elif args.cmd == "backtest":
        try:
            run = runner.run_backtest(
                ws,
                args.strategy,
                args.symbol,
                args.start,
                args.end,
                args.hypothesis,
                params=args.params,
                cash=args.cash,
            )
        except runner.RunError as e:
            sys.exit(f"backtest failed: {e}")
        print(fmt.run_text(run, VIEWER_PORT))
    elif args.cmd == "show":
        run = store.get(ws, args.run_id)
        if run is None:
            sys.exit(f"no run #{args.run_id}")
        print(fmt.run_text(run, VIEWER_PORT))
    elif args.cmd == "runs":
        print(fmt.runs_markdown(store.list_runs(ws)))
    elif args.cmd == "search":
        from trader.mcp_server import search_stock

        print(search_stock(args.query))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
