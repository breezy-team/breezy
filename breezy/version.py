# Copyright (C) 2006-2010 Canonical Ltd
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

"""Report on version of breezy."""

import os
import platform
import sys

from vcsgraph.errors import GhostRevisionsHaveNoRevno

import breezy

from . import bedding, controldir, errors, osutils, trace


def show_version(show_config=True, show_copyright=True, to_file=None):
    """Display version information about Breezy.

    Shows version details including the Breezy version, Python interpreter
    information, platform details, and optionally configuration paths and
    copyright information.

    Args:
        show_config: If True, display configuration directory and log file paths.
            Defaults to True.
        show_copyright: If True, display copyright and license information.
            Defaults to True.
        to_file: File-like object to write the version information to.
            If None, uses sys.stdout. Defaults to None.
    """
    if to_file is None:
        to_file = sys.stdout
    to_file.write(f"Breezy (brz) {breezy.__version__}\n")
    # is breezy itself in a branch?
    src_tree = _get_brz_source_tree()
    if src_tree:
        src_revision_id = src_tree.last_revision()
        to_file.write(f"  from brz checkout {src_tree.basedir}\n")
        try:
            revno = src_tree.branch.revision_id_to_revno(src_revision_id)
        except GhostRevisionsHaveNoRevno:
            pass
        else:
            to_file.write(f"    revision: {revno}\n")
        to_file.write(f"    revid: {src_revision_id}\n")
        to_file.write(f"    branch nick: {src_tree.branch.nick}\n")

    to_file.write("  Python interpreter: ")
    # show path to python interpreter
    # (brz.exe use python interpreter from pythonXY.dll
    # but sys.executable point to brz.exe itself)
    # however, sys.frozen exists if running from brz.exe
    # see http://www.py2exe.org/index.cgi/Py2exeEnvironment
    if getattr(sys, "frozen", None) is None:  # if not brz.exe
        to_file.write(sys.executable + " ")
    else:
        # pythonXY.dll
        basedir = os.path.dirname(sys.executable)
        python_dll = "python%d%d.dll" % sys.version_info[:2]
        to_file.write(os.path.join(basedir, python_dll) + " ")
    # and now version of python interpreter
    to_file.write(breezy._format_version_tuple(sys.version_info))
    to_file.write("\n")

    to_file.write("  Python standard library:" + " ")
    to_file.write(os.path.dirname(os.__file__) + "\n")
    platform_str = platform.platform(aliased=1)
    if not isinstance(platform_str, str):
        platform_str = platform_str.decode("utf-8")
    to_file.write(f"  Platform: {platform_str}\n")
    to_file.write("  breezy: ")
    if len(breezy.__path__) > 1:
        # print repr, which is a good enough way of making it clear it's
        # more than one element (eg ['/foo/bar', '/foo/brz'])
        to_file.write(repr(breezy.__path__) + "\n")
    else:
        to_file.write(breezy.__path__[0] + "\n")
    if show_config:
        config_dir = osutils.normpath(bedding.config_dir())  # use native slashes
        if not isinstance(config_dir, str):
            config_dir = config_dir.decode(osutils.get_user_encoding())
        to_file.write(f"  Breezy configuration: {config_dir}\n")
        to_file.write("  Breezy log file: ")
        to_file.write(trace.get_brz_log_filename() + "\n")
    if show_copyright:
        to_file.write("\n")
        to_file.write(breezy.__copyright__ + "\n")
        to_file.write("https://www.breezy-vcs.org/\n")
        to_file.write("\n")
        to_file.write(
            "brz comes with ABSOLUTELY NO WARRANTY.  brz is free software, and\n"
        )
        to_file.write(
            "you may use, modify and redistribute it under the terms of the GNU\n"
        )
        to_file.write("General Public License version 2 or later.\n")
    to_file.write("\n")


def _get_brz_source_tree():
    """Return the WorkingTree for brz source, if any.

    If brz is not being run from its working tree, returns None.
    """
    try:
        control = controldir.ControlDir.open_containing(__file__)[0]
        return control.open_workingtree(recommend_upgrade=False)
    except (errors.NotBranchError, errors.UnknownFormatError, errors.NoWorkingTree):
        return None
