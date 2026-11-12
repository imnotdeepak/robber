"""Run the advisor page on this computer: python -m catan_ai.cli.advisor

Open http://127.0.0.1:8765, start a table, record what happens and ask for
advice. The table is saved to runs/advisor/table.json after every change and
resumed on restart (pass --fresh to start over).
"""

import argparse

from catan_ai.advisor.server import Session, serve
from catan_ai.advisor.suggest import DEFAULT_BUDGET, DEFAULT_CHECKPOINT, Advisor
from catan_ai.provenance import REPO_ROOT


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--checkpoint", default=DEFAULT_CHECKPOINT)
    parser.add_argument("--budget", default=DEFAULT_BUDGET, help="search budget, e.g. 8t16")
    parser.add_argument("--save", default=str(REPO_ROOT / "runs" / "advisor" / "table.json"))
    parser.add_argument("--fresh", action="store_true", help="ignore the saved table")
    args = parser.parse_args()

    from pathlib import Path

    save = Path(args.save)
    if args.fresh and save.exists():
        save.rename(save.with_suffix(".previous.json"))
    session = Session(save, Advisor(args.checkpoint, args.budget, seed="advisor"))
    server = serve(session, args.port)
    print(f"Robber advisor on http://127.0.0.1:{args.port} (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
