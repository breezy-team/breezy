##############################################################################
#
# Copyright (c) 2006 Zope Corporation and Contributors.
# All Rights Reserved.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.1 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE.
#
##############################################################################
"""Bootstrap a buildout-based project.

Simply run this script in a directory containing a buildout.cfg.
The script accepts buildout command-line options, so you can
use the -c option to specify an alternate configuration file.

$Id: bootstrap.py 90478 2008-08-27 22:44:46Z georgyberdyshev $
"""

import os
import shutil
import sys
import tempfile

import urllib2

tmpeggs = tempfile.mkdtemp()

is_jython = sys.platform.startswith("java")

try:
    import pkg_resources
except ModuleNotFoundError:
    ez = {}
    exec(  # noqa: S102
        urllib2.urlopen("http://peak.telecommunity.com/dist/ez_setup.py").read(),
        ez,
    )
    ez["use_setuptools"](to_dir=tmpeggs, download_delay=0)

    import pkg_resources

if sys.platform == "win32":

    def quote(c):
        """Quote a command argument for Windows if it contains spaces.

        Args:
            c (str): The command argument to potentially quote.

        Returns:
            str: The argument quoted with double quotes if it contains spaces,
                otherwise the original argument.
        """
        if " " in c:
            return f'"{c}"'  # work around spawn lamosity on windows
        else:
            return c
else:

    def quote(c):
        """Quote a command argument for non-Windows platforms.

        Args:
            c (str): The command argument to quote.

        Returns:
            str: The original argument unchanged (no quoting needed on Unix-like systems).
        """
        return c


cmd = "from setuptools.command.easy_install import main; main()"
ws = pkg_resources.working_set
env = dict(
    os.environ,
    PYTHONPATH=ws.find(pkg_resources.Requirement.parse("setuptools")).location,
)

if is_jython:
    import subprocess

    if (
        subprocess.Popen(
            [sys.executable]
            + ["-c", quote(cmd), "-mqNxd", quote(tmpeggs), "zc.buildout"],
            env=env,
        ).wait()
        != 0
    ):
        raise ASsertionError("Failed to bootstrap zc.buildout")

else:
    if (
        os.spawnle(  # noqa: S606
            os.P_WAIT,
            sys.executable,
            quote(sys.executable),
            "-c",
            quote(cmd),
            "-mqNxd",
            quote(tmpeggs),
            "zc.buildout",
            env,
        )
        != 0
    ):
        raise AssertionError("Failed to bootstrap zc.buildout")

ws.add_entry(tmpeggs)
ws.require("zc.buildout")
import zc.buildout.buildout

zc.buildout.buildout.main(sys.argv[1:] + ["bootstrap"])
shutil.rmtree(tmpeggs)
