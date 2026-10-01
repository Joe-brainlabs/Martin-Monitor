"""The source registry: one entry per poller, with its config block and the keys it needs."""

from dataclasses import dataclass
from typing import Callable

from ..config import SOURCES, env
from ..brian import views as brian_views
from . import instagram, mse_forum, mse_guides, mse_news, press, reddit, trends, x, youtube


@dataclass
class Spec:
    label: str
    fetch: Callable
    cfg: dict
    every_minutes: int
    needs: tuple[str, ...] = ()

    @property
    def missing(self) -> list[str]:
        return [name for name in self.needs if not env(name)]

    @property
    def enabled(self) -> bool:
        return not self.missing

    @property
    def reason(self) -> str:
        return f"missing {', '.join(self.missing)}" if self.missing else "ok"


def _spec(key: str, module, needs: tuple[str, ...] = (), label: str | None = None) -> Spec:
    cfg = SOURCES[key]
    return Spec(label or cfg.get("label", key), module.fetch, cfg, cfg["every_minutes"], needs)


REGISTRY: dict[str, Spec] = {
    "x": _spec("x", x, ("BEARER_TOKEN",), label="X"),
    "instagram": _spec("instagram", instagram, ("ENSEMBLE_TOKEN",)),
    "mse_news": _spec("mse_news", mse_news),
    "mse_forum": _spec("mse_forum", mse_forum),
    "press": _spec("press", press),
    "reddit": _spec("reddit", reddit, ("ENSEMBLE_TOKEN",)),
    "youtube": _spec("youtube", youtube, ("YOUTUBE_API_KEY",)),
    "trends": _spec("trends", trends, ("DECODO_USERNAME", "DECODO_PASSWORD")),
    "mse_guides": _spec("mse_guides", mse_guides),
    "brian": _spec("brian", brian_views, ("ANTHROPIC_API_KEY",)),
}

# Items from the X poller are stored per handle (x_martinslewis, x_moneysavingexp); the UI needs labels for those.
ITEM_SOURCE_LABELS: dict[str, str] = {
    **{f"x_{a['handle'].lower()}": a["label"] for a in SOURCES["x"]["handles"]},
    **{name: spec.label for name, spec in REGISTRY.items() if name not in ("x", "brian")},
}
