"""Fibonacci sequence utilities."""
from __future__ import annotations


def fibonacci(n: int) -> int:
    """Return the nth Fibonacci number.

    The sequence is zero-indexed:
    `fibonacci(0) == 0`, `fibonacci(1) == 1`.
    """
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError("n must be an integer")
    if n < 0:
        raise ValueError("n must be non-negative")

    previous, current = 0, 1
    for _ in range(n):
        previous, current = current, previous + current
    return previous
