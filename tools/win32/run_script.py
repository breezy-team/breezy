# A utility that executes a script from our %PYTHON%\Scripts directory.
# Example usage:
# 'python run_script.py cog.py arg1 arg2'
# which will locate %PYTHON_HOME%/Scripts/cog.py and execute it with the args.
# This is only necessary for Windows, and only when the build process is
# executed via a cygwin/*nix based make utility, which doesn't honor the
# PATHEXT environment variable.
import sys
import os

if __name__ == '__main__':
    # clobber me, new sys.argv[0] is the script to run.
    del sys.argv[0]
    assert not os.path.isabs(sys.argv[0]), "If you know the FQ path, just use it!"
    sys.argv[0] = os.path.join(sys.prefix, "Scripts", sys.argv[0])
    exec(compile(open(sys.argv[0]).read(), sys.argv[0], 'exec'))
