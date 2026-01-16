from __future__ import annotations


def test_tool_descriptions_are_well_formed() -> None:
    """Enforce basic description style for tool catalog output."""

    import main  # noqa: F401

    catalog = main.list_all_actions(include_parameters=False, compact=False)
    tools = list(catalog.get("tools", []))
    assert tools, "Expected at least one tool in the registry."

    issues: list[str] = []
    for tool in tools:
        name = tool.get("name") or "<unknown>"
        desc = (tool.get("description") or "").strip()
        if not desc:
            issues.append(f"{name}: missing description")
            continue

        first_line = desc.splitlines()[0].strip()
        if not first_line:
            issues.append(f"{name}: empty first line")
            continue

        ch0 = first_line[0]
        if "a" <= ch0 <= "z":
            issues.append(f"{name}: first line should start with a capital letter")

        if first_line[-1] not in (".", "!", "?", ":"):
            issues.append(f"{name}: first line should end with terminal punctuation")

    assert not issues, "Tool descriptions need updates:\n" + "\n".join(issues)

