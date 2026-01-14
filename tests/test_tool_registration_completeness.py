import importlib
import pkgutil
from types import ModuleType
from typing import Callable, Iterable, Set


def _iter_mcp_wrapped_callables(module: ModuleType) -> Iterable[Callable]:
    for _, value in vars(module).items():
        if callable(value) and getattr(value, "__mcp_tool__", None) is not None:
            yield value


def _import_all_submodules(package_name: str) -> list[ModuleType]:
    package = importlib.import_module(package_name)
    modules: list[ModuleType] = [package]
    pkg_path = getattr(package, "__path__", None)
    if pkg_path is None:
        return modules

    for info in pkgutil.iter_modules(pkg_path):
        full_name = f"{package_name}.{info.name}"
        modules.append(importlib.import_module(full_name))
    return modules


def test_all_mcp_wrapped_tools_are_registered() -> None:
    # Importing main is the canonical bootstrap for tool registration.
    import main  # noqa: F401

    from github_mcp.server import _REGISTERED_MCP_TOOLS

    registered_names: Set[str] = set()
    for tool_obj, func in _REGISTERED_MCP_TOOLS:
        name = getattr(tool_obj, "name", None) or getattr(func, "__name__", None)
        if name:
            registered_names.add(str(name))

    assert registered_names, "Expected at least one registered tool."

    # Collect every callable decorated with @mcp_tool across modules that define tools.
    expected_names: Set[str] = set()

    # Root entrypoint tools.
    expected_names.update(
        {f.__name__ for f in _iter_mcp_wrapped_callables(importlib.import_module("main"))}
    )

    # Workspace tool modules.
    for mod in _import_all_submodules("github_mcp.workspace_tools"):
        expected_names.update({f.__name__ for f in _iter_mcp_wrapped_callables(mod)})

    # Extra tools are optional, but when present they should also be registered.
    try:
        extra = importlib.import_module("extra_tools")
    except Exception:
        extra = None
    if extra is not None:
        expected_names.update({f.__name__ for f in _iter_mcp_wrapped_callables(extra)})

    missing = sorted(expected_names - registered_names)
    assert not missing, f"Tools decorated with @mcp_tool were not registered: {missing}"


def test_registered_tools_have_write_action_flag() -> None:
    import main  # noqa: F401

    from github_mcp.server import _REGISTERED_MCP_TOOLS

    missing_flag = []
    for tool_obj, func in _REGISTERED_MCP_TOOLS:
        name = getattr(tool_obj, "name", None) or getattr(func, "__name__", None)
        if not name:
            continue
        # The decorator stamps this onto the wrapper; the FastMCP tool object also may have it.
        flag = getattr(func, "__mcp_write_action__", None)
        if flag is None:
            flag = getattr(tool_obj, "write_action", None)
        if flag is None:
            missing_flag.append(str(name))

    assert not missing_flag, (
        "Registered tools missing write_action classification: " + str(sorted(missing_flag))
    )
