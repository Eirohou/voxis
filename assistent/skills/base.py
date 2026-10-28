"""Base tool system and schema generator for LLM function calling."""

import inspect
from typing import Any, Callable, Dict, List, Optional, get_type_hints


class Tool:
    """Represents a callable tool with an LLM function calling schema."""

    def __init__(
        self,
        func: Callable[..., Any],
        name: Optional[str] = None,
        description: Optional[str] = None,
        silent_feedback: bool = False,
    ):
        self.func = func
        self.name = name or func.__name__
        self.description = description or (func.__doc__ or "").strip()
        self.silent_feedback = silent_feedback
        self.schema = self._generate_schema()

    def _python_type_to_json_type(self, py_type: Any) -> str:
        if py_type in (int, float):
            return "number" if py_type is float else "integer"
        if py_type is bool:
            return "boolean"
        if py_type in (list, List):
            return "array"
        if py_type in (dict, Dict):
            return "object"
        return "string"

    def _generate_schema(self) -> Dict[str, Any]:
        sig = inspect.signature(self.func)
        try:
            type_hints = get_type_hints(self.func)
        except Exception:
            type_hints = {}

        properties: Dict[str, Any] = {}
        required: List[str] = []

        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls"):
                continue

            param_type = type_hints.get(param_name, str)
            json_type = self._python_type_to_json_type(param_type)

            properties[param_name] = {
                "type": json_type,
                "description": f"Parameter: {param_name}",
            }

            if param.default is inspect.Parameter.empty:
                required.append(param_name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def execute(self, **kwargs) -> Any:
        return self.func(**kwargs)

    def __call__(self, *args, **kwargs) -> Any:
        return self.func(*args, **kwargs)


class ToolRegistry:
    """Registry for managing and executing tools."""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(
        self,
        func: Optional[Callable[..., Any]] = None,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        silent_feedback: bool = False,
    ):
        def decorator(f: Callable[..., Any]) -> Tool:
            tool = Tool(
                func=f,
                name=name,
                description=description,
                silent_feedback=silent_feedback,
            )
            self._tools[tool.name] = tool
            return tool

        if func is not None:
            return decorator(func)
        return decorator

    def get_tool(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def get_schemas(self) -> List[Dict[str, Any]]:
        return [tool.schema for tool in self._tools.values()]

    def execute(self, name: str, **kwargs) -> Any:
        tool = self.get_tool(name)
        if not tool:
            return f"Error: Tool '{name}' not found."
        try:
            return tool.execute(**kwargs)
        except Exception as e:
            return f"Error executing tool '{name}': {str(e)}"

    @property
    def tools(self) -> Dict[str, Tool]:
        return self._tools


# Global default registry
default_registry = ToolRegistry()


def tool(
    func: Optional[Callable[..., Any]] = None,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    silent_feedback: bool = False,
    registry: Optional[ToolRegistry] = None,
):
    reg = registry or default_registry
    return reg.register(
        func, name=name, description=description, silent_feedback=silent_feedback
    )
