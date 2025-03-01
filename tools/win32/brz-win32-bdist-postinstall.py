# (c) Canonical Ltd, 2006
# written by Alexander Belchenko for brz project
#
# This script will be executed after installation of breezy package
# and before installer exits.
# All printed data will appear on the last screen of installation
# procedure.
# The main goal of this script is to create special batch file
# launcher for brz. Typical content of this batch file is:
#  @python brz %*
#
# This file works only on Windows 2000/XP. For win98 there is
# should be "%1 %2 %3 %4 %5 %6 %7 %8 %9" instead of "%*".
# Or even more complex thing.
#
# [bialix]: brz de-facto does not support win98.
#           Although it seems to work on. Sometimes.
# 2006/07/30    added minimal support of win98.
# 2007/01/30    added *real* support of win98.

import os
import sys

import _winreg

from breezy import win32utils


def _quoted_path(path):
    if " " in path:
        return '"' + path + '"'
    else:
        return path


def _win_batch_args():
    if win32utils.winver == "Windows NT":
        return "%*"
    else:
        return "%1 %2 %3 %4 %5 %6 %7 %8 %9"


if "-install" in sys.argv[1:]:
    # try to detect version number automatically
    try:
        import breezy
    except ImportError:
        ver = ""
    else:
        ver = breezy.__version__

    ##
    # XXX change message for something more appropriate
    print(
        """Breezy {}

Congratulation! Brz successfully installed.

""".format(ver)
    )

    batch_path = "brz.bat"
    prefix = sys.exec_prefix
    try:
        ##
        # try to create
        scripts_dir = os.path.join(prefix, "Scripts")
        script_path = _quoted_path(os.path.join(scripts_dir, "brz"))
        python_path = _quoted_path(os.path.join(prefix, "python.exe"))
        args = _win_batch_args()
        batch_str = "@{} {} {}".format(python_path, script_path, args)
        # support of win98
        # if there is no HOME for brz then set it for Breezy manually
        base = os.environ.get("brz_HOME", None)
        if base is None:
            base = win32utils.get_appdata_location()
        if base is None:
            base = os.environ.get("HOME", None)
        if base is None:
            base = os.path.splitdrive(sys.prefix)[0] + "\\"
            batch_str = "@SET brz_HOME=" + _quoted_path(base) + "\n" + batch_str

        batch_path = os.path.join(scripts_dir, "brz.bat")
        with open(batch_path, "w") as f:
            f.write(batch_str)
        # registering manually created files for auto-deinstallation procedure
        file_created(batch_path)
        ##
        # inform user where batch launcher is.
        print("Created:", batch_path)
        print("Use this batch file to run brz")
    except Exception as e:
        print("ERROR: Unable to create {}: {}".format(batch_path, e))

    ## this hunk borrowed from pywin32_postinstall.py
    # use bdist_wininst builtins to create a shortcut.
    # CSIDL_COMMON_PROGRAMS only available works on NT/2000/XP, and
    # will fail there if the user has no admin rights.
    if get_root_hkey() == _winreg.HKEY_LOCAL_MACHINE:
        try:
            fldr = get_special_folder_path("CSIDL_COMMON_PROGRAMS")
        except OSError:
            # No CSIDL_COMMON_PROGRAMS on this platform
            fldr = get_special_folder_path("CSIDL_PROGRAMS")
    else:
        # non-admin install - always goes in this user's start menu.
        fldr = get_special_folder_path("CSIDL_PROGRAMS")

    # make Breezy entry
    fldr = os.path.join(fldr, "Breezy")
    if not os.path.isdir(fldr):
        os.mkdir(fldr)
        directory_created(fldr)

    # link to documentation
    docs = os.path.join(sys.exec_prefix, "Doc", "Breezy", "index.html")
    dst = os.path.join(fldr, "Documentation.lnk")
    create_shortcut(docs, "Breezy Documentation", dst)
    file_created(dst)
    print("Documentation for Breezy: Start => Programs => Breezy")

    # brz in cmd shell
    if os.name == "nt":
        cmd = os.environ.get("COMSPEC", "cmd.exe")
        args = "/K brz help"
    else:
        # minimal support of win98
        cmd = os.environ.get("COMSPEC", "command.com")
        args = "brz help"
    dst = os.path.join(fldr, "Start brz.lnk")
    create_shortcut(
        cmd,
        "Start brz in cmd shell",
        dst,
        args,
        os.path.join(sys.exec_prefix, "Scripts"),
    )
    file_created(dst)

    # uninstall shortcut
    uninst = os.path.join(sys.exec_prefix, "Removebrz.exe")
    dst = os.path.join(fldr, "Uninstall Breezy.lnk")
    create_shortcut(
        uninst,
        "Uninstall Breezy",
        dst,
        "-u brz-wininst.log",
        sys.exec_prefix,
    )
    file_created(dst)
