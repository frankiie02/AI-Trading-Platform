from dataclasses import dataclass
from logging import Logger
from typing import Any, Dict

from core.runtime.modes import RuntimeMode


@dataclass
class RuntimeContext:
    """Minimal, typed set of dependencies available to a runtime mode handler."""

    settings: Dict[str, Any]
    mode: RuntimeMode
    logger: Logger
