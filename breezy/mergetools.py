# Copyright (C) 2010 Canonical Ltd.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Utility functions for managing external merge tools such as kdiff3."""

import os
import shutil
import subprocess
import sys
import tempfile

from .lazy_import import lazy_import

lazy_import(
    globals(),
    """
from breezy import (
    cmdline,
    osutils,
    trace,
)
""",
)


known_merge_tools = {
    "bcompare": "bcompare {this} {other} {base} {result}",
    "kdiff3": "kdiff3 {base} {this} {other} -o {result}",
    "xdiff": "xxdiff -m -O -M {result} {this} {base} {other}",
    "meld": "meld {base} {this_temp} {other}",
    "opendiff": "opendiff {this} {other} -ancestor {base} -merge {result}",
    "winmergeu": "winmergeu {result}",
}


def check_availability(command_line):
    cmd_list = cmdline.split(command_line)
    exe = cmd_list[0]
    if sys.platform == "win32":
        exe = _get_executable_path(exe)
        if exe is None:
            return False
        _base, ext = os.path.splitext(exe)
        path_ext = [s.lower() for s in os.getenv("PATHEXT", "").split(os.pathsep)]
        return os.path.exists(exe) and ext in path_ext
    else:
        return (
            os.access(exe, os.X_OK) or osutils.find_executable_on_path(exe) is not None
        )


def invoke(command_line, filename, invoker=None):
    """Invokes the given merge tool command line, substituting the given
    filename according to the embedded substitution markers. Optionally, it
    will use the given invoker function instead of the default
    subprocess_invoker.
    """
    if invoker is None:
        invoker = subprocess_invoker
    cmd_list = cmdline.split(command_line)
    exe = _get_executable_path(cmd_list[0])
    if exe is not None:
        cmd_list[0] = exe
    args, tmp_file = _subst_filename(cmd_list, filename)

    def cleanup(retcode):
        if tmp_file is not None:
            if retcode == 0:  # on success, replace file with temp file
                shutil.move(tmp_file, filename)
            else:  # otherwise, delete temp file
                os.remove(tmp_file)

    return invoker(args[0], args[1:], cleanup)


def _get_executable_path(exe):
    if os.path.isabs(exe):
        return exe
    return osutils.find_executable_on_path(exe)


def _subst_filename(args, filename):
    subst_names = {
        "base": filename + ".BASE",
        "this": filename + ".THIS",
        "other": filename + ".OTHER",
        "result": filename,
    }
    tmp_file = None
    subst_args = []
    for arg in args:
        if "{this_temp}" in arg and "this_temp" not in subst_names:
            fh, tmp_file = tempfile.mkstemp(
                "_bzr_mergetools_{}.THIS".format(os.path.basename(filename))
            )
            trace.mutter("fh=%r, tmp_file=%r", fh, tmp_file)
            os.close(fh)
            shutil.copy(filename + ".THIS", tmp_file)
            subst_names["this_temp"] = tmp_file
        arg = _format_arg(arg, subst_names)
        subst_args.append(arg)
    return subst_args, tmp_file


# This would be better implemented using format() from python 2.6
def _format_arg(arg, subst_names):
    arg = arg.replace("{base}", subst_names["base"])
    arg = arg.replace("{this}", subst_names["this"])
    arg = arg.replace("{other}", subst_names["other"])
    arg = arg.replace("{result}", subst_names["result"])
    if "this_temp" in subst_names:
        arg = arg.replace("{this_temp}", subst_names["this_temp"])
    return arg


def subprocess_invoker(executable, args, cleanup):
    retcode = subprocess.call([executable] + args)
    cleanup(retcode)
    return retcode
