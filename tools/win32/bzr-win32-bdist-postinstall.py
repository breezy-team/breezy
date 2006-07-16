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
import _winreg


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

    # make entry in APPDATA
    appdata = get_special_folder_path("CSIDL_APPDATA")
    dst = os.path.join(appdata, "bazaar", "2.0")
    if not os.path.isdir(dst):
        os.makedirs(dst)
        import locale
        print "Configuration files stored in %s" % \
              dst.encode(locale.getpreferredencoding(), 'replace')
        # create dummy bazaar.conf
        f = file(os.path.join(dst,'bazaar.conf'), 'w')
        f.write("# main configuration file of Bazaar-NG\n"
                "[DEFAULT]\n"
                "#email=Your Name <you@domain.com>\n")
        f.close()

    ## this hunk borrowed from pywin32_postinstall.py
    # use bdist_wininst builtins to create a shortcut.
    # CSIDL_COMMON_PROGRAMS only available works on NT/2000/XP, and
    # will fail there if the user has no admin rights.
    if get_root_hkey()==_winreg.HKEY_LOCAL_MACHINE:
        try:
            fldr = get_special_folder_path("CSIDL_COMMON_PROGRAMS")
        except OSError:
            # No CSIDL_COMMON_PROGRAMS on this platform
            fldr = get_special_folder_path("CSIDL_PROGRAMS")
    else:
        # non-admin install - always goes in this user's start menu.
        fldr = get_special_folder_path("CSIDL_PROGRAMS")

    # make Bazaar-NG entry
    fldr = os.path.join(fldr, 'Bazaar-NG')
    if not os.path.isdir(fldr):
        os.mkdir(fldr)
        directory_created(fldr)

    # link to documentation
    docs = os.path.join(sys.exec_prefix, 'Doc', 'Bazaar-NG', 'index.htm')
    dst = os.path.join(fldr, 'Documentation.lnk')
    create_shortcut(docs, 'Bazaar-NG Documentation', dst)
    file_created(dst)
    print 'Documentation for Bazaar-NG: Start => Programs => Bazaar-NG'

    # bzr in cmd shell
    cmd = os.environ.get('COMSPEC', 'cmd.exe')
    dst = os.path.join(fldr, 'Start bzr.lnk')
    create_shortcut(cmd,
                    'Start bzr in cmd shell',
                    dst,
                    "/K bzr help",
                    os.path.join(sys.exec_prefix, 'Scripts'))
    file_created(dst)
