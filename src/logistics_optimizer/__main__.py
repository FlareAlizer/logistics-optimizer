"""python -m logistics_optimizer: без аргументов открывает окно, с аргументами считает в консоли."""

import sys


def main() -> int:
    if len(sys.argv) > 1:
        from .cli import main as run_cli

        return run_cli()
    from .ui.app import main as run_gui

    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
