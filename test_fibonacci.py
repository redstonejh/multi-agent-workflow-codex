import pytest

from fibonacci import fibonacci


@pytest.mark.parametrize(
    ("n", "expected"),
    [
        (0, 0),
        (1, 1),
        (2, 1),
        (3, 2),
        (4, 3),
        (5, 5),
        (6, 8),
        (7, 13),
        (10, 55),
        (20, 6765),
    ],
)
def test_fibonacci_sequence_values(n, expected):
    assert fibonacci(n) == expected


def test_fibonacci_rejects_negative_input():
    with pytest.raises(ValueError, match="non-negative"):
        fibonacci(-1)


@pytest.mark.parametrize("value", [1.5, "8", None, True])
def test_fibonacci_rejects_non_integer_input(value):
    with pytest.raises(TypeError, match="integer"):
        fibonacci(value)
