"""Command-line interface for meta-repo."""

import argparse
from pathlib import Path
import sys

from . import __version__
from .processor import ProcessingError, process_repository


def main() -> int:
    parser = argparse.ArgumentParser(prog="meta-repo", description="Render a repository containing embedded Python.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("source", type=Path, help="source repository directory")
    parser.add_argument("destination", type=Path, help="new output repository directory")
    order = parser.add_mutually_exclusive_group()
    order.add_argument("--ascending", action="store_true", dest="ascending", help="lower priorities first (default)")
    order.add_argument("--descending", action="store_false", dest="ascending", help="higher priorities first")
    parser.set_defaults(ascending=True)
    args = parser.parse_args()
    try:
        process_repository(args.source, args.destination, ascending=args.ascending)
    except (ProcessingError, OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(f"Created: {args.destination.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
