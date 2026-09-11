"""Validate model arguments and enforce tool permissions before execution."""

from dataclasses import dataclass
from collections.abc import Callable
from copy import deepcopy


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Callable[..., object]
    permission: str = "safe"
    preview: Callable[..., dict] | None = None


class ToolRegistry:
    def __init__(self, tools: list[Tool], confirm: Callable[[str, dict], bool] | None = None):
        self._tools = {tool.name: tool for tool in tools}
        if len(self._tools) != len(tools):
            raise ValueError("Duplicate tool names")
        self._confirm = confirm

    @property
    def schemas(self) -> list[dict]:
        return [{"type": "function", "function": {
            "name": tool.name, "description": tool.description,
            "parameters": deepcopy(tool.parameters),
        }} for tool in self._tools.values()]

    @property
    def tools(self) -> tuple[Tool, ...]:
        return tuple(self._tools.values())

    def execute(self, name: str, arguments: object) -> dict:
        tool = self._tools.get(name)
        if tool is None:
            return {"ok": False, "error": "Unknown tool"}
        if not isinstance(arguments, dict):
            return {"ok": False, "error": "Arguments must be an object"}
        properties = tool.parameters.get("properties", {})
        if set(arguments) - set(properties) or any(
            key not in arguments for key in tool.parameters.get("required", [])
        ):
            return {"ok": False, "error": "Missing or unexpected arguments"}
        for key, value in arguments.items():
            if not isinstance(value, str) or not value.strip():
                return {"ok": False, "error": f"{key} must be a nonempty string"}
            if "enum" in properties[key] and value not in properties[key]["enum"]:
                return {"ok": False, "error": f"Unsupported {key}"}
        try:
            if tool.permission != "safe":
                if tool.permission not in {"confirm", "dangerous"} or self._confirm is None:
                    return {"ok": False, "error": "Permission denied"}
                details = tool.preview(**arguments) if tool.preview else deepcopy(arguments)
                if not self._confirm(name, details):
                    return {"ok": False, "error": "Permission denied"}
            return {"ok": True, "result": tool.handler(**arguments)}
        except (OSError, ValueError, RuntimeError) as error:
            return {"ok": False, "error": str(error)}
