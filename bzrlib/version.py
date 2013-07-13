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

"""Report on version of bzrlib"""

from __future__ import absolute_import

import os
import platform
import sys

import bzrlib
from bzrlib import (
    config,
    controldir,
    errors,
    osutils,
    trace,
    )


def show_version(show_config=True, show_copyright=True, to_file=None):
    if to_file is None:
        to_file = sys.stdout
    to_file.write("Bazaar (bzr) %s\n" % bzrlib.__version__)
    # is bzrlib itself in a branch?
    src_tree = _get_bzr_source_tree()
    if src_tree:
        src_revision_id = src_tree.last_revision()
        revno = src_tree.branch.revision_id_to_revno(src_revision_id)
        to_file.write("  from bzr checkout %s\n" % (src_tree.basedir,))
        to_file.write("    revision: %s\n" % (revno,))
        to_file.write("    revid: %s\n" % (src_revision_id,))
        to_file.write("    branch nick: %s\n" % (src_tree.branch.nick,))

    to_file.write("  Python interpreter: ")
    # show path to python interpreter
    # (bzr.exe use python interpreter from pythonXY.dll
    # but sys.executable point to bzr.exe itself)
    # however, sys.frozen exists if running from bzr.exe
    # see http://www.py2exe.org/index.cgi/Py2exeEnvironment
    if getattr(sys, 'frozen', None) is None: # if not bzr.exe
        to_file.write(sys.executable + ' ')
    else:
        # pythonXY.dll
        basedir = os.path.dirname(sys.executable)
        python_dll = "python%d%d.dll" % sys.version_info[:2]
        to_file.write(os.path.join(basedir, python_dll) + ' ')
    # and now version of python interpreter
    to_file.write(bzrlib._format_version_tuple(sys.version_info))
    to_file.write('\n')

    to_file.write("  Python standard library:" + ' ')
    to_file.write(os.path.dirname(os.__file__) + '\n')
    to_file.write("  Platform: %s\n"
                  % platform.platform(aliased=1).decode('utf-8'))
    to_file.write("  bzrlib: ")
    if len(bzrlib.__path__) > 1:
        # print repr, which is a good enough way of making it clear it's
        # more than one element (eg ['/foo/bar', '/foo/bzr'])
        to_file.write(repr(bzrlib.__path__) + '\n')
    else:
        to_file.write(bzrlib.__path__[0] + '\n')
    if show_config:
        config_dir = osutils.normpath(config.config_dir())  # use native slashes
        if not isinstance(config_dir, unicode):
            config_dir = config_dir.decode(osutils.get_user_encoding())
        to_file.write("  Bazaar configuration: %s\n" % (config_dir,))
        to_file.write("  Bazaar log file: ")
        to_file.write(trace._bzr_log_filename + '\n')
    if show_copyright:
        to_file.write('\n')
        to_file.write(bzrlib.__copyright__ + '\n')
        to_file.write("http://bazaar.canonical.com/\n")
        to_file.write('\n')
        to_file.write("bzr comes with ABSOLUTELY NO WARRANTY.  bzr is free software, and\n")
        to_file.write("you may use, modify and redistribute it under the terms of the GNU\n")
        to_file.write("General Public License version 2 or later.\n")
        to_file.write("\nBazaar is part of the GNU Project to produce a free operating "
                "system.\n")
    to_file.write('\n')


def _get_bzr_source_tree():
    """Return the WorkingTree for bzr source, if any.

    If bzr is not being run from its working tree, returns None.
    """
    try:
        control = controldir.ControlDir.open_containing(__file__)[0]
        return control.open_workingtree(recommend_upgrade=False)
    except (errors.NotBranchError, errors.UnknownFormatError,
            errors.NoWorkingTree):
        return None
