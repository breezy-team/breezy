# Copyright (C) 2006 by Canonical Ltd
# -*- coding: utf-8 -*-

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""Tests for the info command of bzr."""


from bzrlib.osutils import format_date
from bzrlib.tests import TestSkipped
from bzrlib.tests.blackbox import ExternalBase


class TestInfo(ExternalBase):

    def test_info_standalone_trivial(self):
        self.runbzr("init")
        out, err = self.runbzr('info')
        self.assertEqualDiff(
"""branch format: Bazaar-NG branch, format 6

in the working tree:
         0 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

branch history:
         0 revisions
         0 committers

revision store:
         0 revisions
         0 kB
""",
        out)
        self.assertEqual('', err)

    def test_info_up_to_date_checkout(self):
        a_branch = self.make_branch_and_tree('branch')
        self.runbzr('checkout branch checkout')
        out, err = self.runbzr('info checkout')
        self.assertEqualDiff(
"""working tree format: Bazaar-NG Working Tree format 3
branch location: %s
branch format: Bazaar-NG branch, format 6

in the working tree:
         0 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

branch history:
         0 revisions
         0 committers

revision store:
         0 revisions
         0 kB
""" % a_branch.bzrdir.root_transport.base,
        out)
        self.assertEqual('', err)

    def test_info_out_of_date_standalone_tree(self):
        # FIXME the default format has to change for this to pass
        # because it currently uses the branch last-revision marker.
        raise TestSkipped('default format too old')
        self.make_branch_and_tree('branch')
        # make a checkout
        self.runbzr('checkout branch checkout')
        self.build_tree(['checkout/file'])
        self.runbzr('add checkout/file')
        self.runbzr('commit -m add-file checkout')
        # now branch should be out of date
        out,err = self.runbzr('update branch')
        self.assertEqualDiff(
"""branch format: Bazaar-NG branch, format 6

Working tree is out of date: missing 1 revision.
in the working tree:
         0 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

branch history:
         0 revisions
         0 committers

revision store:
         0 revisions
         0 kB
""" % a_branch.bzrdir.root_transport.base,
        out)
        self.assertEqual('', err)

    def test_info_out_of_date_checkout(self):
        # note this deliberately uses a checkout at 'None' to 
        # test the out of date message with a revision notin the 
        # revision history.
        a_branch = self.make_branch('branch')
        # make two checkouts
        self.runbzr('checkout branch checkout')
        self.runbzr('checkout branch checkout2')
        self.build_tree(['checkout/file'])
        self.runbzr('add checkout/file')
        self.runbzr('commit -m add-file checkout')
        # now checkout2 should be out of date
        out,err = self.runbzr('info checkout2')
        rev = a_branch.repository.get_revision(a_branch.revision_history()[0])
        datestring = format_date(rev.timestamp, rev.timezone)
        self.assertEqualDiff(
"""working tree format: Bazaar-NG Working Tree format 3
branch location: %s
branch format: Bazaar-NG branch, format 6

Working tree is out of date: missing 1 revision.
in the working tree:
         0 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

branch history:
         1 revision
         1 committer
         0 days old
   first revision: %s
  latest revision: %s

revision store:
         1 revision
         0 kB
""" % (a_branch.bzrdir.root_transport.base,
       datestring,
       datestring,
       ),
            out)
        self.assertEqual('', err)
