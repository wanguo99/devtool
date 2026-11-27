"""Launch internal helpers from source or the self-contained executable."""
from __future__ import annotations

import os
import sys
import subprocess


def frozen():
    return bool(getattr(sys, "frozen", False))


def helper_command(module):
    if frozen():
        return (sys.executable, "_internal", module)
    return (sys.executable, "-m", "devtool_core." + module)


def external_environment(environment=None, *, executable=None):
    """Do not expose the bundled Python libraries to system commands.

    A one-file executable temporarily changes LD_LIBRARY_PATH for its runtime.
    Programs such as git, ssh and docker must use their own system libraries.
    An independent invocation of this executable gets its own extraction.
    """
    result = dict(os.environ if environment is None else environment)
    if frozen():
        original = result.pop("LD_LIBRARY_PATH_ORIG", None)
        if original is None:
            result.pop("LD_LIBRARY_PATH", None)
        else:
            result["LD_LIBRARY_PATH"] = original
        if executable and os.path.realpath(executable) == os.path.realpath(sys.executable):
            result["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return result


def run_checked(argv, **kwargs):
    kwargs["env"] = external_environment(kwargs.get("env"), executable=argv[0])
    return subprocess.run(argv, check=True, **kwargs)
