"""
Test isolation: every test run gets its own throw-away SQLite file, so tests never write into the
developer's backend/jarvis.db (and data from earlier runs never slows down or skews later runs).
Imported by tests/__init__.py, helpers.py and auth_helpers.py before any database connection.
An explicit JARVIS_SQLITE_PATH is respected. Never run the suite with a production DATABASE_URL.
"""
import atexit
import os
import shutil
import tempfile

if not os.environ.get("JARVIS_SQLITE_PATH"):
    _TMP_DIR = tempfile.mkdtemp(prefix="jarvis-tests-")
    os.environ["JARVIS_SQLITE_PATH"] = os.path.join(_TMP_DIR, "jarvis-test.db")
    atexit.register(shutil.rmtree, _TMP_DIR, ignore_errors=True)
