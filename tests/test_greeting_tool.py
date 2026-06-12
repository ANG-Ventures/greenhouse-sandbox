from datetime import datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "greeting_tool.py"
SPEC = spec_from_file_location("greeting_tool", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
greeting_tool = module_from_spec(SPEC)
SPEC.loader.exec_module(greeting_tool)

greeting_with_current_time = greeting_tool.greeting_with_current_time


def test_greeting_with_current_time_uses_injected_clock() -> None:
    def fixed_clock() -> datetime:
        return datetime(2026, 6, 12, 9, 7)

    assert greeting_with_current_time("Ace", clock=fixed_clock) == (
        "Hello, Ace! The current time is 09:07."
    )


def test_greeting_with_current_time_defaults_blank_name_to_friend() -> None:
    def fixed_clock() -> datetime:
        return datetime(2026, 6, 12, 23, 45)

    assert greeting_with_current_time("   ", clock=fixed_clock) == (
        "Hello, friend! The current time is 23:45."
    )
