"""The import rules that keep the three packages separable.

`core` is what the Telegram bot and the admin panel have in common. If
something in it imports `telegram`, the panel is dragging a Telegram library
into its process in order to read a question; if it imports `flask`, the bot is
carrying a web framework around. Either way the two front ends have quietly
stopped being independent, and whoever notices will be the person who tried to
change one and broke the other.

Checked here rather than left to memory, because this is exactly the kind of
rule that one reasonable-looking import undoes.
"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Everything `core` is meant to be free of: both front ends, their frameworks,
# and the sample data, which is a fixture rather than part of the product.
FORBIDDEN_IN_CORE = {"telegram", "flask", "bot", "admin", "samples"}


def _top_level_imports(path):
    """Every top-level package this module imports, by name."""
    tree = ast.parse(path.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module.split(".")[0]


def _offences(package, forbidden):
    found = []

    for path in (ROOT / package).rglob("*.py"):
        for module in _top_level_imports(path):
            if module in forbidden:
                found.append(f"{path.relative_to(ROOT).as_posix()} imports {module}")

    return sorted(found)


def test_core_knows_nothing_about_either_front_end():
    assert _offences("core", FORBIDDEN_IN_CORE) == []


def test_the_admin_panel_does_not_import_the_bot():
    """The panel used to reach into `bot.services` for everything, which is why
    a Flask process ended up importing python-telegram-bot."""
    assert _offences("admin", {"bot", "telegram"}) == []


def test_the_bot_does_not_import_the_admin_panel():
    assert _offences("bot", {"admin", "flask"}) == []


def test_the_rules_are_actually_being_applied_to_something():
    """A canary. If `core` were empty or the glob stopped matching, every
    assertion above would pass by saying nothing."""
    modules = list((ROOT / "core").rglob("*.py"))

    assert len(modules) >= 10
    assert any("models.py" in path.name for path in modules)
