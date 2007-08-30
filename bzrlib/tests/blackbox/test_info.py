# Copyright (C) 2006, 2007 Canonical Ltd
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


"""Tests for the info command of bzr."""

import os
import sys

import bzrlib
from bzrlib import (
    bzrdir,
    osutils,
    repository,
    urlutils,
    )
from bzrlib.osutils import format_date
from bzrlib.tests import TestSkipped
from bzrlib.tests.blackbox import ExternalBase


class TestInfo(ExternalBase):

    def test_info_non_existing(self):
        if sys.platform == "win32":
            location = "C:/i/do/not/exist/"
        else:
            location = "/i/do/not/exist/"
        out, err = self.run_bzr('info '+location, retcode=3)
        self.assertEqual(out, '')
        self.assertEqual(err, 'bzr: ERROR: Not a branch: "%s".\n' % location)

    def test_info_standalone(self):
        transport = self.get_transport()

        # Create initial standalone branch
        tree1 = self.make_branch_and_tree('standalone', 'weave')
        self.build_tree(['standalone/a'])
        tree1.add('a')
        branch1 = tree1.branch

        out, err = self.run_bzr('info standalone')
        self.assertEqualDiff(
"""Standalone tree (format: weave)
Location:
  branch root: standalone
""", out)
        self.assertEqual('', err)

        out, err = self.run_bzr('info standalone -v')
        self.assertEqualDiff(
"""Standalone tree (format: weave)
Location:
  branch root: standalone

Format:
       control: All-in-one format 6
  working tree: Working tree format 2
        branch: Branch format 4
    repository: Weave repository format 6

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

Repository:
         0 revisions
         0 KiB
""", out)
        self.assertEqual('', err)
        tree1.commit('commit one')
        rev = branch1.repository.get_revision(branch1.revision_history()[0])
        datestring_first = format_date(rev.timestamp, rev.timezone)

        # Branch standalone with push location
        branch2 = branch1.bzrdir.sprout('branch').open_branch()
        branch2.set_push_location(branch1.bzrdir.root_transport.base)

        out, err = self.run_bzr('info branch')
        self.assertEqualDiff(
"""Standalone tree (format: weave)
Location:
  branch root: branch

Related branches:
    push branch: standalone
  parent branch: standalone
""", out)
        self.assertEqual('', err)

        out, err = self.run_bzr('info branch --verbose')
        self.assertEqualDiff(
"""Standalone tree (format: weave)
Location:
  branch root: branch

Related branches:
    push branch: standalone
  parent branch: standalone

Format:
       control: All-in-one format 6
  working tree: Working tree format 2
        branch: Branch format 4
    repository: Weave repository format 6

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

Repository:
         1 revision
         %d KiB
""" % (datestring_first, datestring_first,
       # poking at _revision_store isn't all that clean, but neither is
       # having the ui test dependent on the exact overhead of a given store.
       branch2.repository._revision_store.total_size(
        branch2.repository.get_transaction())[1] / 1024,
       ), out)
        self.assertEqual('', err)

        # Branch and bind to standalone, needs upgrade to metadir
        # (creates backup as unknown)
        branch1.bzrdir.sprout('bound')
        knit1_format = bzrdir.format_registry.make_bzrdir('knit')
        bzrlib.upgrade.upgrade('bound', knit1_format)
        branch3 = bzrlib.bzrdir.BzrDir.open('bound').open_branch()
        branch3.bind(branch1)
        bound_tree = branch3.bzrdir.open_workingtree()
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

Repository:
         1 revision
         %d KiB
""" % (bound_tree._format.get_format_description(),
       branch3._format.get_format_description(),
       branch3.repository._format.get_format_description(),
       datestring_first, datestring_first,
       # poking at _revision_store isn't all that clean, but neither is
       # having the ui test dependent on the exact overhead of a given store.
       branch3.repository._revision_store.total_size(
        branch3.repository.get_transaction())[1] / 1024,
       ), out)
        self.assertEqual('', err)

        # Checkout standalone (same as above, but does not have parent set)
        branch4 = bzrlib.bzrdir.BzrDir.create_branch_convenience('checkout',
            format=knit1_format)
        branch4.bind(branch1)
        branch4.bzrdir.open_workingtree().update()
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

Repository:
         1 revision
         %d KiB
""" % (branch4.repository._format.get_format_description(),
       datestring_first, datestring_first,
       # poking at _revision_store isn't all that clean, but neither is
       # having the ui test dependent on the exact overhead of a given store.
       branch4.repository._revision_store.total_size(
        branch4.repository.get_transaction())[1] / 1024,
       ), out)
        self.assertEqual('', err)

        # Lightweight checkout (same as above, different branch and repository)
        tree5 = branch1.create_checkout('lightcheckout', lightweight=True)
        branch5 = tree5.branch
        out, err = self.run_bzr('info -v lightcheckout')
        self.assertEqualDiff(
"""Lightweight checkout (format: dirstate or dirstate-tags)
Location:
  light checkout root: lightcheckout
   checkout of branch: standalone

Format:
       control: Meta directory format 1
  working tree: Working tree format 4
        branch: Branch format 4
    repository: Weave repository format 6

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

Repository:
         1 revision
         0 KiB
""" % (datestring_first, datestring_first,), out)
        self.assertEqual('', err)

        # Update initial standalone branch
        self.build_tree(['standalone/b'])
        tree1.add('b')
        tree1.commit('commit two')
        rev = branch1.repository.get_revision(branch1.revision_history()[-1])
        datestring_last = format_date(rev.timestamp, rev.timezone)

        # Out of date branched standalone branch will not be detected
        out, err = self.run_bzr('info -v branch')
        self.assertEqualDiff(
"""Standalone tree (format: weave)
Location:
  branch root: branch

Related branches:
    push branch: standalone
  parent branch: standalone

Format:
       control: All-in-one format 6
  working tree: Working tree format 2
        branch: Branch format 4
    repository: Weave repository format 6

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

Repository:
         1 revision
         0 KiB
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

Repository:
         1 revision
         %d KiB
""" % (branch3.repository._format.get_format_description(),
       datestring_first, datestring_first,
       # poking at _revision_store isn't all that clean, but neither is
       # having the ui test dependent on the exact overhead of a given store.
       branch3.repository._revision_store.total_size(
        branch3.repository.get_transaction())[1] / 1024,
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

Repository:
         1 revision
         %d KiB
""" % (branch4.repository._format.get_format_description(),
       datestring_first, datestring_first,
       # poking at _revision_store isn't all that clean, but neither is
       # having the ui test dependent on the exact overhead of a given store.
       branch4.repository._revision_store.total_size(
        branch4.repository.get_transaction())[1] / 1024,
       ), out)
        self.assertEqual('', err)

        # Out of date lightweight checkout
        out, err = self.run_bzr('info lightcheckout --verbose')
        self.assertEqualDiff(
"""Lightweight checkout (format: dirstate or dirstate-tags)
Location:
  light checkout root: lightcheckout
   checkout of branch: standalone

Format:
       control: Meta directory format 1
  working tree: Working tree format 4
        branch: Branch format 4
    repository: Weave repository format 6

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

Repository:
         2 revisions
         0 KiB
""" % (datestring_first, datestring_last,), out)
        self.assertEqual('', err)

    def test_info_standalone_no_tree(self):
        # create standalone branch without a working tree
        format = bzrdir.format_registry.make_bzrdir('default')
        branch = self.make_branch('branch')
        repo = branch.repository
        out, err = self.run_bzr('info branch -v')
        self.assertEqualDiff(
"""Standalone branch (format: dirstate-tags)
Location:
  branch root: branch

Format:
       control: Meta directory format 1
        branch: %s
    repository: %s

Branch history:
         0 revisions
         0 committers

Repository:
         0 revisions
         0 KiB
""" % (format.get_branch_format().get_format_description(),
       format.repository_format.get_format_description(),
       ), out)
        self.assertEqual('', err)

    def test_info_shared_repository(self):
        format = bzrdir.format_registry.make_bzrdir('knit')
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

Repository:
         0 revisions
         0 KiB
""" % ('repo', format.repository_format.get_format_description(),
       ), out)
        self.assertEqual('', err)

        # Create branch inside shared repository
        repo.bzrdir.root_transport.mkdir('branch')
        branch1 = repo.bzrdir.create_branch_convenience('repo/branch',
            format=format)
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

Branch history:
         0 revisions
         0 committers

Repository:
         0 revisions
         0 KiB
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
        rev = repo.get_revision(branch2.revision_history()[0])
        datestring_first = format_date(rev.timestamp, rev.timezone)
        out, err = self.run_bzr('info tree/lightcheckout --verbose')
        self.assertEqualDiff(
"""Lightweight checkout (format: dirstate or dirstate-tags)
Location:
  light checkout root: tree/lightcheckout
   checkout of branch: repo/branch
    shared repository: repo

Format:
       control: Meta directory format 1
  working tree: Working tree format 4
        branch: %s
    repository: %s

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

Repository:
         1 revision
         %d KiB
""" % (format.get_branch_format().get_format_description(),
       format.repository_format.get_format_description(),
       datestring_first, datestring_first,
       # poking at _revision_store isn't all that clean, but neither is
       # having the ui test dependent on the exact overhead of a given store.
       repo._revision_store.total_size(repo.get_transaction())[1] / 1024,
       ), out)
        self.assertEqual('', err)

        # Out of date checkout
        out, err = self.run_bzr('info -v tree/checkout')
        self.assertEqualDiff(
"""Checkout (format: dirstate)
Location:
       checkout root: tree/checkout
  checkout of branch: repo/branch

Format:
       control: Meta directory format 1
  working tree: Working tree format 4
        branch: %s
    repository: %s

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

Repository:
         0 revisions
         0 KiB
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
"""Checkout (format: dirstate)
Location:
       checkout root: tree/checkout
  checkout of branch: repo/branch

Format:
       control: Meta directory format 1
  working tree: Working tree format 4
        branch: %s
    repository: %s

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

Repository:
         1 revision
         %d KiB
""" % (format.get_branch_format().get_format_description(),
       format.repository_format.get_format_description(),
       datestring_first, datestring_first,
       # poking at _revision_store isn't all that clean, but neither is
       # having the ui test dependent on the exact overhead of a given store.
       repo._revision_store.total_size(repo.get_transaction())[1] / 1024,
       ), out)
        self.assertEqual('', err)
        tree3.commit('commit two')

        # Out of date lightweight checkout
        rev = repo.get_revision(branch1.revision_history()[-1])
        datestring_last = format_date(rev.timestamp, rev.timezone)
        out, err = self.run_bzr('info tree/lightcheckout --verbose')
        self.assertEqualDiff(
"""Lightweight checkout (format: dirstate or dirstate-tags)
Location:
  light checkout root: tree/lightcheckout
   checkout of branch: repo/branch
    shared repository: repo

Format:
       control: Meta directory format 1
  working tree: Working tree format 4
        branch: %s
    repository: %s

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

Repository:
         2 revisions
         %d KiB
""" % (format.get_branch_format().get_format_description(),
       format.repository_format.get_format_description(),
       datestring_first, datestring_last,
       # poking at _revision_store isn't all that clean, but neither is
       # having the ui test dependent on the exact overhead of a given store.
       repo._revision_store.total_size(repo.get_transaction())[1] / 1024,
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

Branch history:
         2 revisions
         1 committer
         0 days old
   first revision: %s
  latest revision: %s

Repository:
         2 revisions
         %d KiB
""" % (format.get_branch_format().get_format_description(),
       format.repository_format.get_format_description(),
       datestring_first, datestring_last,
       # poking at _revision_store isn't all that clean, but neither is
       # having the ui test dependent on the exact overhead of a given store.
       repo._revision_store.total_size(repo.get_transaction())[1] / 1024,
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

Repository:
         2 revisions
         %d KiB
""" % (format.repository_format.get_format_description(),
       # poking at _revision_store isn't all that clean, but neither is
       # having the ui test dependent on the exact overhead of a given store.
       repo._revision_store.total_size(repo.get_transaction())[1] / 1024,
       ), out)
        self.assertEqual('', err)

    def test_info_shared_repository_with_trees(self):
        format = bzrdir.format_registry.make_bzrdir('knit')
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

Create working tree for new branches inside the repository.

Repository:
         0 revisions
         0 KiB
""" % (format.repository_format.get_format_description(),
       ), out)
        self.assertEqual('', err)

        # Create two branches
        repo.bzrdir.root_transport.mkdir('branch1')
        branch1 = repo.bzrdir.create_branch_convenience('repo/branch1',
            format=format)
        branch2 = branch1.bzrdir.sprout('repo/branch2').open_branch()

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

Repository:
         0 revisions
         0 KiB
""" % (format.get_branch_format().get_format_description(),
       format.repository_format.get_format_description(),
       ), out)
        self.assertEqual('', err)

        # Update first branch
        self.build_tree(['repo/branch1/a'])
        tree1 = branch1.bzrdir.open_workingtree()
        tree1.add('a')
        tree1.commit('commit one')
        rev = repo.get_revision(branch1.revision_history()[0])
        datestring_first = format_date(rev.timestamp, rev.timezone)
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

Repository:
         1 revision
         %d KiB
""" % (format.get_branch_format().get_format_description(),
       format.repository_format.get_format_description(),
       datestring_first, datestring_first,
       # poking at _revision_store isn't all that clean, but neither is
       # having the ui test dependent on the exact overhead of a given store.
       repo._revision_store.total_size(repo.get_transaction())[1] / 1024,
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

Repository:
         1 revision
         %d KiB
""" % (format.get_branch_format().get_format_description(),
       format.repository_format.get_format_description(),
       # poking at _revision_store isn't all that clean, but neither is
       # having the ui test dependent on the exact overhead of a given store.
       repo._revision_store.total_size(repo.get_transaction())[1] / 1024,
       ), out)
        self.assertEqual('', err)

        # Update second branch
        tree2 = branch2.bzrdir.open_workingtree()
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

Repository:
         1 revision
         %d KiB
""" % (format.get_branch_format().get_format_description(),
       format.repository_format.get_format_description(),
       datestring_first, datestring_first,
       # poking at _revision_store isn't all that clean, but neither is
       # having the ui test dependent on the exact overhead of a given store.
       repo._revision_store.total_size(repo.get_transaction())[1] / 1024,
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

Create working tree for new branches inside the repository.

Repository:
         1 revision
         %d KiB
""" % (format.repository_format.get_format_description(),
       # poking at _revision_store isn't all that clean, but neither is
       # having the ui test dependent on the exact overhead of a given store.
       repo._revision_store.total_size(repo.get_transaction())[1] / 1024,
       ),
       out)
        self.assertEqual('', err)
    
    def test_info_shared_repository_with_tree_in_root(self):
        format = bzrdir.format_registry.make_bzrdir('knit')
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

Create working tree for new branches inside the repository.

Repository:
         0 revisions
         0 KiB
""" % (format.repository_format.get_format_description(),
       ), out)
        self.assertEqual('', err)

        # Create branch in root of repository
        control = repo.bzrdir
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

Repository:
         0 revisions
         0 KiB
""" % (format.get_branch_format().get_format_description(),
       format.repository_format.get_format_description(),
       ), out)
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
        :param verbose: If true, expect verbose output
        """
        def friendly_location(url):
            path = urlutils.unescape_for_display(url, 'ascii')
            try:
                return osutils.relpath(os.getcwd(), path)
            except errors.PathNotChild:
                return path

        if tree_locked and sys.platform == 'win32':
            # We expect this to fail because of locking errors. (A write-locked
            # file cannot be read-locked in the same process).
            # This should be removed when the locking errors are fixed.
            args = command_string.split(' ')
            self.run_bzr_error([], 'info', *args)
            return
        out, err = self.run_bzr('info %s' % command_string)
        description = {
            (True, True): 'Lightweight checkout',
            (True, False): 'Repository checkout',
            (False, True): 'Lightweight checkout',
            (False, False): 'Checkout',
            }[(shared_repo is not None, light_checkout)]
        format = {True: 'dirstate or dirstate-tags',
                  False: 'dirstate'}[light_checkout]
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
                friendly_location(lco_tree.bzrdir.root_transport.base))
            extra_space = ' '
        if lco_tree.branch.get_bound_location() is not None:
            tree_data += ("%s       checkout root: %s\n" % (extra_space,
                friendly_location(lco_tree.branch.bzrdir.root_transport.base)))
        if shared_repo is not None:
            branch_data = (
                "   checkout of branch: %s\n"
                "    shared repository: %s\n" %
                (friendly_location(repo_branch.bzrdir.root_transport.base),
                 friendly_location(shared_repo.bzrdir.root_transport.base)))
        elif repo_branch is not None:
            branch_data = (
                "%s  checkout of branch: %s\n" %
                (extra_space,
                 friendly_location(repo_branch.bzrdir.root_transport.base)))
        else:
            branch_data = ("   checkout of branch: %s\n" %
                lco_tree.branch.bzrdir.root_transport.base)
        
        if verbose:
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
%s
Repository:
         0 revisions
         0 KiB
""" %  (description,
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
                                    format=bzrlib.bzrdir.BzrDirMetaFormat1())
        repo.set_make_working_trees(False)
        repo.bzrdir.root_transport.mkdir('branch')
        repo_branch = repo.bzrdir.create_branch_convenience('repo/branch',
                                    format=bzrlib.bzrdir.BzrDirMetaFormat1())
        # Do a heavy checkout
        transport.mkdir('tree')
        transport.mkdir('tree/checkout')
        co_branch = bzrlib.bzrdir.BzrDir.create_branch_convenience('tree/checkout',
            format=bzrlib.bzrdir.BzrDirMetaFormat1())
        co_branch.bind(repo_branch)
        # Do a light checkout of the heavy one
        transport.mkdir('tree/lightcheckout')
        lco_dir = bzrlib.bzrdir.BzrDirMetaFormat1().initialize('tree/lightcheckout')
        bzrlib.branch.BranchReferenceFormat().initialize(lco_dir, co_branch)
        lco_dir.create_workingtree()
        lco_tree = lco_dir.open_workingtree()

        # Test all permutations of locking the working tree, branch and repository
        # W B R

        # U U U
        self.assertCheckoutStatusOutput('-v tree/lightcheckout', lco_tree,
                                        repo_branch=repo_branch,
                                        verbose=True, light_checkout=True)
        # U U L
        lco_tree.branch.repository.lock_write()
        try:
            self.assertCheckoutStatusOutput('-v tree/lightcheckout',
            lco_tree, repo_branch=repo_branch,
            repo_locked=True, verbose=True, light_checkout=True)
        finally:
            lco_tree.branch.repository.unlock()
        # U L L
        lco_tree.branch.lock_write()
        try:
            self.assertCheckoutStatusOutput('-v tree/lightcheckout',
            lco_tree,
            branch_locked=True,
            repo_locked=True,
            repo_branch=repo_branch,
            verbose=True)
        finally:
            lco_tree.branch.unlock()
        # L L L
        lco_tree.lock_write()
        try:
            self.assertCheckoutStatusOutput('-v tree/lightcheckout',
            lco_tree, repo_branch=repo_branch,
            tree_locked=True,
            branch_locked=True,
            repo_locked=True,
            verbose=True)
        finally:
            lco_tree.unlock()
        # L L U
        lco_tree.lock_write()
        lco_tree.branch.repository.unlock()
        try:
            self.assertCheckoutStatusOutput('-v tree/lightcheckout',
            lco_tree, repo_branch=repo_branch,
            tree_locked=True,
            branch_locked=True,
            verbose=True)
        finally:
            lco_tree.branch.repository.lock_write()
            lco_tree.unlock()
        # L U U
        lco_tree.lock_write()
        lco_tree.branch.unlock()
        try:
            self.assertCheckoutStatusOutput('-v tree/lightcheckout',
            lco_tree, repo_branch=repo_branch,
            tree_locked=True,
            verbose=True)
        finally:
            lco_tree.branch.lock_write()
            lco_tree.unlock()
        # L U L
        lco_tree.lock_write()
        lco_tree.branch.unlock()
        lco_tree.branch.repository.lock_write()
        try:
            self.assertCheckoutStatusOutput('-v tree/lightcheckout',
            lco_tree, repo_branch=repo_branch,
            tree_locked=True,
            repo_locked=True,
            verbose=True)
        finally:
            lco_tree.branch.repository.unlock()
            lco_tree.branch.lock_write()
            lco_tree.unlock()
        # U L U
        lco_tree.branch.lock_write()
        lco_tree.branch.repository.unlock()
        try:
            self.assertCheckoutStatusOutput('-v tree/lightcheckout',
            lco_tree, repo_branch=repo_branch,
            branch_locked=True,
            verbose=True)
        finally:
            lco_tree.branch.repository.lock_write()
            lco_tree.branch.unlock()

        if sys.platform == 'win32':
            self.knownFailure('Win32 cannot run "bzr info"'
                              ' when the tree is locked.')

    def test_info_locking_oslocks(self):
        if sys.platform == "win32":
            raise TestSkipped("don't use oslocks on win32 in unix manner")

        tree = self.make_branch_and_tree('branch',
                                         format=bzrlib.bzrdir.BzrDirFormat6())

        # Test all permutations of locking the working tree, branch and repository
        # XXX: Well not yet, as we can't query oslocks yet. Currently, it's
        # implemented by raising NotImplementedError and get_physical_lock_status()
        # always returns false. This makes bzr info hide the lock status.  (Olaf)
        # W B R

        # U U U
        out, err = self.run_bzr('info -v branch')
        self.assertEqualDiff(
"""Standalone tree (format: weave)
Location:
  branch root: %s

Format:
       control: All-in-one format 6
  working tree: Working tree format 2
        branch: Branch format 4
    repository: %s

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

Repository:
         0 revisions
         0 KiB
""" % ('branch', tree.branch.repository._format.get_format_description(),
       ), out)
        self.assertEqual('', err)
        # L L L
        tree.lock_write()
        out, err = self.run_bzr('info -v branch')
        self.assertEqualDiff(
"""Standalone tree (format: weave)
Location:
  branch root: %s

Format:
       control: All-in-one format 6
  working tree: Working tree format 2
        branch: Branch format 4
    repository: %s

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

Repository:
         0 revisions
         0 KiB
""" % ('branch', tree.branch.repository._format.get_format_description(),
       ), out)
        self.assertEqual('', err)
        tree.unlock()
