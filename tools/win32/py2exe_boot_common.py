# Common py2exe boot script - executed for all target types.

# In the standard py2exe boot script, it setup stderr so that anything written
# to it will be written to exe.log, and a message dialog is shown.
# For Breezy, we log most things to .brz.log, and there are many things that
# write to stderr, that are not errors, and so we don't want the py2exe dialog
# message, So also blackhole stderr.

import sys
if sys.frozen == "windows_exe":
    class Blackhole:
        softspace = 0
        def write(self, text):
            pass
        def flush(self):
            pass
    sys.stdout = Blackhole()
    sys.stderr = Blackhole()
    del Blackhole

# add more directories to sys.path to allow "installing" third-party libs
# required by some plugins (see bug #743256)
import os
sys.path.append(os.path.join(os.path.dirname(sys.executable), 'site-packages'))
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
    return ''
linecache.orig_getline = linecache.getline
linecache.getline = fake_getline

del linecache, fake_getline
