# Common py2exe boot script - executed for all target types.

# In the standard py2exe boot script, it setup stderr so that anything written
# to it will be written to exe.log, and a message dialog is shown.
# For Breezy, we log most things to .brz.log, and there are many things that
# write to stderr, that are not errors, and so we don't want the py2exe dialog
# message, So also blackhole stderr.

import sys

if sys.frozen == "windows_exe":

    class Blackhole:
        """A null output stream that discards all written data.

        This class provides a file-like interface that silently discards
        any data written to it. Used to suppress stdout/stderr output in
        py2exe-compiled executables to prevent unwanted dialog boxes.

        Attributes:
            softspace (int): Required for file-like compatibility, set to 0.
        """

        softspace = 0

        def write(self, text):
            """Write text to the blackhole (discards the data).

            Args:
                text (str): The text to be discarded.
            """
            pass

        def flush(self):
            """Flush the output stream (no-op for blackhole).

            This method is required for file-like compatibility but
            performs no operation since there's nothing to flush.
            """
            pass

    sys.stdout = Blackhole()
    sys.stderr = Blackhole()
    del Blackhole

# add more directories to sys.path to allow "installing" third-party libs
# required by some plugins (see bug #743256)
import os

sys.path.append(os.path.join(os.path.dirname(sys.executable), "site-packages"))
del os
del sys

# Disable linecache.getline() which is called by
# traceback.extract_stack() when an exception occurs to try and read
# the filenames embedded in the packaged python code.  This is really
# annoying on windows when the d: or e: on our build box refers to
# someone elses removable or network drive so the getline() call
# causes it to ask them to insert a disk in that drive.
import linecache


def fake_getline(filename, lineno, module_globals=None):
    """Replacement for linecache.getline that always returns empty string.

    This function replaces the standard linecache.getline to prevent
    py2exe from attempting to read source files that may be on network
    drives or removable media, which could cause unwanted prompts.

    Args:
        filename (str): The filename to read from (ignored).
        lineno (int): The line number to read (ignored).
        module_globals (dict, optional): Module globals (ignored).

    Returns:
        str: Always returns an empty string.
    """
    return ""


linecache.orig_getline = linecache.getline
linecache.getline = fake_getline

del linecache, fake_getline
