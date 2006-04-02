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


import os


from bzrlib.bzrdir import BzrDir
from bzrlib.osutils import format_date
from bzrlib.tests import TestSkipped
from bzrlib.tests.blackbox import ExternalBase


class TestInfo(ExternalBase):

    def test_info_standalone(self):
        # Create initial standalone branch
        self.runbzr('init standalone')
        os.chdir('standalone')
        file('hello', 'wt').write('hello world')
        self.runbzr('add hello')
        branch1 = BzrDir.open('.').open_branch()
        out, err = self.runbzr('info')
        self.assertEqualDiff(
"""Location:
          branch root: %s

Format:
        branch format: Bazaar-NG branch, format 6

In the working tree:
         0 unchanged
         0 modified
         1 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         0 revisions
         0 committers

Revision store:
         0 revisions
         0 kB
""" % branch1.bzrdir.root_transport.base, out)
        self.assertEqual('', err)
        self.runbzr('commit -m one')
        rev = branch1.repository.get_revision(branch1.revision_history()[0])
        datestring_first = format_date(rev.timestamp, rev.timezone)
        os.chdir('..')

        # Branch with push location
        self.runbzr('branch standalone branch')
        branch2 = BzrDir.open('branch').open_branch()
        branch2.set_push_location(branch1.bzrdir.root_transport.base)
        out, err = self.runbzr('info branch')
        self.assertEqualDiff(
"""Location:
          branch root: %s
        parent branch: %s
       push to branch: %s

Format:
        branch format: Bazaar-NG branch, format 6

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         1 revision
         1 committer
         0 days old
   first revision: %s
  latest revision: %s

Revision store:
         1 revision
         0 kB
""" % (branch2.bzrdir.root_transport.base, branch1.bzrdir.root_transport.base,
       branch1.bzrdir.root_transport.base,
       datestring_first, datestring_first), out)
        self.assertEqual('', err)

        # Branch, upgrade to metadir (creates backup as unknown) and bind
        self.runbzr('branch standalone bound')
        branch3 = BzrDir.open('bound').open_branch()
        os.chdir('bound')
        self.runbzr('upgrade --format=metadir')
        self.runbzr('bind ../standalone')
        os.chdir('..')
        out, err = self.runbzr('info bound')
        self.assertEqualDiff(
"""Location:
          branch root: %s
      bound to branch: %s
        parent branch: %s

Format:
  working tree format: Bazaar-NG Working Tree format 3
        branch format: Bazaar-NG branch format 5
    repository format: Bazaar-NG Repository format 7

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         1 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         1 revision
         1 committer
         0 days old
   first revision: %s
  latest revision: %s

Revision store:
         1 revision
         0 kB
""" % (branch3.bzrdir.root_transport.base, branch1.bzrdir.root_transport.base,
       branch1.bzrdir.root_transport.base,
       datestring_first, datestring_first), out)
        self.assertEqual('', err)

        # Checkout (same as above, but does not have parent set)
        self.runbzr('checkout standalone checkout')
        branch4 = BzrDir.open('checkout').open_branch()
        out, err = self.runbzr('info checkout')
        self.assertEqualDiff(
"""Location:
          branch root: %s
      bound to branch: %s

Format:
  working tree format: Bazaar-NG Working Tree format 3
        branch format: Bazaar-NG branch format 5
    repository format: Bazaar-NG Repository format 7

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         1 revision
         1 committer
         0 days old
   first revision: %s
  latest revision: %s

Revision store:
         1 revision
         0 kB
""" % (branch4.bzrdir.root_transport.base, branch1.bzrdir.root_transport.base,
       datestring_first, datestring_first), out)
        self.assertEqual('', err)

        # Lightweight checkout (same as above, different branch and repository)
        self.runbzr('checkout --lightweight standalone lightcheckout')
        branch5 = BzrDir.open('lightcheckout').open_workingtree()
        out, err = self.runbzr('info lightcheckout')
        self.assertEqualDiff(
"""Location:
        checkout root: %s
   checkout of branch: %s

Format:
  working tree format: Bazaar-NG Working Tree format 3
        branch format: Bazaar-NG branch, format 6
    repository format: Bazaar-NG branch, format 6

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         1 revision
         1 committer
         0 days old
   first revision: %s
  latest revision: %s

Revision store:
         1 revision
         0 kB
""" % (branch5.bzrdir.root_transport.base, branch1.bzrdir.root_transport.base,
       datestring_first, datestring_first), out)
        self.assertEqual('', err)

        # Update initial standalone branch
        os.chdir('standalone')
        file('bye', 'wt').write('goodbye')
        self.runbzr('add bye')
        self.runbzr('commit -m two')
        rev = branch1.repository.get_revision(branch1.revision_history()[-1])
        datestring_last = format_date(rev.timestamp, rev.timezone)
        os.chdir('..')

        # Out of date branched standalone branch will not be detected
        out, err = self.runbzr('info branch')
        self.assertEqualDiff(
"""Location:
          branch root: %s
        parent branch: %s
       push to branch: %s

Format:
        branch format: Bazaar-NG branch, format 6

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         1 revision
         1 committer
         0 days old
   first revision: %s
  latest revision: %s

Revision store:
         1 revision
         0 kB
""" % (branch2.bzrdir.root_transport.base, branch1.bzrdir.root_transport.base,
       branch1.bzrdir.root_transport.base,
       datestring_first, datestring_first), out)
        self.assertEqual('', err)

        # Out of date bound branch
        out, err = self.runbzr('info bound')
        self.assertEqualDiff(
"""Location:
          branch root: %s
      bound to branch: %s
        parent branch: %s

Format:
  working tree format: Bazaar-NG Working Tree format 3
        branch format: Bazaar-NG branch format 5
    repository format: Bazaar-NG Repository format 7

Branch is out of date: missing 1 revision.

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         1 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         1 revision
         1 committer
         0 days old
   first revision: %s
  latest revision: %s

Revision store:
         1 revision
         0 kB
""" % (branch3.bzrdir.root_transport.base, branch1.bzrdir.root_transport.base,
       branch1.bzrdir.root_transport.base,
       datestring_first, datestring_first), out)
        self.assertEqual('', err)

        # Out of date checkout
        out, err = self.runbzr('info checkout')
        self.assertEqualDiff(
"""Location:
          branch root: %s
      bound to branch: %s

Format:
  working tree format: Bazaar-NG Working Tree format 3
        branch format: Bazaar-NG branch format 5
    repository format: Bazaar-NG Repository format 7

Branch is out of date: missing 1 revision.

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         1 revision
         1 committer
         0 days old
   first revision: %s
  latest revision: %s

Revision store:
         1 revision
         0 kB
""" % (branch4.bzrdir.root_transport.base, branch1.bzrdir.root_transport.base,
       datestring_first, datestring_first), out)
        self.assertEqual('', err)

        # Out of date lightweight checkout
        out, err = self.runbzr('info lightcheckout')
        self.assertEqualDiff(
"""Location:
        checkout root: %s
   checkout of branch: %s

Format:
  working tree format: Bazaar-NG Working Tree format 3
        branch format: Bazaar-NG branch, format 6
    repository format: Bazaar-NG branch, format 6

Working tree is out of date: missing 1 revision.

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         2 revisions
         1 committer
         0 days old
   first revision: %s
  latest revision: %s

Revision store:
         2 revisions
         0 kB
""" % (branch5.bzrdir.root_transport.base, branch1.bzrdir.root_transport.base,
       datestring_first, datestring_last), out)
        self.assertEqual('', err)

    def test_info_shared_repository(self):
        # Create shared repository
        self.runbzr('init-repository repo')
        os.chdir('repo')
        self.runbzr('init --format=metadir branch')
        os.chdir('..')

        # Create lightweight checkout
        os.mkdir('tree')
        os.chdir('tree')
        self.runbzr('checkout --lightweight ../repo/branch lightcheckout')
        bzrdir1 = BzrDir.open('lightcheckout')
        work1 = bzrdir1.open_workingtree()
        branch1 = bzrdir1.open_branch()
        repo = branch1.repository
        out, err = self.runbzr('info lightcheckout')
        self.assertEqualDiff(
"""Location:
        checkout root: %s
   checkout of branch: %s
    shared repository: %s

Format:
  working tree format: Bazaar-NG Working Tree format 3
        branch format: Bazaar-NG branch format 5
    repository format: Bazaar-NG Repository format 7

In the working tree:
         0 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         0 revisions
         0 committers

Revision store:
         0 revisions
         0 kB
""" % (work1.bzrdir.root_transport.base,
       branch1.bzrdir.root_transport.base,
       repo.bzrdir.root_transport.base), out)
        self.assertEqual('', err)

        # Create normal checkout
        self.runbzr('checkout ../repo/branch checkout')
        bzrdir2 = BzrDir.open('checkout')
        work2 = bzrdir2.open_workingtree()
        branch2 = bzrdir2.open_branch()
        out, err = self.runbzr('info checkout')
        self.assertEqualDiff(
"""Location:
          branch root: %s
      bound to branch: %s

Format:
  working tree format: Bazaar-NG Working Tree format 3
        branch format: Bazaar-NG branch format 5
    repository format: Bazaar-NG Repository format 7

In the working tree:
         0 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         0 revisions
         0 committers

Revision store:
         0 revisions
         0 kB
""" % (work2.bzrdir.root_transport.base,
       branch2.get_bound_location()), out)
        self.assertEqual('', err)

        # Update lightweight checkout
        os.chdir('lightcheckout')
        file('hello', 'wt').write('hello world')
        self.runbzr('add hello')
        self.runbzr('commit -m one')
        rev = repo.get_revision(branch1.revision_history()[0])
        datestring_first = format_date(rev.timestamp, rev.timezone)
        os.chdir('..')
        out, err = self.runbzr('info lightcheckout')
        self.assertEqualDiff(
"""Location:
        checkout root: %s
   checkout of branch: %s
    shared repository: %s

Format:
  working tree format: Bazaar-NG Working Tree format 3
        branch format: Bazaar-NG branch format 5
    repository format: Bazaar-NG Repository format 7

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         1 revision
         1 committer
         0 days old
   first revision: %s
  latest revision: %s

Revision store:
         1 revision
         0 kB
""" % (work1.bzrdir.root_transport.base,
       branch1.bzrdir.root_transport.base,
       repo.bzrdir.root_transport.base,
       datestring_first, datestring_first), out)
        self.assertEqual('', err)

        # Out of date checkout
        out, err = self.runbzr('info checkout')
        self.assertEqualDiff(
"""Location:
          branch root: %s
      bound to branch: %s

Format:
  working tree format: Bazaar-NG Working Tree format 3
        branch format: Bazaar-NG branch format 5
    repository format: Bazaar-NG Repository format 7

Branch is out of date: missing 1 revision.

In the working tree:
         0 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         0 revisions
         0 committers

Revision store:
         0 revisions
         0 kB
""" % (work2.bzrdir.root_transport.base,
       branch2.get_bound_location()), out)
        self.assertEqual('', err)

        # Update checkout
        os.chdir('checkout')
        self.runbzr('update')
        file('bye', 'wt').write('goodbye')
        self.runbzr('add bye')
        out, err = self.runbzr('info')
        self.assertEqualDiff(
"""Location:
          branch root: %s
      bound to branch: %s

Format:
  working tree format: Bazaar-NG Working Tree format 3
        branch format: Bazaar-NG branch format 5
    repository format: Bazaar-NG Repository format 7

In the working tree:
         1 unchanged
         0 modified
         1 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         1 revision
         1 committer
         0 days old
   first revision: %s
  latest revision: %s

Revision store:
         1 revision
         0 kB
""" % (work2.bzrdir.root_transport.base, branch1.bzrdir.root_transport.base,
       datestring_first, datestring_first), out)
        self.assertEqual('', err)
        self.runbzr('commit -m two')
        os.chdir('..')

        # Out of date lightweight checkout
        rev = repo.get_revision(branch1.revision_history()[0])
	datestring_last = format_date(rev.timestamp, rev.timezone)
        out, err = self.runbzr('info lightcheckout')
        self.assertEqualDiff(
"""Location:
        checkout root: %s
   checkout of branch: %s
    shared repository: %s

Format:
  working tree format: Bazaar-NG Working Tree format 3
        branch format: Bazaar-NG branch format 5
    repository format: Bazaar-NG Repository format 7

Working tree is out of date: missing 1 revision.

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         2 revisions
         1 committer
         0 days old
   first revision: %s
  latest revision: %s

Revision store:
         2 revisions
         0 kB
""" % (work1.bzrdir.root_transport.base,
       branch1.bzrdir.root_transport.base,
       repo.bzrdir.root_transport.base,
       datestring_first, datestring_last), out)
        self.assertEqual('', err)

    def test_info_shared_repository_with_trees(self):
        # TODO: Do the same with checkouts inside this repository
        # XXX: Replace with --trees option when it's in mainline bzr.dev
        # Create shared repository
        self.runbzr('init-repository repotree')
        # self.runbzr('init-repository --trees repotree')
        os.unlink('repotree/.bzr/repository/no-working-trees')
        os.chdir('repotree')
        self.runbzr('init --format=metadir branch1')
        self.runbzr('branch branch1 branch2')

        # Empty first branch
        bzrdir1 = BzrDir.open('branch1')
        branch1 = bzrdir1.open_branch()
        repo = branch1.repository
        out, err = self.runbzr('info branch1')
        self.assertEqualDiff(
"""Location:
          branch root: %s
    shared repository: %s

Format:
  working tree format: Bazaar-NG Working Tree format 3
        branch format: Bazaar-NG branch format 5
    repository format: Bazaar-NG Repository format 7

In the working tree:
         0 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         0 revisions
         0 committers

Revision store:
         0 revisions
         0 kB
""" % (branch1.bzrdir.root_transport.base,
       repo.bzrdir.root_transport.base), out)
        self.assertEqual('', err)

        # Update first branch
        os.chdir('branch1')
        file('hello', 'wt').write('hello world')
        self.runbzr('add hello')
        self.runbzr('commit -m one')
        os.chdir('..')
        rev = repo.get_revision(branch1.revision_history()[0])
        datestring_first = format_date(rev.timestamp, rev.timezone)
        out, err = self.runbzr('info branch1')
        self.assertEqualDiff(
"""Location:
          branch root: %s
    shared repository: %s

Format:
  working tree format: Bazaar-NG Working Tree format 3
        branch format: Bazaar-NG branch format 5
    repository format: Bazaar-NG Repository format 7

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         1 revision
         1 committer
         0 days old
   first revision: %s
  latest revision: %s

Revision store:
         1 revision
         0 kB
""" % (branch1.bzrdir.root_transport.base, repo.bzrdir.root_transport.base,
       datestring_first, datestring_first), out)
        self.assertEqual('', err)

        # Out of date second branch
        bzrdir2 = BzrDir.open('branch2')
        branch2 = bzrdir2.open_branch()
        out, err = self.runbzr('info branch2')
        self.assertEqualDiff(
"""Location:
          branch root: %s
    shared repository: %s
        parent branch: %s

Format:
  working tree format: Bazaar-NG Working Tree format 3
        branch format: Bazaar-NG branch format 5
    repository format: Bazaar-NG Repository format 7

In the working tree:
         0 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         0 revisions
         0 committers

Revision store:
         1 revision
         0 kB
""" % (branch2.bzrdir.root_transport.base, repo.bzrdir.root_transport.base,
       branch1.bzrdir.root_transport.base), out)
        self.assertEqual('', err)

        # Update second branch
        os.chdir('branch2')
        self.runbzr('pull')
        out, err = self.runbzr('info')
        self.assertEqualDiff(
"""Location:
          branch root: %s
    shared repository: %s
        parent branch: %s

Format:
  working tree format: Bazaar-NG Working Tree format 3
        branch format: Bazaar-NG branch format 5
    repository format: Bazaar-NG Repository format 7

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         1 revision
         1 committer
         0 days old
   first revision: %s
  latest revision: %s

Revision store:
         1 revision
         0 kB
""" % (branch2.bzrdir.root_transport.base,
       repo.bzrdir.root_transport.base,
       branch1.bzrdir.root_transport.base,
       datestring_first, datestring_first), out)
        self.assertEqual('', err)
