# Copyright (C) 2026 Breezy Developers
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

"""Tests for the Git InterRepository implementations."""

import os

from dulwich.objects import Blob, Commit, Tag, Tree
from dulwich.repo import Repo as GitRepo

from ...controldir import ControlDir
from ...repository import InterRepository
from ...tests import TestCaseWithTransport


class ShallowDeepenTests(TestCaseWithTransport):
    """Deepening a shallow Git repository.

    The shallow boundary is a Git concept with no Breezy equivalent, so these
    assertions cannot live in the parameterised inter test suites.
    """

    def build_commit(self, repo, message, parents):
        blob = Blob.from_string(message)
        tree = Tree()
        tree.add(b"f", 0o100644, blob.id)
        commit = Commit()
        commit.tree = tree.id
        commit.parents = list(parents)
        commit.author = commit.committer = b"Somebody <somebody@someorg.org>"
        commit.commit_time = commit.author_time = 1000000000
        commit.commit_timezone = commit.author_timezone = 0
        commit.encoding = b"UTF-8"
        commit.message = message
        for obj in (blob, tree, commit):
            repo.object_store.add_object(obj)
        return commit.id

    def build_commits(self, repo, name, count):
        """Add a line of `count` commits and return their ids, oldest first."""
        ids = []
        parents = []
        for i in range(count):
            parents = [self.build_commit(repo, b"%s %d" % (name, i), parents)]
            ids.append(parents[0])
        return ids

    def build_branch(self, repo, name, count):
        """Add a branch of `count` commits and return their ids, oldest first."""
        ids = self.build_commits(repo, name, count)
        repo.refs[b"refs/heads/" + name] = ids[-1]
        return ids

    def build_tag(self, repo, name, commit_id):
        """Add an annotated tag on `commit_id` and return the tag object id."""
        tag = Tag()
        tag.name = name
        tag.object = (Commit, commit_id)
        tag.tagger = b"Somebody <somebody@someorg.org>"
        tag.tag_time = 1000000000
        tag.tag_timezone = 0
        tag.message = name + b"\n"
        repo.object_store.add_object(tag)
        repo.refs[b"refs/tags/" + name] = tag.id
        return tag.id

    def make_git_repo(self, path):
        os.mkdir(path)
        repo = GitRepo.init(path)
        self.addCleanup(repo.close)
        return repo

    def fetch(self, depth=None):
        inter = InterRepository.get(
            ControlDir.open("source").open_repository(),
            ControlDir.open("target").open_repository(),
        )
        inter.fetch(depth=depth)

    def shallow(self):
        repo = GitRepo("target")
        self.addCleanup(repo.close)
        return repo.get_shallow()

    def ancestry(self, head):
        repo = GitRepo("target")
        self.addCleanup(repo.close)
        return [entry.commit.id for entry in repo.get_walker(include=[head])]

    def commits(self):
        repo = GitRepo("target")
        self.addCleanup(repo.close)
        store = repo.object_store
        return [sha for sha in store if store[sha].type_name == b"commit"]

    def messages(self, head):
        repo = GitRepo("target")
        self.addCleanup(repo.close)
        return [entry.commit.message for entry in repo.get_walker(include=[head])]

    def test_deepening_past_the_root_clears_the_boundary(self):
        source = self.make_git_repo("source")
        revs = self.build_branch(source, b"master", 3)
        self.make_git_repo("target")

        self.fetch(depth=1)
        self.assertEqual({revs[2]}, self.shallow())

        self.fetch(depth=3)
        self.assertEqual({revs[0]}, self.shallow())

        # Nothing is left behind the root of a three commit history.
        self.fetch(depth=4)
        self.assertEqual(set(), self.shallow())

    def test_deepening_follows_a_tag_to_the_boundary(self):
        source = self.make_git_repo("source")
        # Only an annotated tag leads here, so the want is the tag object.
        revs = self.build_commits(source, b"lineage", 2)
        self.build_tag(source, b"v1", revs[1])
        self.make_git_repo("target")

        self.fetch(depth=1)
        self.assertEqual({revs[1]}, self.shallow())

        self.fetch(depth=2)

        self.assertEqual({revs[0]}, self.shallow())
        self.assertEqual([revs[1], revs[0]], self.ancestry(revs[1]))

    def test_deepening_shortens_a_complete_branch(self):
        source = self.make_git_repo("source")
        alpha = self.build_branch(source, b"alpha", 4)
        self.make_git_repo("target")
        self.fetch(depth=2)
        self.assertEqual({alpha[2]}, self.shallow())

        beta = self.build_branch(source, b"beta", 4)
        self.fetch()
        self.assertEqual({alpha[2]}, self.shallow())
        self.assertEqual(list(reversed(beta)), self.ancestry(beta[3]))

        # Like git fetch --depth, this deepens alpha and shortens beta.
        self.fetch(depth=3)

        self.assertEqual({alpha[1], beta[1]}, self.shallow())
        self.assertEqual([beta[3], beta[2], beta[1]], self.ancestry(beta[3]))

    def test_deepening_from_bzr(self):
        tree = self.make_branch_and_tree("source", format="2a")
        for i in range(3):
            tree.commit(f"rev {i}")
        self.make_git_repo("target")
        inter = InterRepository.get(
            tree.branch.repository, ControlDir.open("target").open_repository()
        )

        inter.fetch(revision_id=tree.last_revision(), lossy=True, depth=1)
        [head] = self.commits()
        self.assertEqual({head}, self.shallow())
        self.assertEqual([b"rev 2"], self.messages(head))

        inter.fetch(revision_id=tree.last_revision(), lossy=True, depth=2)
        self.assertEqual([b"rev 2", b"rev 1"], self.messages(head))
        self.assertEqual({self.ancestry(head)[1]}, self.shallow())

        inter.fetch(revision_id=tree.last_revision(), lossy=True, depth=3)
        self.assertEqual([b"rev 2", b"rev 1", b"rev 0"], self.messages(head))
        self.assertEqual(set(), self.shallow())
