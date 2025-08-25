r"""Windows script runner utility.

A utility that executes a script from the %PYTHON%\Scripts directory.
This is only necessary for Windows, and only when the build process is
executed via a cygwin/*nix based make utility, which doesn't honor the
PATHEXT environment variable.

Example usage:
    python run_script.py cog.py arg1 arg2

This will locate %PYTHON_HOME%/Scripts/cog.py and execute it with the args.
"""

import os
import sys

if __name__ == "__main__":
    """Execute a script from the Python Scripts directory.
    
    This main block modifies sys.argv to point to the full path of a script
    in the Python Scripts directory, then executes that script.
    
    Raises:
        AssertionError: If the first argument is already an absolute path.
    """
    # clobber me, new sys.argv[0] is the script to run.
    del sys.argv[0]
    if os.path.isabs(sys.argv[0]):
        raise AssertionError("If you know the FQ path, just use it!")
    sys.argv[0] = os.path.join(sys.prefix, "Scripts", sys.argv[0])
    exec(compile(open(sys.argv[0]).read(), sys.argv[0], "exec"))  # noqa: S102
