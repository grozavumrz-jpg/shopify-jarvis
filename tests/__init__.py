"""
Shopify Jarvis Comprehensive E2E Test Suite
Tiers 1-4 Test Infrastructure
"""
try:
    from tests import _test_env  # noqa: F401  (isolated SQLite file per test run)
except ImportError:  # pragma: no cover
    import _test_env  # noqa: F401
