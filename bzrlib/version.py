# Copyright (C) 2004, 2005, 2006 Canonical Ltd
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
from bzrlib import errors, osutils
from bzrlib.branch import Branch


def show_version():
    print "Bazaar (bzr) %s" % bzrlib.__version__
    # is bzrlib itself in a branch?
    src_tree = _get_bzr_source_tree()
    if src_tree:
        src_revision_id = src_tree.last_revision()
        revno = src_tree.branch.revision_id_to_revno(src_revision_id)
        print "  from bzr checkout", src_tree.basedir
        print "    revision:", revno
        print "    revid:", src_revision_id
        print "    branch nick:", src_tree.branch.nick
    print "Using python interpreter:", sys.executable
    import site
    print "Using python standard library:", os.path.dirname(site.__file__)
    print "Using bzrlib:",
    if len(bzrlib.__path__) > 1:
        # print repr, which is a good enough way of making it clear it's
        # more than one element (eg ['/foo/bar', '/foo/bzr'])
        print repr(bzrlib.__path__)
    else:
        print bzrlib.__path__[0]

    print
    print bzrlib.__copyright__
    print "http://bazaar-vcs.org/"
    print
    print "bzr comes with ABSOLUTELY NO WARRANTY.  bzr is free software, and"
    print "you may use, modify and redistribute it under the terms of the GNU"
    print "General Public License version 2 or later."


def _get_bzr_source_tree():
    """Return the WorkingTree for bzr source, if any.

    If bzr is not being run from its working tree, returns None.
    """
    try:
        from bzrlib.workingtree import WorkingTree
        return WorkingTree.open_containing(__file__)[0]
    except (errors.NotBranchError, errors.UnknownFormatError):
        return None
