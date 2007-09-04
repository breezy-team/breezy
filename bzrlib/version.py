# Copyright (C) 2004, 2005, 2006, 2007 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Report on version of bzrlib"""

import os
import sys

import bzrlib
from bzrlib import (
    bzrdir,
    config,
    errors,
    osutils,
    trace,
    )
from bzrlib.branch import Branch


def show_version(show_config=True, show_copyright=True, to_file=None):
    if to_file is None:
        to_file = sys.stdout
    print >>to_file, "Bazaar (bzr) %s" % bzrlib.__version__
    # is bzrlib itself in a branch?
    src_tree = _get_bzr_source_tree()
    if src_tree:
        src_revision_id = src_tree.last_revision()
        revno = src_tree.branch.revision_id_to_revno(src_revision_id)
        print >>to_file, "  from bzr checkout", src_tree.basedir
        print >>to_file, "    revision:", revno
        print >>to_file, "    revid:", src_revision_id
        print >>to_file, "    branch nick:", src_tree.branch.nick
    print >>to_file, "  Python interpreter:",
    print >>to_file, sys.executable, '.'.join(map(str, sys.version_info))
    print >>to_file, "  Python standard library:", os.path.dirname(os.__file__)
    print >>to_file, "  bzrlib:",
    if len(bzrlib.__path__) > 1:
        # print repr, which is a good enough way of making it clear it's
        # more than one element (eg ['/foo/bar', '/foo/bzr'])
        print >>to_file, repr(bzrlib.__path__)
    else:
        print >>to_file, bzrlib.__path__[0]
    if show_config:
        config_dir = os.path.normpath(config.config_dir())  # use native slashes
        if not isinstance(config_dir, unicode):
            config_dir = config_dir.decode(bzrlib.user_encoding)
        print >>to_file, "  Bazaar configuration:", config_dir
        print >>to_file, "  Bazaar log file:", trace._bzr_log_filename
    if show_copyright:
        print >>to_file
        print >>to_file, bzrlib.__copyright__
        print >>to_file, "http://bazaar-vcs.org/"
        print >>to_file
        print >>to_file, "bzr comes with ABSOLUTELY NO WARRANTY.  bzr is free software, and"
        print >>to_file, "you may use, modify and redistribute it under the terms of the GNU"
        print >>to_file, "General Public License version 2 or later."
    print >>to_file


def _get_bzr_source_tree():
    """Return the WorkingTree for bzr source, if any.

    If bzr is not being run from its working tree, returns None.
    """
    try:
        control = bzrdir.BzrDir.open_containing(__file__)[0]
        return control.open_workingtree(recommend_upgrade=False)
    except (errors.NotBranchError, errors.UnknownFormatError,
            errors.NoWorkingTree):
        return None
