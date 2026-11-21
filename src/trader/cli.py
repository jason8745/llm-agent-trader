import argparse

from trader import __version__


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="llm-agent-trader")
    parser.add_argument("--version", action="version", version=__version__)
    parser.parse_args(argv)


if __name__ == "__main__":
    main()
