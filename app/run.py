"""Run one source (or all) once from the command line: python -m app.run mse_news"""

import json
import logging
import sys

from . import db
from .scheduler import run_source
from .sources import REGISTRY


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    db.init()
    names = sys.argv[1:] or ["all"]
    if names == ["all"]:
        names = [n for n, s in REGISTRY.items() if s.enabled]
    for name in names:
        if name not in REGISTRY:
            sys.exit(f"Unknown source {name!r}. Known: {', '.join(REGISTRY)}")
        if not REGISTRY[name].enabled:
            print(f"{name}: skipped ({REGISTRY[name].reason})")
            continue
        print(json.dumps(run_source(name)))


if __name__ == "__main__":
    main()
