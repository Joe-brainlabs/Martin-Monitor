"""Configuration: .env loading, paths and sources.yaml."""

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Load KEY=value lines into the environment without overriding real env vars."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv()

DATA_DIR = Path(os.getenv("DATA_DIR") or ROOT / "data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "martin.db"
UI_DIR = ROOT / "ui"
SOURCES: dict = yaml.safe_load((ROOT / "sources.yaml").read_text())

# MSE sits behind Cloudflare, which rejects bare clients but accepts a normal browser UA.
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)


def env(name: str) -> str | None:
    """Environment variable, or None when unset or blank."""
    return os.getenv(name) or None
