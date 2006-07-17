# (c) Canonical Ltd, 2006
# written by Alexander Belchenko for bzr project
#
# This script will be executed after installation of bzrlib package
# and before installer exits.
# All printed data will appear on the last screen of installation
# procedure.
# The main goal of this script is to create special batch file
# launcher for bzr. Typical content of this batch file is:
#  @python bzr %*
#
# This file works only on Windows 2000/XP. For win98 there is
# should be "%1 %2 %3 %4 %5 %6 %7 %8 %9" instead of "%*".
# Or even more complex thing.
#
# [bialix]: bzr de-facto does not support win98.
#           Although it seems to work on. Sometimes.

import os
import sys

if len(sys.argv) == 2 and sys.argv[1] == "-install":
    # try to detect version number automatically
    try:
        import bzrlib
    except ImportError:
        ver = ''
    else:
        ver = bzrlib.__version__

    ##
    # XXX change message for something more appropriate
    print """Bazaar-NG %s

Congratulation! Bzr successfully installed.

""" % ver

    batch_path = "bzr.bat"
    prefix = sys.prefix
    try:
        ##
        # try to create
        scripts_dir = os.path.join(prefix, "Scripts")
        script_path = os.path.join(scripts_dir, "bzr")
        python_path = os.path.join(prefix, "python.exe")
        batch_str = "@%s %s %%*\n" % (python_path, script_path)
        batch_path = script_path + ".bat"
        f = file(batch_path, "w")
        f.write(batch_str)
        f.close()
        file_created(batch_path)        # registering manually created files for
                                        # auto-deinstallation procedure
        ##
        # inform user where batch launcher is.
        print "Created:", batch_path
        print "Use this batch file to run bzr"
    except Exception, e:
        print "ERROR: Unable to create %s: %s" % (batch_path, e)
