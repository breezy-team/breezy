# Copyright (C) 2007 Canonical Ltd
# Copyright (C) 2007-2018 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Tests for interfacing with a Git Repository."""

import os

import dulwich
from dulwich.repo import Repo as GitRepo

from ... import config, errors, revision
from ...repository import InterRepository, Repository
from .. import dir, repository, tests
from ..mapping import default_mapping
from ..object_store import BazaarObjectStore
from ..push import MissingObjectsIterator


class TestGitRepositoryFeatures(tests.TestCaseInTempDir):
    """Feature tests for GitRepository."""

    def _do_commit(self):
        builder = tests.GitBranchBuilder()
        builder.set_file(b"a", b"text for a\n", False)
        commit_handle = builder.commit(b"Joe Foo <joe@foo.com>", b"message")
        mapping = builder.finish()
        return mapping[commit_handle]

    def test_open_existing(self):
        GitRepo.init(self.test_dir)

        repo = Repository.open(".")
        self.assertIsInstance(repo, repository.GitRepository)

    def test_has_git_repo(self):
        GitRepo.init(self.test_dir)

        repo = Repository.open(".")
        self.assertIsInstance(repo._git, dulwich.repo.BaseRepo)

    def test_has_revision(self):
        GitRepo.init(self.test_dir)
        commit_id = self._do_commit()
        repo = Repository.open(".")
        self.assertFalse(repo.has_revision(b"foobar"))
        revid = default_mapping.revision_id_foreign_to_bzr(commit_id)
        self.assertTrue(repo.has_revision(revid))

    def test_has_revisions(self):
        GitRepo.init(self.test_dir)
        commit_id = self._do_commit()
        repo = Repository.open(".")
        self.assertEqual(set(), repo.has_revisions([b"foobar"]))
        revid = default_mapping.revision_id_foreign_to_bzr(commit_id)
        self.assertEqual({revid}, repo.has_revisions([b"foobar", revid]))

    def test_get_revision(self):
        # GitRepository.get_revision gives a Revision object.

        # Create a git repository with a revision.
        GitRepo.init(self.test_dir)
        commit_id = self._do_commit()

        # Get the corresponding Revision object.
        revid = default_mapping.revision_id_foreign_to_bzr(commit_id)
        repo = Repository.open(".")
        rev = repo.get_revision(revid)
        self.assertIsInstance(rev, revision.Revision)

    def test_get_revision_unknown(self):
        GitRepo.init(self.test_dir)

        repo = Repository.open(".")
        self.assertRaises(errors.NoSuchRevision, repo.get_revision, b"bla")

    def simple_commit(self):
        # Create a git repository with some interesting files in a revision.
        GitRepo.init(self.test_dir)
        builder = tests.GitBranchBuilder()
        builder.set_file(b"data", b"text\n", False)
        builder.set_file(b"executable", b"content", True)
        builder.set_symlink(b"link", b"broken")
        builder.set_file(b"subdir/subfile", b"subdir text\n", False)
        commit_handle = builder.commit(
            b"Joe Foo <joe@foo.com>", b"message", timestamp=1205433193
        )
        mapping = builder.finish()
        return mapping[commit_handle]

    def test_pack(self):
        self.simple_commit()
        repo = Repository.open(".")
        repo.pack()

    def test_unlock_closes(self):
        self.simple_commit()
        repo = Repository.open(".")
        repo.pack()
        with repo.lock_read():
            repo.all_revision_ids()
            self.assertGreater(len(repo._git.object_store._pack_cache), 0)
        self.assertEqual(len(repo._git.object_store._pack_cache), 0)

    def test_revision_tree(self):
        commit_id = self.simple_commit()
        revid = default_mapping.revision_id_foreign_to_bzr(commit_id)
        repo = Repository.open(".")
        tree = repo.revision_tree(revid)
        self.assertEqual(tree.get_revision_id(), revid)
        self.assertEqual(b"text\n", tree.get_file_text("data"))


class TestGitRepository(tests.TestCaseWithTransport):
    def _do_commit(self):
        builder = tests.GitBranchBuilder()
        builder.set_file(b"a", b"text for a\n", False)
        commit_handle = builder.commit(b"Joe Foo <joe@foo.com>", b"message")
        mapping = builder.finish()
        return mapping[commit_handle]

    def setUp(self):
        tests.TestCaseWithTransport.setUp(self)
        dulwich.repo.Repo.create(self.test_dir)
        self.git_repo = Repository.open(self.test_dir)

    def test_supports_rich_root(self):
        repo = self.git_repo
        self.assertEqual(repo.supports_rich_root(), True)

    def test_get_signature_text(self):
        self.assertRaises(
            errors.NoSuchRevision,
            self.git_repo.get_signature_text,
            revision.NULL_REVISION,
        )

    def test_has_signature_for_revision_id(self):
        self.assertEqual(
            False, self.git_repo.has_signature_for_revision_id(revision.NULL_REVISION)
        )

    def test_all_revision_ids_none(self):
        self.assertEqual([], self.git_repo.all_revision_ids())

    def test_get_known_graph_ancestry(self):
        cid = self._do_commit()
        revid = default_mapping.revision_id_foreign_to_bzr(cid)
        g = self.git_repo.get_known_graph_ancestry([revid])
        self.assertEqual(frozenset([revid]), g.heads([revid]))
        self.assertEqual(
            [(revid, 0, (1,), True)],
            [
                (n.key, n.merge_depth, n.revno, n.end_of_merge)
                for n in g.merge_sort(revid)
            ],
        )

    def test_all_revision_ids(self):
        commit_id = self._do_commit()
        self.assertEqual(
            [default_mapping.revision_id_foreign_to_bzr(commit_id)],
            self.git_repo.all_revision_ids(),
        )

    def assertIsNullInventory(self, inv):
        self.assertEqual(inv.root, None)
        self.assertEqual(inv.revision_id, revision.NULL_REVISION)
        self.assertEqual(list(inv.iter_entries()), [])

    def test_revision_tree_none(self):
        # GitRepository.revision_tree('null':') returns the null tree.
        repo = self.git_repo
        tree = repo.revision_tree(revision.NULL_REVISION)
        self.assertEqual(tree.get_revision_id(), revision.NULL_REVISION)

    def test_get_parent_map_null(self):
        self.assertEqual(
            {revision.NULL_REVISION: ()},
            self.git_repo.get_parent_map([revision.NULL_REVISION]),
        )


class SigningGitRepository(tests.TestCaseWithTransport):
    def test_signed_commit(self):
        import breezy.gpg

        oldstrategy = breezy.gpg.GPGStrategy
        wt = self.make_branch_and_tree(".", format="git")
        branch = wt.branch
        revid = wt.commit("base", allow_pointless=True)
        self.assertFalse(branch.repository.has_signature_for_revision_id(revid))
        try:
            breezy.gpg.GPGStrategy = breezy.gpg.LoopbackGPGStrategy
            conf = config.MemoryStack(
                b"""
create_signatures=always
"""
            )
            revid2 = wt.commit(config=conf, message="base", allow_pointless=True)

            def sign(text):
                return breezy.gpg.LoopbackGPGStrategy(None).sign(text)

            self.assertIsInstance(branch.repository.get_signature_text(revid2), bytes)
        finally:
            breezy.gpg.GPGStrategy = oldstrategy


class RevpropsRepository(tests.TestCaseWithTransport):
    def test_author(self):
        wt = self.make_branch_and_tree(".", format="git")
        revid = wt.commit(
            "base",
            allow_pointless=True,
            revprops={"author": "Joe Example <joe@example.com>"},
        )
        wt.branch.repository.get_revision(revid)
        r = dulwich.repo.Repo(".")
        self.assertEqual(b"Joe Example <joe@example.com>", r[r.head()].author)

    def test_authors_single_author(self):
        wt = self.make_branch_and_tree(".", format="git")
        revid = wt.commit(
            "base",
            allow_pointless=True,
            revprops={"authors": "Joe Example <joe@example.com>"},
        )
        wt.branch.repository.get_revision(revid)
        r = dulwich.repo.Repo(".")
        self.assertEqual(b"Joe Example <joe@example.com>", r[r.head()].author)

    def test_multiple_authors(self):
        wt = self.make_branch_and_tree(".", format="git")
        self.assertRaises(
            Exception,
            wt.commit,
            "base",
            allow_pointless=True,
            revprops={
                "authors": "Joe Example <joe@example.com>\n"
                "Jane Doe <jane@example.com\n>"
            },
        )

    def test_bugs(self):
        wt = self.make_branch_and_tree(".", format="git")
        revid = wt.commit(
            "base",
            allow_pointless=True,
            revprops={"bugs": "https://github.com/jelmer/dulwich/issues/123 fixed\n"},
        )
        wt.branch.repository.get_revision(revid)
        r = dulwich.repo.Repo(".")
        self.assertEqual(
            b"base\n\nFixes: https://github.com/jelmer/dulwich/issues/123\n",
            r[r.head()].message,
        )

    def test_authors(self):
        wt = self.make_branch_and_tree(".", format="git")
        revid = wt.commit(
            "base",
            allow_pointless=True,
            revprops={
                "authors": (
                    "Jelmer Vernooij <jelmer@example.com>\n"
                    "Martin Packman <bz2@example.com>\n"
                ),
            },
        )
        wt.branch.repository.get_revision(revid)
        r = dulwich.repo.Repo(".")
        self.assertEqual(r[r.head()].author, b"Jelmer Vernooij <jelmer@example.com>")
        self.assertEqual(
            b"base\n\nCo-authored-by: Martin Packman <bz2@example.com>\n",
            r[r.head()].message,
        )


class GitRepositoryFormat(tests.TestCase):
    def setUp(self):
        super().setUp()
        self.format = repository.GitRepositoryFormat()

    def test_get_format_description(self):
        self.assertEqual("Git Repository", self.format.get_format_description())


class RevisionGistImportTests(tests.TestCaseWithTransport):
    def setUp(self):
        tests.TestCaseWithTransport.setUp(self)
        self.git_path = os.path.join(self.test_dir, "git")
        os.mkdir(self.git_path)
        dulwich.repo.Repo.create(self.git_path)
        self.git_repo = Repository.open(self.git_path)
        self.bzr_tree = self.make_branch_and_tree("bzr")

    def get_inter(self):
        return InterRepository.get(self.bzr_tree.branch.repository, self.git_repo)

    def object_iter(self):
        store = BazaarObjectStore(self.bzr_tree.branch.repository, default_mapping)
        store_iterator = MissingObjectsIterator(store, self.bzr_tree.branch.repository)
        return store, store_iterator

    def import_rev(self, revid, parent_lookup=None):
        store, store_iter = self.object_iter()
        store._cache.idmap.start_write_group()
        try:
            return store_iter.import_revision(revid, lossy=True)
        except:
            store._cache.idmap.abort_write_group()
            raise
        else:
            store._cache.idmap.commit_write_group()

    def test_pointless(self):
        revid = self.bzr_tree.commit(
            "pointless",
            timestamp=1205433193,
            timezone=0,
            committer="Jelmer Vernooij <jelmer@samba.org>",
        )
        self.assertEqual(
            b"2caa8094a5b794961cd9bf582e3e2bb090db0b14", self.import_rev(revid)
        )
        self.assertEqual(
            b"2caa8094a5b794961cd9bf582e3e2bb090db0b14", self.import_rev(revid)
        )


class ForeignTestsRepositoryFactory:
    def make_repository(self, transport):
        return (
            dir.LocalGitControlDirFormat()
            .initialize_on_transport(transport)
            .open_repository()
        )
