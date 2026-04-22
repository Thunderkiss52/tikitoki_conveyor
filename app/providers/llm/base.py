from typing import Any, Protocol

from app.models.pipeline import ScriptPackage


class ScriptProvider(Protocol):
    def generate_script(self, context: dict[str, Any]) -> ScriptPackage:
        ...
