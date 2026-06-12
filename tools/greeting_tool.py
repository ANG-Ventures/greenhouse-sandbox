"""Small PoC greeting tool that includes the current local time.

No network calls. The clock can be injected in tests so the behavior is
predictable without freezing global time.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

Clock = Callable[[], datetime]


def greeting_with_current_time(name: str = "friend", *, clock: Clock | None = None) -> str:
    """Return a friendly greeting with the current local time.

    Args:
        name: Person to greet. Blank names fall back to "friend".
        clock: Optional datetime supplier for tests or demos.
    """
    clean_name = name.strip() or "friend"
    now = (clock or datetime.now)()
    return f"Hello, {clean_name}! The current time is {now:%H:%M}."


def main() -> None:
    """CLI entry point for a quick manual demo."""
    print(greeting_with_current_time())


if __name__ == "__main__":
    main()
