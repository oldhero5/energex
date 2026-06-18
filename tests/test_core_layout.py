"""Both the legacy import paths and the new energex.core paths must resolve to
the SAME objects after the move, so the 122 pre-S1 tests keep importing the old
paths while new code imports energex.core.*."""


def test_exceptions_old_and_new_paths_are_identical():
    from energex.core.exceptions import EnergexError as New
    from energex.exceptions import EnergexError as Old

    assert Old is New


def test_logging_config_old_and_new_paths_are_identical():
    from energex.core.logging_config import setup_logging as new
    from energex.logging_config import setup_logging as old

    assert old is new


def test_rate_limiter_old_and_new_paths_are_identical():
    from energex.core.rate_limiter import RateLimiter as New
    from energex.rate_limiter import RateLimiter as Old

    assert Old is New
