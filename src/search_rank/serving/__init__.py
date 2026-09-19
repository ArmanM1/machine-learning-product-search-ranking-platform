"""Serving submodules.

Keep this package initializer deliberately lightweight: the budget and expiry
kill-switch Lambda imports a sibling module from the same container and must
not initialize the ranking model or web stack.
"""

__all__: list[str] = []
