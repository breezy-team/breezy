# Copyright (C) 2006-2012, 2016 Canonical Ltd
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


"""Tests for the info command of bzr."""

import shutil
import sys

from breezy import (
    branch,
    controldir,
    errors,
    info,
    osutils,
    tests,
    upgrade,
    urlutils,
    )
from breezy.bzr import (
    bzrdir,
    )
from breezy.transport import memory


class TestInfo(tests.TestCaseWithTransport):

    def setUp(self):
        super(TestInfo, self).setUp()
        self._repo_strings = "2a"

    def test_info_non_existing(self):
        self.vfs_transport_factory = memory.MemoryServer
        location = self.get_url()
        out, err = self.run_bzr('info ' + location, retcode=3)
        self.assertEqual(out, '')
        self.assertEqual(err, 'brz: ERROR: Not a branch: "%s".\n' % location)

    def test_info_empty_controldir(self):
        self.make_controldir('ctrl')
        out, err = self.run_bzr('info ctrl')
        self.assertEqual(out,
                         'Empty control directory (format: 2a)\n'
                         'Location:\n'
                         '  control directory: ctrl\n')
        self.assertEqual(err, '')

    def test_info_empty_controldir_verbose(self):
        self.make_controldir('ctrl')
        out, err = self.run_bzr('info -v ctrl')
        self.assertEqualDiff(out,
                             'Empty control directory (format: 2a)\n'
                             'Location:\n'
                             '  control directory: ctrl\n\n'
                             'Format:\n'
                             '       control: Meta directory format 1\n\n'
                             'Control directory:\n'
                             '         0 branches\n')
        self.assertEqual(err, '')

    def test_info_dangling_branch_reference(self):
        br = self.make_branch('target')
        br.create_checkout('from', lightweight=True)
        shutil.rmtree('target')
        out, err = self.run_bzr('info from')
        self.assertEqual(out,
                         'Dangling branch reference (format: 2a)\n'
                         'Location:\n'
                         '   control directory: from\n'
                         '  checkout of branch: target\n')
        self.assertEqual(err, '')

    def test_info_colocated(self):
        br = self.make_branch_and_tree('target', format='development-colo')
        target = br.controldir.create_branch(name='dichtbij')
        br.controldir.set_branch_reference(target)
        out, err = self.run_bzr('info target')
        self.assertEqual(out,
                         'Standalone tree (format: development-colo)\n'
                         'Location:\n'
                         '            light checkout root: target\n'
                         '  checkout of co-located branch: dichtbij\n')
        self.assertEqual(err, '')

    def test_info_standalone(self):
        transport = self.get_transport()

        # Create initial standalone branch
        tree1 = self.make_branch_and_tree('standalone', 'knit')
        self.build_tree(['standalone/a'])
        tree1.add('a')
        branch1 = tree1.branch

        out, err = self.run_bzr('info standalone')
        self.assertEqualDiff(
            """Standalone tree (format: knit)
Location:
  branch root: standalone
""", out)
        self.assertEqual('', err)

        # Standalone branch - verbose mode
        out, err = self.run_bzr('info standalone -v')
        self.assertEqualDiff(
            """Standalone tree (format: knit)
Location:
  branch root: standalone

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: Branch format 5
    repository: Knit repository format 1

Control directory:
         1 branches

In the working tree:
         0 unchanged
         0 modified
         1 added
         0 removed
         0 renamed
         0 copied
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         0 revisions

Repository:
         0 revisions
""", out)
        self.assertEqual('', err)

        # Standalone branch - really verbose mode
        out, err = self.run_bzr('info standalone -vv')
        self.assertEqualDiff(
            """Standalone tree (format: knit)
Location:
  branch root: standalone

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: Branch format 5
    repository: Knit repository format 1

Control directory:
         1 branches

In the working tree:
         0 unchanged
         0 modified
         1 added
         0 removed
         0 renamed
         0 copied
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         0 revisions
         0 committers

Repository:
         0 revisions
""", out)
        self.assertEqual('', err)
        tree1.commit('commit one')
        rev = branch1.repository.get_revision(branch1.last_revision())
        datestring_first = osutils.format_date(rev.timestamp, rev.timezone)

        # Branch standalone with push location
        branch2 = branch1.controldir.sprout('branch').open_branch()
        branch2.set_push_location(branch1.controldir.root_transport.base)

        out, err = self.run_bzr('info branch')
        self.assertEqualDiff(
            """Standalone tree (format: knit)
Location:
  branch root: branch

Related branches:
    push branch: standalone
  parent branch: standalone
""", out)
        self.assertEqual('', err)

        out, err = self.run_bzr('info branch --verbose')
        self.assertEqualDiff(
            """Standalone tree (format: knit)
Location:
  branch root: branch

Related branches:
    push branch: standalone
  parent branch: standalone

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: Branch format 5
    repository: Knit repository format 1

Control directory:
         1 branches

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 copied
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         1 revision
         0 days old
   first revision: %s
  latest revision: %s

Repository:
         1 revision
""" % (datestring_first, datestring_first,
       ), out)
        self.assertEqual('', err)

        # Branch and bind to standalone, needs upgrade to metadir
        # (creates backup as unknown)
        branch1.controldir.sprout('bound')
        knit1_format = controldir.format_registry.make_controldir('knit')
        upgrade.upgrade('bound', knit1_format)
        branch3 = controldir.ControlDir.open('bound').open_branch()
        branch3.bind(branch1)
        bound_tree = branch3.controldir.open_workingtree()
        out, err = self.run_bzr('info -v bound')
        self.assertEqualDiff(
            """Checkout (format: knit)
Location:
       checkout root: bound
  checkout of branch: standalone

Related branches:
  parent branch: standalone

Format:
       control: Meta directory format 1
  working tree: %s
        branch: %s
    repository: %s

Control directory:
         1 branches

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 copied
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         1 revision
         0 days old
   first revision: %s
  latest revision: %s

Repository:
         1 revision
""" % (bound_tree._format.get_format_description(),
                branch3._format.get_format_description(),
                branch3.repository._format.get_format_description(),
                datestring_first, datestring_first,
       ), out)
        self.assertEqual('', err)

        # Checkout standalone (same as above, but does not have parent set)
        branch4 = controldir.ControlDir.create_branch_convenience('checkout',
                                                                  format=knit1_format)
        branch4.bind(branch1)
        branch4.controldir.open_workingtree().update()
        out, err = self.run_bzr('info checkout --verbose')
        self.assertEqualDiff(
            """Checkout (format: knit)
Location:
       checkout root: checkout
  checkout of branch: standalone

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: Branch format 5
    repository: %s

Control directory:
         1 branches

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 copied
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         1 revision
         0 days old
   first revision: %s
  latest revision: %s

Repository:
         1 revision
""" % (branch4.repository._format.get_format_description(),
                datestring_first, datestring_first,
       ), out)
        self.assertEqual('', err)

        # Lightweight checkout (same as above, different branch and repository)
        tree5 = branch1.create_checkout('lightcheckout', lightweight=True)
        branch5 = tree5.branch
        out, err = self.run_bzr('info -v lightcheckout')
        if "metaweave" in controldir.format_registry:
            format_description = "knit or metaweave"
        else:
            format_description = "knit"
        self.assertEqualDiff(
            """Lightweight checkout (format: %s)
Location:
  light checkout root: lightcheckout
   checkout of branch: standalone

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: Branch format 5
    repository: Knit repository format 1

Control directory:
         1 branches

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 copied
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         1 revision
         0 days old
   first revision: %s
  latest revision: %s

Repository:
         1 revision
""" % (format_description, datestring_first, datestring_first,), out)
        self.assertEqual('', err)

        # Update initial standalone branch
        self.build_tree(['standalone/b'])
        tree1.add('b')
        tree1.commit('commit two')
        rev = branch1.repository.get_revision(branch1.last_revision())
        datestring_last = osutils.format_date(rev.timestamp, rev.timezone)

        # Out of date branched standalone branch will not be detected
        out, err = self.run_bzr('info -v branch')
        self.assertEqualDiff(
            """Standalone tree (format: knit)
Location:
  branch root: branch

Related branches:
    push branch: standalone
  parent branch: standalone

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: Branch format 5
    repository: Knit repository format 1

Control directory:
         1 branches

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 copied
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         1 revision
         0 days old
   first revision: %s
  latest revision: %s

Repository:
         1 revision
""" % (datestring_first, datestring_first,
       ), out)
        self.assertEqual('', err)

        # Out of date bound branch
        out, err = self.run_bzr('info -v bound')
        self.assertEqualDiff(
            """Checkout (format: knit)
Location:
       checkout root: bound
  checkout of branch: standalone

Related branches:
  parent branch: standalone

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: Branch format 5
    repository: %s

Control directory:
         1 branches

Branch is out of date: missing 1 revision.

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 copied
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         1 revision
         0 days old
   first revision: %s
  latest revision: %s

Repository:
         1 revision
""" % (branch3.repository._format.get_format_description(),
                datestring_first, datestring_first,
       ), out)
        self.assertEqual('', err)

        # Out of date checkout
        out, err = self.run_bzr('info -v checkout')
        self.assertEqualDiff(
            """Checkout (format: knit)
Location:
       checkout root: checkout
  checkout of branch: standalone

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: Branch format 5
    repository: %s

Control directory:
         1 branches

Branch is out of date: missing 1 revision.

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 copied
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         1 revision
         0 days old
   first revision: %s
  latest revision: %s

Repository:
         1 revision
""" % (branch4.repository._format.get_format_description(),
                datestring_first, datestring_first,
       ), out)
        self.assertEqual('', err)

        # Out of date lightweight checkout
        out, err = self.run_bzr('info lightcheckout --verbose')
        self.assertEqualDiff(
            """Lightweight checkout (format: %s)
Location:
  light checkout root: lightcheckout
   checkout of branch: standalone

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: Branch format 5
    repository: Knit repository format 1

Control directory:
         1 branches

Working tree is out of date: missing 1 revision.

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 copied
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         2 revisions
         0 days old
   first revision: %s
  latest revision: %s

Repository:
         2 revisions
""" % (format_description, datestring_first, datestring_last,), out)
        self.assertEqual('', err)

    def test_info_standalone_no_tree(self):
        # create standalone branch without a working tree
        format = controldir.format_registry.make_controldir('default')
        branch = self.make_branch('branch')
        repo = branch.repository
        out, err = self.run_bzr('info branch -v')
        self.assertEqualDiff(
            """Standalone branch (format: %s)
Location:
  branch root: branch

Format:
       control: Meta directory format 1
        branch: %s
    repository: %s

Control directory:
         1 branches

Branch history:
         0 revisions

Repository:
         0 revisions
""" % (info.describe_format(repo.controldir, repo, branch, None),
                format.get_branch_format().get_format_description(),
                format.repository_format.get_format_description(),
       ), out)
        self.assertEqual('', err)

    def test_info_shared_repository(self):
        format = controldir.format_registry.make_controldir('knit')
        transport = self.get_transport()

        # Create shared repository
        repo = self.make_repository('repo', shared=True, format=format)
        repo.set_make_working_trees(False)
        out, err = self.run_bzr('info -v repo')
        self.assertEqualDiff(
            """Shared repository (format: dirstate or dirstate-tags or knit)
Location:
  shared repository: %s

Format:
       control: Meta directory format 1
    repository: %s

Control directory:
         0 branches

Repository:
         0 revisions
""" % ('repo', format.repository_format.get_format_description(),
       ), out)
        self.assertEqual('', err)

        # Create branch inside shared repository
        repo.controldir.root_transport.mkdir('branch')
        branch1 = controldir.ControlDir.create_branch_convenience(
            'repo/branch', format=format)
        out, err = self.run_bzr('info -v repo/branch')
        self.assertEqualDiff(
            """Repository branch (format: dirstate or knit)
Location:
  shared repository: repo
  repository branch: repo/branch

Format:
       control: Meta directory format 1
        branch: %s
    repository: %s

Control directory:
         1 branches

Branch history:
         0 revisions

Repository:
         0 revisions
""" % (format.get_branch_format().get_format_description(),
                format.repository_format.get_format_description(),
       ), out)
        self.assertEqual('', err)

        # Create lightweight checkout
        transport.mkdir('tree')
        transport.mkdir('tree/lightcheckout')
        tree2 = branch1.create_checkout('tree/lightcheckout',
                                        lightweight=True)
        branch2 = tree2.branch
        self.assertCheckoutStatusOutput('-v tree/lightcheckout', tree2,
                                        shared_repo=repo, repo_branch=branch1, verbose=True)

        # Create normal checkout
        tree3 = branch1.create_checkout('tree/checkout')
        self.assertCheckoutStatusOutput('tree/checkout --verbose', tree3,
                                        verbose=True,
                                        light_checkout=False, repo_branch=branch1)
        # Update lightweight checkout
        self.build_tree(['tree/lightcheckout/a'])
        tree2.add('a')
        tree2.commit('commit one')
        rev = repo.get_revision(branch2.last_revision())
        datestring_first = osutils.format_date(rev.timestamp, rev.timezone)
        out, err = self.run_bzr('info tree/lightcheckout --verbose')
        self.assertEqualDiff(
            """Lightweight checkout (format: %s)
Location:
  light checkout root: tree/lightcheckout
   checkout of branch: repo/branch
    shared repository: repo

Format:
       control: Meta directory format 1
  working tree: Working tree format 6
        branch: %s
    repository: %s

Control directory:
         1 branches

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 copied
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         1 revision
         0 days old
   first revision: %s
  latest revision: %s

Repository:
         1 revision
""" % (self._repo_strings, format.get_branch_format().get_format_description(),
                format.repository_format.get_format_description(),
                datestring_first, datestring_first,
       ), out)
        self.assertEqual('', err)

        # Out of date checkout
        out, err = self.run_bzr('info -v tree/checkout')
        self.assertEqualDiff(
            """Checkout (format: unnamed)
Location:
       checkout root: tree/checkout
  checkout of branch: repo/branch

Format:
       control: Meta directory format 1
  working tree: Working tree format 6
        branch: %s
    repository: %s

Control directory:
         1 branches

Branch is out of date: missing 1 revision.

In the working tree:
         0 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 copied
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         0 revisions

Repository:
         0 revisions
""" % (format.get_branch_format().get_format_description(),
                format.repository_format.get_format_description(),
       ), out)
        self.assertEqual('', err)

        # Update checkout
        tree3.update()
        self.build_tree(['tree/checkout/b'])
        tree3.add('b')
        out, err = self.run_bzr('info tree/checkout --verbose')
        self.assertEqualDiff(
            """Checkout (format: unnamed)
Location:
       checkout root: tree/checkout
  checkout of branch: repo/branch

Format:
       control: Meta directory format 1
  working tree: Working tree format 6
        branch: %s
    repository: %s

Control directory:
         1 branches

In the working tree:
         1 unchanged
         0 modified
         1 added
         0 removed
         0 renamed
         0 copied
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         1 revision
         0 days old
   first revision: %s
  latest revision: %s

Repository:
         1 revision
""" % (format.get_branch_format().get_format_description(),
                format.repository_format.get_format_description(),
                datestring_first, datestring_first,
       ), out)
        self.assertEqual('', err)
        tree3.commit('commit two')

        # Out of date lightweight checkout
        rev = repo.get_revision(branch1.last_revision())
        datestring_last = osutils.format_date(rev.timestamp, rev.timezone)
        out, err = self.run_bzr('info tree/lightcheckout --verbose')
        self.assertEqualDiff(
            """Lightweight checkout (format: %s)
Location:
  light checkout root: tree/lightcheckout
   checkout of branch: repo/branch
    shared repository: repo

Format:
       control: Meta directory format 1
  working tree: Working tree format 6
        branch: %s
    repository: %s

Control directory:
         1 branches

Working tree is out of date: missing 1 revision.

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 copied
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         2 revisions
         0 days old
   first revision: %s
  latest revision: %s

Repository:
         2 revisions
""" % (self._repo_strings, format.get_branch_format().get_format_description(),
                format.repository_format.get_format_description(),
                datestring_first, datestring_last,
       ), out)
        self.assertEqual('', err)

        # Show info about shared branch
        out, err = self.run_bzr('info repo/branch --verbose')
        self.assertEqualDiff(
            """Repository branch (format: dirstate or knit)
Location:
  shared repository: repo
  repository branch: repo/branch

Format:
       control: Meta directory format 1
        branch: %s
    repository: %s

Control directory:
         1 branches

Branch history:
         2 revisions
         0 days old
   first revision: %s
  latest revision: %s

Repository:
         2 revisions
""" % (format.get_branch_format().get_format_description(),
                format.repository_format.get_format_description(),
                datestring_first, datestring_last,
       ), out)
        self.assertEqual('', err)

        # Show info about repository with revisions
        out, err = self.run_bzr('info -v repo')
        self.assertEqualDiff(
            """Shared repository (format: dirstate or dirstate-tags or knit)
Location:
  shared repository: repo

Format:
       control: Meta directory format 1
    repository: %s

Control directory:
         0 branches

Repository:
         2 revisions
""" % (format.repository_format.get_format_description(),
       ), out)
        self.assertEqual('', err)

    def test_info_shared_repository_with_trees(self):
        format = controldir.format_registry.make_controldir('knit')
        transport = self.get_transport()

        # Create shared repository with working trees
        repo = self.make_repository('repo', shared=True, format=format)
        repo.set_make_working_trees(True)
        out, err = self.run_bzr('info -v repo')
        self.assertEqualDiff(
            """Shared repository with trees (format: dirstate or dirstate-tags or knit)
Location:
  shared repository: repo

Format:
       control: Meta directory format 1
    repository: %s

Control directory:
         0 branches

Create working tree for new branches inside the repository.

Repository:
         0 revisions
""" % (format.repository_format.get_format_description(),
       ), out)
        self.assertEqual('', err)

        # Create two branches
        repo.controldir.root_transport.mkdir('branch1')
        branch1 = controldir.ControlDir.create_branch_convenience('repo/branch1',
                                                                  format=format)
        branch2 = branch1.controldir.sprout('repo/branch2').open_branch()

        # Empty first branch
        out, err = self.run_bzr('info repo/branch1 --verbose')
        self.assertEqualDiff(
            """Repository tree (format: knit)
Location:
  shared repository: repo
  repository branch: repo/branch1

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: %s
    repository: %s

Control directory:
         1 branches

In the working tree:
         0 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 copied
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         0 revisions

Repository:
         0 revisions
""" % (format.get_branch_format().get_format_description(),
                format.repository_format.get_format_description(),
       ), out)
        self.assertEqual('', err)

        # Update first branch
        self.build_tree(['repo/branch1/a'])
        tree1 = branch1.controldir.open_workingtree()
        tree1.add('a')
        tree1.commit('commit one')
        rev = repo.get_revision(branch1.last_revision())
        datestring_first = osutils.format_date(rev.timestamp, rev.timezone)
        out, err = self.run_bzr('info -v repo/branch1')
        self.assertEqualDiff(
            """Repository tree (format: knit)
Location:
  shared repository: repo
  repository branch: repo/branch1

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: %s
    repository: %s

Control directory:
         1 branches

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 copied
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         1 revision
         0 days old
   first revision: %s
  latest revision: %s

Repository:
         1 revision
""" % (format.get_branch_format().get_format_description(),
                format.repository_format.get_format_description(),
                datestring_first, datestring_first,
       ), out)
        self.assertEqual('', err)

        # Out of date second branch
        out, err = self.run_bzr('info repo/branch2 --verbose')
        self.assertEqualDiff(
            """Repository tree (format: knit)
Location:
  shared repository: repo
  repository branch: repo/branch2

Related branches:
  parent branch: repo/branch1

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: %s
    repository: %s

Control directory:
         1 branches

In the working tree:
         0 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 copied
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         0 revisions

Repository:
         1 revision
""" % (format.get_branch_format().get_format_description(),
                format.repository_format.get_format_description(),
       ), out)
        self.assertEqual('', err)

        # Update second branch
        tree2 = branch2.controldir.open_workingtree()
        tree2.pull(branch1)
        out, err = self.run_bzr('info -v repo/branch2')
        self.assertEqualDiff(
            """Repository tree (format: knit)
Location:
  shared repository: repo
  repository branch: repo/branch2

Related branches:
  parent branch: repo/branch1

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: %s
    repository: %s

Control directory:
         1 branches

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 copied
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         1 revision
         0 days old
   first revision: %s
  latest revision: %s

Repository:
         1 revision
""" % (format.get_branch_format().get_format_description(),
                format.repository_format.get_format_description(),
                datestring_first, datestring_first,
       ), out)
        self.assertEqual('', err)

        # Show info about repository with revisions
        out, err = self.run_bzr('info -v repo')
        self.assertEqualDiff(
            """Shared repository with trees (format: dirstate or dirstate-tags or knit)
Location:
  shared repository: repo

Format:
       control: Meta directory format 1
    repository: %s

Control directory:
         0 branches

Create working tree for new branches inside the repository.

Repository:
         1 revision
""" % (format.repository_format.get_format_description(),
       ),
            out)
        self.assertEqual('', err)

    def test_info_shared_repository_with_tree_in_root(self):
        format = controldir.format_registry.make_controldir('knit')
        transport = self.get_transport()

        # Create shared repository with working trees
        repo = self.make_repository('repo', shared=True, format=format)
        repo.set_make_working_trees(True)
        out, err = self.run_bzr('info -v repo')
        self.assertEqualDiff(
            """Shared repository with trees (format: dirstate or dirstate-tags or knit)
Location:
  shared repository: repo

Format:
       control: Meta directory format 1
    repository: %s

Control directory:
         0 branches

Create working tree for new branches inside the repository.

Repository:
         0 revisions
""" % (format.repository_format.get_format_description(),
       ), out)
        self.assertEqual('', err)

        # Create branch in root of repository
        control = repo.controldir
        branch = control.create_branch()
        control.create_workingtree()
        out, err = self.run_bzr('info -v repo')
        self.assertEqualDiff(
            """Repository tree (format: knit)
Location:
  shared repository: repo
  repository branch: repo

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: %s
    repository: %s

Control directory:
         1 branches

In the working tree:
         0 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 copied
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         0 revisions

Repository:
         0 revisions
""" % (format.get_branch_format().get_format_description(),
                format.repository_format.get_format_description(),
       ), out)
        self.assertEqual('', err)

    def test_info_repository_hook(self):
        format = controldir.format_registry.make_controldir('knit')

        def repo_info(repo, stats, outf):
            outf.write(u"more info\n")
        info.hooks.install_named_hook('repository', repo_info, None)
        # Create shared repository with working trees
        repo = self.make_repository('repo', shared=True, format=format)
        out, err = self.run_bzr('info -v repo')
        self.assertEqualDiff(
            """Shared repository with trees (format: dirstate or dirstate-tags or knit)
Location:
  shared repository: repo

Format:
       control: Meta directory format 1
    repository: %s

Control directory:
         0 branches

Create working tree for new branches inside the repository.

Repository:
         0 revisions
more info
""" % (format.repository_format.get_format_description(),
       ), out)
        self.assertEqual('', err)

    def test_info_unshared_repository_with_colocated_branches(self):
        format = controldir.format_registry.make_controldir('development-colo')
        transport = self.get_transport()

        # Create unshared repository
        repo = self.make_repository('repo', shared=False, format=format)
        repo.set_make_working_trees(True)
        repo.controldir.create_branch(name='foo')
        out, err = self.run_bzr('info repo')
        self.assertEqualDiff(
            """Unshared repository with trees and colocated branches (format: development-colo)
Location:
  repository: repo
""", out)
        self.assertEqual('', err)

    def assertCheckoutStatusOutput(self,
                                   command_string, lco_tree, shared_repo=None,
                                   repo_branch=None,
                                   tree_locked=False,
                                   branch_locked=False, repo_locked=False,
                                   verbose=False,
                                   light_checkout=True,
                                   checkout_root=None):
        """Check the output of info in a checkout.

        This is not quite a mirror of the info code: rather than using the
        tree being examined to predict output, it uses a bunch of flags which
        allow us, the test writers, to document what *should* be present in
        the output. Removing this separation would remove the value of the
        tests.

        :param path: the path to the light checkout.
        :param lco_tree: the tree object for the light checkout.
        :param shared_repo: A shared repository is in use, expect that in
            the output.
        :param repo_branch: A branch in a shared repository for non light
            checkouts.
        :param tree_locked: If true, expect the tree to be locked.
        :param branch_locked: If true, expect the branch to be locked.
        :param repo_locked: If true, expect the repository to be locked.
            Note that the lco_tree.branch.repository is inspected, and if is not
            actually locked then this parameter is overridden. This is because
            pack repositories do not have any public API for obtaining an
            exclusive repository wide lock.
        :param verbose: verbosity level: 2 or higher to show committers
        """
        def friendly_location(url):
            path = urlutils.unescape_for_display(url, 'ascii')
            try:
                return osutils.relpath(osutils.getcwd(), path)
            except errors.PathNotChild:
                return path

        if tree_locked:
            # We expect this to fail because of locking errors.
            # (A write-locked file cannot be read-locked
            # in the different process -- either on win32 or on linux).
            # This should be removed when the locking errors are fixed.
            self.expectFailure('OS locks are exclusive '
                               'for different processes (Bug #174055)',
                               self.run_brz_subprocess,
                               'info ' + command_string)
        out, err = self.run_bzr('info %s' % command_string)
        description = {
            (True, True): 'Lightweight checkout',
            (True, False): 'Repository checkout',
            (False, True): 'Lightweight checkout',
            (False, False): 'Checkout',
            }[(shared_repo is not None, light_checkout)]
        format = {True: self._repo_strings,
                  False: 'unnamed'}[light_checkout]
        if repo_locked:
            repo_locked = lco_tree.branch.repository.get_physical_lock_status()
        if repo_locked or branch_locked or tree_locked:
            def locked_message(a_bool):
                if a_bool:
                    return 'locked'
                else:
                    return 'unlocked'
            expected_lock_output = (
                "\n"
                "Lock status:\n"
                "  working tree: %s\n"
                "        branch: %s\n"
                "    repository: %s\n" % (
                    locked_message(tree_locked),
                    locked_message(branch_locked),
                    locked_message(repo_locked)))
        else:
            expected_lock_output = ''
        tree_data = ''
        extra_space = ''
        if light_checkout:
            tree_data = ("  light checkout root: %s\n" %
                         friendly_location(lco_tree.controldir.root_transport.base))
            extra_space = ' '
        if lco_tree.branch.get_bound_location() is not None:
            tree_data += ("%s       checkout root: %s\n" % (extra_space,
                                                            friendly_location(lco_tree.branch.controldir.root_transport.base)))
        if shared_repo is not None:
            branch_data = (
                "   checkout of branch: %s\n"
                "    shared repository: %s\n" %
                (friendly_location(repo_branch.controldir.root_transport.base),
                 friendly_location(shared_repo.controldir.root_transport.base)))
        elif repo_branch is not None:
            branch_data = (
                "%s  checkout of branch: %s\n" %
                (extra_space,
                 friendly_location(repo_branch.controldir.root_transport.base)))
        else:
            branch_data = ("   checkout of branch: %s\n" %
                           lco_tree.branch.controldir.root_transport.base)

        if verbose >= 2:
            verbose_info = '         0 committers\n'
        else:
            verbose_info = ''

        self.assertEqualDiff(
            """%s (format: %s)
Location:
%s%s
Format:
       control: Meta directory format 1
  working tree: %s
        branch: %s
    repository: %s
%s
Control directory:
         1 branches

In the working tree:
         0 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 copied
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         0 revisions
%s
Repository:
         0 revisions
""" % (description,
                format,
                tree_data,
                branch_data,
                lco_tree._format.get_format_description(),
                lco_tree.branch._format.get_format_description(),
                lco_tree.branch.repository._format.get_format_description(),
                expected_lock_output,
                verbose_info,
       ), out)
        self.assertEqual('', err)

    def test_info_locking(self):
        transport = self.get_transport()
        # Create shared repository with a branch
        repo = self.make_repository('repo', shared=True,
                                    format=bzrdir.BzrDirMetaFormat1())
        repo.set_make_working_trees(False)
        repo.controldir.root_transport.mkdir('branch')
        repo_branch = controldir.ControlDir.create_branch_convenience(
            'repo/branch', format=bzrdir.BzrDirMetaFormat1())
        # Do a heavy checkout
        transport.mkdir('tree')
        transport.mkdir('tree/checkout')
        co_branch = controldir.ControlDir.create_branch_convenience(
            'tree/checkout', format=bzrdir.BzrDirMetaFormat1())
        co_branch.bind(repo_branch)
        # Do a light checkout of the heavy one
        transport.mkdir('tree/lightcheckout')
        lco_dir = bzrdir.BzrDirMetaFormat1().initialize('tree/lightcheckout')
        lco_dir.set_branch_reference(co_branch)
        lco_dir.create_workingtree()
        lco_tree = lco_dir.open_workingtree()

        # Test all permutations of locking the working tree, branch and repository
        # W B R

        # U U U
        self.assertCheckoutStatusOutput('-v tree/lightcheckout', lco_tree,
                                        repo_branch=repo_branch,
                                        verbose=True, light_checkout=True)
        # U U L
        with lco_tree.branch.repository.lock_write():
            self.assertCheckoutStatusOutput('-v tree/lightcheckout',
                                            lco_tree, repo_branch=repo_branch,
                                            repo_locked=True, verbose=True, light_checkout=True)
        # U L L
        with lco_tree.branch.lock_write():
            self.assertCheckoutStatusOutput('-v tree/lightcheckout',
                                            lco_tree,
                                            branch_locked=True,
                                            repo_locked=True,
                                            repo_branch=repo_branch,
                                            verbose=True)
        # L L L
        with lco_tree.lock_write():
            self.assertCheckoutStatusOutput('-v tree/lightcheckout',
                                            lco_tree, repo_branch=repo_branch,
                                            tree_locked=True,
                                            branch_locked=True,
                                            repo_locked=True,
                                            verbose=True)
        # L L U
        with lco_tree.lock_write(), lco_tree.branch.repository.unlock():
            self.assertCheckoutStatusOutput('-v tree/lightcheckout',
                                            lco_tree, repo_branch=repo_branch,
                                            tree_locked=True,
                                            branch_locked=True,
                                            verbose=True)
        # L U U
        with lco_tree.lock_write(), lco_tree.branch.unlock():
            self.assertCheckoutStatusOutput('-v tree/lightcheckout',
                                            lco_tree, repo_branch=repo_branch,
                                            tree_locked=True,
                                            verbose=True)
        # L U L
        with lco_tree.lock_write(), lco_tree.branch.unlock(), \
                lco_tree.branch.repository.lock_write():
            self.assertCheckoutStatusOutput('-v tree/lightcheckout',
                                            lco_tree, repo_branch=repo_branch,
                                            tree_locked=True,
                                            repo_locked=True,
                                            verbose=True)
        # U L U
        with lco_tree.branch.lock_write(), lco_tree.branch.repository.unlock():
            self.assertCheckoutStatusOutput('-v tree/lightcheckout',
                                            lco_tree, repo_branch=repo_branch,
                                            branch_locked=True,
                                            verbose=True)

        if sys.platform == 'win32':
            self.knownFailure('Win32 cannot run "brz info"'
                              ' when the tree is locked.')

    def test_info_stacked(self):
        # We have a mainline
        trunk_tree = self.make_branch_and_tree('mainline',
                                               format='1.6')
        trunk_tree.commit('mainline')
        # and a branch from it which is stacked
        new_dir = trunk_tree.controldir.sprout('newbranch', stacked=True)
        out, err = self.run_bzr('info newbranch')
        self.assertEqual(
            """Standalone tree (format: 1.6)
Location:
  branch root: newbranch

Related branches:
  parent branch: mainline
     stacked on: mainline
""", out)
        self.assertEqual("", err)

    def test_info_revinfo_optional(self):
        tree = self.make_branch_and_tree('.')

        def last_revision_info(self):
            raise errors.UnsupportedOperation(last_revision_info, self)
        self.overrideAttr(
            branch.Branch, "last_revision_info", last_revision_info)
        out, err = self.run_bzr('info -v .')
        self.assertEqual(
            """Standalone tree (format: 2a)
Location:
  branch root: .

Format:
       control: Meta directory format 1
  working tree: Working tree format 6
        branch: Branch format 7
    repository: Repository format 2a - rich roots, group compression and chk inventories

Control directory:
         1 branches

In the working tree:
         0 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 copied
         0 unknown
         0 ignored
         0 versioned subdirectories
""", out)
        self.assertEqual("", err)

    def test_info_shows_colocated_branches(self):
        bzrdir = self.make_branch('.', format='development-colo').controldir
        bzrdir.create_branch(name="colo1")
        bzrdir.create_branch(name="colo2")
        bzrdir.create_branch(name="colo3")
        out, err = self.run_bzr('info -v .')
        self.assertEqualDiff(
            """Standalone branch (format: development-colo)
Location:
  branch root: .

Format:
       control: Meta directory format 1 with support for colocated branches
        branch: Branch format 7
    repository: Repository format 2a - rich roots, group compression and chk inventories

Control directory:
         4 branches

Branch history:
         0 revisions

Repository:
         0 revisions
""", out)
        self.assertEqual("", err)
