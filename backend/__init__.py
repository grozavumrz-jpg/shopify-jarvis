"""
Makes `backend.<module>` and `<module>` resolve to the SAME module object.

Production runs from inside backend/ (`python main.py`), so modules import each
other by bare name (`import database as db`). Some tests import them as
`backend.<module>`. Without this shim Python would load two separate copies of
each module (e.g. `database` and `backend.database`), so a patch applied to one
copy silently misses the code that uses the other — which made tests fail
depending on the order they ran in.
"""
import importlib
import importlib.abc
import importlib.util
import os
import sys

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


class _BackendAliasFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    _PREFIX = __name__ + "."

    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(self._PREFIX) and fullname.count(".") == 1:
            bare = fullname[len(self._PREFIX):]
            if os.path.exists(os.path.join(_BACKEND_DIR, bare + ".py")):
                return importlib.util.spec_from_loader(fullname, self)
        return None

    def create_module(self, spec):
        return importlib.import_module(spec.name[len(self._PREFIX):])

    def exec_module(self, module):
        # Already executed under its bare name.
        pass


if not any(isinstance(f, _BackendAliasFinder) for f in sys.meta_path):
    sys.meta_path.insert(0, _BackendAliasFinder())
