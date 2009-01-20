# Copyright (C) 2007 Canonical Ltd
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

"""Tests for interfacing with a Git Repository"""

from bzrlib import (
    errors,
    inventory,
    revision,
    )
from bzrlib.repository import Repository

from bzrlib.plugins.git import (
    dir,
    git,
    repository,
    tests,
    )
from bzrlib.plugins.git.mapping import default_mapping


class TestGitRepositoryFeatures(tests.TestCaseInTempDir):
    """Feature tests for GitRepository."""

    _test_needs_features = [tests.GitCommandFeature]

    def test_open_existing(self):
        tests.run_git('init')

        repo = Repository.open('.')
        self.assertIsInstance(repo, repository.GitRepository)

    def test_has_git_repo(self):
        tests.run_git('init')

        repo = Repository.open('.')
        self.assertIsInstance(repo._git, git.repo.Repo)

    def test_get_revision(self):
        # GitRepository.get_revision gives a Revision object.

        # Create a git repository with a revision.
        tests.run_git('init')
        builder = tests.GitBranchBuilder()
        builder.set_file('a', 'text for a\n', False)
        commit_handle = builder.commit('Joe Foo <joe@foo.com>', u'message')
        mapping = builder.finish()
        commit_id = mapping[commit_handle]

        # Get the corresponding Revision object.
        revid = default_mapping.revision_id_foreign_to_bzr(commit_id)
        repo = Repository.open('.')
        rev = repo.get_revision(revid)
        self.assertIsInstance(rev, revision.Revision)

    def test_get_revision_unknown(self):
        tests.run_git('init')

        repo = Repository.open('.')
        self.assertRaises(errors.NoSuchRevision, repo.get_revision, "bla")

    def simple_commit(self):
        # Create a git repository with some interesting files in a revision.
        tests.run_git('init')
        builder = tests.GitBranchBuilder()
        builder.set_file('data', 'text\n', False)
        builder.set_file('executable', 'content', True)
        builder.set_link('link', 'broken')
        builder.set_file('subdir/subfile', 'subdir text\n', False)
        commit_handle = builder.commit('Joe Foo <joe@foo.com>', u'message',
            timestamp=1205433193)
        mapping = builder.finish()
        return mapping[commit_handle]

    def test_revision_tree(self):
        commit_id = self.simple_commit()
        revid = default_mapping.revision_id_foreign_to_bzr(commit_id)
        repo = Repository.open('.')
        tree = repo.revision_tree(revid)
        self.assertEquals(tree.get_revision_id(), revid)
        self.assertEquals("text\n", tree.get_file_text(tree.path2id("data")))

    def test_get_inventory(self):
        # GitRepository.get_inventory gives a GitInventory object with
        # plausible entries for typical cases.

        commit_id = self.simple_commit()

        # Get the corresponding Inventory object.
        revid = default_mapping.revision_id_foreign_to_bzr(commit_id)
        repo = Repository.open('.')
        inv = repo.get_inventory(revid)
        self.assertIsInstance(inv, inventory.Inventory)
        printed_inv = '\n'.join(
            repr((path, entry.executable, entry))
            for path, entry in inv.iter_entries())
        self.assertEqualDiff(
            printed_inv,
            "('', False, InventoryDirectory('TREE_ROOT', u'', parent_id=None,"
            " revision='"+default_mapping.revision_id_foreign_to_bzr("69c39cfa65962f3cf16b9b3eb08a15954e9d8590")+"'))\n"
            "(u'data', False, InventoryFile('data', u'data',"
            " parent_id='TREE_ROOT',"
            " sha1='aa785adca3fcdfe1884ae840e13c6d294a2414e8', len=5))\n"
            "(u'executable', True, InventoryFile('executable', u'executable',"
            " parent_id='TREE_ROOT',"
            " sha1='040f06fd774092478d450774f5ba30c5da78acc8', len=7))\n"
            "(u'link', False, InventoryLink('link', u'link',"
            " parent_id='TREE_ROOT', revision='"+default_mapping.revision_id_foreign_to_bzr("69c39cfa65962f3cf16b9b3eb08a15954e9d8590")+"'))\n"
            "(u'subdir', False, InventoryDirectory('subdir', u'subdir',"
            " parent_id='TREE_ROOT', revision='"+default_mapping.revision_id_foreign_to_bzr("69c39cfa65962f3cf16b9b3eb08a15954e9d8590")+"'))\n"
            "(u'subdir/subfile', False, InventoryFile('subdir/subfile',"
            " u'subfile', parent_id='subdir',"
            " sha1='67b75c3e49f31fcadddbf9df6a1d8be8c3e44290', len=12))")


class TestGitRepository(tests.TestCaseWithTransport):

    def setUp(self):
        tests.TestCaseWithTransport.setUp(self)
        git.repo.Repo.create(self.test_dir)
        self.git_repo = Repository.open(self.test_dir)

    def test_supports_rich_root(self):
        repo = self.git_repo
        self.assertEqual(repo.supports_rich_root(), True)

    def test_get_signature_text(self):
        self.assertRaises(errors.NoSuchRevision, self.git_repo.get_signature_text, revision.NULL_REVISION)

    def test_has_signature_for_revision_id(self):
        self.assertEquals(False, self.git_repo.has_signature_for_revision_id(revision.NULL_REVISION))

    def test_all_revision_ids_none(self):
        self.assertEquals(set(), self.git_repo.all_revision_ids())

    def test_get_ancestry_null(self):
        self.assertEquals([None], self.git_repo.get_ancestry(revision.NULL_REVISION))

    def assertIsNullInventory(self, inv):
        self.assertEqual(inv.root, None)
        self.assertEqual(inv.revision_id, revision.NULL_REVISION)
        self.assertEqual(list(inv.iter_entries()), [])

    def test_get_inventory_none(self):
        # GitRepository.get_inventory(None) returns the null inventory.
        repo = self.git_repo
        inv = repo.get_inventory(revision.NULL_REVISION)
        self.assertIsNullInventory(inv)

    def test_revision_tree_none(self):
        # GitRepository.revision_tree(None) returns the null tree.
        repo = self.git_repo
        tree = repo.revision_tree(revision.NULL_REVISION)
        self.assertEqual(tree.get_revision_id(), revision.NULL_REVISION)
        self.assertIsNullInventory(tree.inventory)

    def test_get_parent_map_null(self):
        self.assertEquals({revision.NULL_REVISION: ()}, 
                           self.git_repo.get_parent_map([revision.NULL_REVISION]))


class GitRepositoryFormat(tests.TestCase):

    def setUp(self):
        super(GitRepositoryFormat, self).setUp()
        self.format = repository.GitFormat()

    def test_get_format_description(self):
        self.assertEquals("Git Repository", self.format.get_format_description())
