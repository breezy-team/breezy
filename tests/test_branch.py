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


"""Tests for interfacing with a Git Branch"""


import dulwich
from dulwich.objects import (
    Commit,
    Tag,
    )
from dulwich.repo import (
    Repo as GitRepo,
    )

import os
import urllib

from bzrlib import (
    errors,
    revision,
    urlutils,
    version_info as bzrlib_version,
    )
from bzrlib.branch import (
    Branch,
    InterBranch,
    )
from bzrlib.bzrdir import (
    BzrDir,
    )
from bzrlib.repository import (
    Repository,
    )
from bzrlib.symbol_versioning import (
    deprecated_in,
    )
from bzrlib.tests import TestSkipped

from bzrlib.plugins.git import (
    branch,
    tests,
    )
from bzrlib.plugins.git.dir import (
    LocalGitControlDirFormat,
    )
from bzrlib.plugins.git.mapping import (
    default_mapping,
    )


class TestGitBranch(tests.TestCaseInTempDir):

    def test_open_by_ref(self):
        GitRepo.init('.')
        url = "%s,ref=%s" % (
            urlutils.local_path_to_url(self.test_dir),
            urllib.quote("refs/remotes/origin/unstable", safe='')
            )
        if bzrlib_version < (2, 5, 0):
            self.assertRaises(errors.NotBranchError, BzrDir.open, url)
            raise TestSkipped("opening by ref not supported with bzr < 2.5")
        d = BzrDir.open(url)
        b = d.create_branch()
        self.assertEquals(b.ref, "refs/remotes/origin/unstable")

    def test_open_existing(self):
        GitRepo.init('.')
        d = BzrDir.open('.')
        thebranch = d.create_branch()
        self.assertIsInstance(thebranch, branch.GitBranch)

    def test_repr(self):
        GitRepo.init('.')
        d = BzrDir.open('.')
        thebranch = d.create_branch()
        self.assertEquals(
            "<LocalGitBranch('%s/', u'master')>" % (
                urlutils.local_path_to_url(self.test_dir),),
            repr(thebranch))

    def test_last_revision_is_null(self):
        GitRepo.init('.')
        thedir = BzrDir.open('.')
        thebranch = thedir.create_branch()
        self.assertEqual(revision.NULL_REVISION, thebranch.last_revision())
        self.assertEqual((0, revision.NULL_REVISION),
                         thebranch.last_revision_info())

    def simple_commit_a(self):
        r = GitRepo.init('.')
        self.build_tree(['a'])
        r.stage(["a"])
        return r.do_commit("a", committer="Somebody <foo@example.com>")

    def test_last_revision_is_valid(self):
        head = self.simple_commit_a()
        thebranch = Branch.open('.')
        self.assertEqual(default_mapping.revision_id_foreign_to_bzr(head),
                         thebranch.last_revision())

    def test_revision_history(self):
        reva = self.simple_commit_a()
        self.build_tree(['b'])
        r = GitRepo(".")
        r.stage("b")
        revb = r.do_commit("b", committer="Somebody <foo@example.com>")

        thebranch = Branch.open('.')
        (warnings, history) = self.callCatchWarnings(thebranch.revision_history)
        self.assertTrue(
            warnings == [] or 
            (len(warnings) == 1 and isinstance(warnings[0], DeprecationWarning)),
            warnings)
        self.assertEqual([default_mapping.revision_id_foreign_to_bzr(r) for r in (reva, revb)],
                         history)

    def test_tag_annotated(self):
        reva = self.simple_commit_a()
        o = Tag()
        o.name = "foo"
        o.tagger = "Jelmer <foo@example.com>"
        o.message = "add tag"
        o.object = (Commit, reva)
        o.tag_timezone = 0
        o.tag_time = 42
        r = GitRepo(".")
        r.object_store.add_object(o)
        r['refs/tags/foo'] = o.id
        thebranch = Branch.open('.')
        self.assertEquals({"foo": default_mapping.revision_id_foreign_to_bzr(reva)},
                          thebranch.tags.get_tag_dict())

    def test_tag(self):
        reva = self.simple_commit_a()
        r = GitRepo(".")
        r.refs["refs/tags/foo"] = reva
        thebranch = Branch.open('.')
        self.assertEquals({"foo": default_mapping.revision_id_foreign_to_bzr(reva)},
                          thebranch.tags.get_tag_dict())



class TestWithGitBranch(tests.TestCaseWithTransport):

    def setUp(self):
        tests.TestCaseWithTransport.setUp(self)
        dulwich.repo.Repo.create(self.test_dir)
        d = BzrDir.open(self.test_dir)
        self.git_branch = d.create_branch()

    def test_get_parent(self):
        self.assertIs(None, self.git_branch.get_parent())

    def test_get_stacked_on_url(self):
        self.assertRaises(errors.UnstackableBranchFormat,
            self.git_branch.get_stacked_on_url)

    def test_get_physical_lock_status(self):
        self.assertFalse(self.git_branch.get_physical_lock_status())


class TestGitBranchFormat(tests.TestCase):

    def setUp(self):
        super(TestGitBranchFormat, self).setUp()
        self.format = branch.GitBranchFormat()

    def test_get_format_description(self):
        self.assertEquals("Git Branch", self.format.get_format_description())

    def test_get_network_name(self):
        self.assertEquals("git", self.format.network_name())

    def test_supports_tags(self):
        self.assertTrue(self.format.supports_tags())


class BranchTests(tests.TestCaseInTempDir):

    def make_onerev_branch(self):
        os.mkdir("d")
        os.chdir("d")
        GitRepo.init('.')
        bb = tests.GitBranchBuilder()
        bb.set_file("foobar", "foo\nbar\n", False)
        mark = bb.commit("Somebody <somebody@someorg.org>", "mymsg")
        gitsha = bb.finish()[mark]
        os.chdir("..")
        return os.path.abspath("d"), gitsha

    def make_tworev_branch(self):
        os.mkdir("d")
        os.chdir("d")
        GitRepo.init('.')
        bb = tests.GitBranchBuilder()
        bb.set_file("foobar", "foo\nbar\n", False)
        mark1 = bb.commit("Somebody <somebody@someorg.org>", "mymsg")
        mark2 = bb.commit("Somebody <somebody@someorg.org>", "mymsg")
        marks = bb.finish()
        os.chdir("..")
        return "d", (marks[mark1], marks[mark2])

    def clone_git_branch(self, from_url, to_url):
        from_dir = BzrDir.open(from_url)
        to_dir = from_dir.sprout(to_url)
        return to_dir.open_branch()

    def test_single_rev(self):
        path, gitsha = self.make_onerev_branch()
        oldrepo = Repository.open(path)
        revid = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha)
        self.assertEquals(gitsha, oldrepo._git.get_refs()["refs/heads/master"])
        newbranch = self.clone_git_branch(path, "f")
        self.assertEquals([revid], newbranch.repository.all_revision_ids())

    def test_sprouted_tags(self):
        path, gitsha = self.make_onerev_branch()
        r = GitRepo(path)
        r.refs["refs/tags/lala"] = r.head()
        oldrepo = Repository.open(path)
        revid = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha)
        newbranch = self.clone_git_branch(path, "f")
        self.assertEquals({"lala": revid}, newbranch.tags.get_tag_dict())
        self.assertEquals([revid], newbranch.repository.all_revision_ids())

    def test_interbranch_pull(self):
        path, (gitsha1, gitsha2) = self.make_tworev_branch()
        oldrepo = Repository.open(path)
        revid2 = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha2)
        newbranch = self.make_branch('g')
        inter_branch = InterBranch.get(Branch.open(path), newbranch)
        inter_branch.pull()
        self.assertEquals(revid2, newbranch.last_revision())

    def test_interbranch_pull_noop(self):
        path, (gitsha1, gitsha2) = self.make_tworev_branch()
        oldrepo = Repository.open(path)
        revid2 = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha2)
        newbranch = self.make_branch('g')
        inter_branch = InterBranch.get(Branch.open(path), newbranch)
        inter_branch.pull()
        # This is basically "assertNotRaises"
        inter_branch.pull()
        self.assertEquals(revid2, newbranch.last_revision())

    def test_interbranch_pull_stop_revision(self):
        path, (gitsha1, gitsha2) = self.make_tworev_branch()
        oldrepo = Repository.open(path)
        revid1 = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha1)
        newbranch = self.make_branch('g')
        inter_branch = InterBranch.get(Branch.open(path), newbranch)
        inter_branch.pull(stop_revision=revid1)
        self.assertEquals(revid1, newbranch.last_revision())

    def test_interbranch_pull_with_tags(self):
        path, (gitsha1, gitsha2) = self.make_tworev_branch()
        gitrepo = GitRepo(path)
        gitrepo.refs["refs/tags/sometag"] = gitsha2
        oldrepo = Repository.open(path)
        revid1 = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha1)
        revid2 = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha2)
        newbranch = self.make_branch('g')
        source_branch = Branch.open(path)
        source_branch.get_config().set_user_option("branch.fetch_tags", True)
        inter_branch = InterBranch.get(source_branch, newbranch)
        inter_branch.pull(stop_revision=revid1)
        self.assertEquals(revid1, newbranch.last_revision())
        self.assertTrue(newbranch.repository.has_revision(revid2))


class ForeignTestsBranchFactory(object):

    def make_empty_branch(self, transport):
        d = LocalGitControlDirFormat().initialize_on_transport(transport)
        return d.create_branch()

    make_branch = make_empty_branch