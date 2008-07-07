# -*- coding: utf-8 -*-

# Copyright (C) 2006-2007 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from bzrlib.branch import Branch, BranchReferenceFormat
from bzrlib.bzrdir import BzrDir, BzrDirFormat
from bzrlib.errors import AlreadyBranchError, BzrError, DivergedBranches
from bzrlib.inventory import Inventory
from bzrlib.merge import Merger, Merge3Merger
from bzrlib.osutils import has_symlinks
from bzrlib.progress import DummyProgress
from bzrlib.repository import Repository
from bzrlib.tests import KnownFailure, TestCaseWithTransport
from bzrlib.trace import mutter
from bzrlib.workingtree import WorkingTree

import os
from time import sleep

from bzrlib.plugins.svn import core, format, ra
from bzrlib.plugins.svn.errors import ChangesRootLHSHistory, MissingPrefix
from bzrlib.plugins.svn.commit import push, dpush
from bzrlib.plugins.svn.mapping import SVN_PROP_BZR_REVISION_ID
from bzrlib.plugins.svn.tests import TestCaseWithSubversionRepository

class TestDPush(TestCaseWithSubversionRepository):
    def setUp(self):
        super(TestDPush, self).setUp()
        self.repos_url = self.make_repository('d')

        dc = self.commit_editor()
        foo = dc.add_dir("foo")
        foo.add_file("foo/bla").modify("data")
        dc.close()

        self.svndir = BzrDir.open(self.repos_url)
        os.mkdir("dc")
        self.bzrdir = self.svndir.sprout("dc")

    def commit_editor(self):
        return self.get_commit_editor(self.repos_url)

    def test_change_single(self):
        self.build_tree({'dc/foo/bla': 'other data'})
        wt = self.bzrdir.open_workingtree()
        newid = wt.commit(message="Commit from Bzr")

        revid_map = dpush(self.svndir.open_branch(), self.bzrdir.open_branch())

        self.assertEquals([newid], revid_map.keys())

        c = ra.RemoteAccess(self.repos_url)
        (entries, fetch_rev, props) = c.get_dir("", c.get_latest_revnum())
        self.assertEquals(set(['svn:entry:committed-rev', 
            'svn:entry:last-author', 'svn:entry:uuid', 
            'svn:entry:committed-date']), set(props.keys()))

        r = self.svndir.find_repository()
        self.assertEquals([r.generate_revision_id(
                c.get_latest_revnum(),
                "", 
                r.get_mapping())], revid_map.values())

    def test_change_multiple(self):
        self.build_tree({'dc/foo/bla': 'other data'})
        wt = self.bzrdir.open_workingtree()
        self.build_tree({'dc/foo/bla': 'other data'})
        newid1 = wt.commit(message="Commit from Bzr")
        self.build_tree({'dc/foo/bla': 'yet other data'})
        newid2 = wt.commit(message="Commit from Bzr")

        revid_map = dpush(self.svndir.open_branch(), self.bzrdir.open_branch())

        self.assertEquals(set([newid1, newid2]), set(revid_map.keys()))

        c = ra.RemoteAccess(self.repos_url)
        (entries, fetch_rev, props) = c.get_dir("", c.get_latest_revnum())
        self.assertEquals(set(['svn:entry:committed-rev', 
            'svn:entry:last-author', 'svn:entry:uuid', 
            'svn:entry:committed-date']), set(props.keys()))

        r = self.svndir.find_repository()
        self.assertEquals(set([r.generate_revision_id(
                rev,
                "", 
                r.get_mapping()) for rev in (c.get_latest_revnum()-1, c.get_latest_revnum())]), 
                set(revid_map.values()))
 
    def test_diverged(self):
        dc = self.commit_editor()
        foo = dc.open_dir("foo")
        foo.add_file("foo/bar").modify("data")
        dc.close()

        svndir = BzrDir.open(self.repos_url)

        self.build_tree({'dc/file': 'data'})
        wt = self.bzrdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.assertRaises(DivergedBranches, 
                          dpush, svndir.open_branch(),
                          self.bzrdir.open_branch())


class TestPush(TestCaseWithSubversionRepository):
    def setUp(self):
        super(TestPush, self).setUp()
        self.repos_url = self.make_repository('d')

        dc = self.commit_editor()
        foo = dc.add_dir("foo")
        foo.add_file("foo/bla").modify("data")
        dc.close()

        self.svndir = BzrDir.open(self.repos_url)
        os.mkdir("dc")
        self.bzrdir = self.svndir.sprout("dc")

    def commit_editor(self):
        return self.get_commit_editor(self.repos_url)

    def test_empty(self):
        svnbranch = self.svndir.open_branch()
        bzrbranch = self.bzrdir.open_branch()
        result = svnbranch.pull(bzrbranch)
        self.assertEqual(0, result.new_revno - result.old_revno)
        self.assertEqual(svnbranch.revision_history(),
                         bzrbranch.revision_history())

    def test_child(self):
        dc = self.commit_editor()
        foo = dc.open_dir("foo")
        foo.add_file("foo/bar").modify("data")
        dc.close()

        svnbranch = self.svndir.open_branch()
        bzrbranch = self.bzrdir.open_branch()
        result = svnbranch.pull(bzrbranch)
        self.assertEqual(0, result.new_revno - result.old_revno)

    def test_diverged(self):
        dc = self.commit_editor()
        foo = dc.open_dir("foo")
        foo.add_file("foo/bar").modify("data")
        dc.close()

        svndir = BzrDir.open(self.repos_url)

        self.build_tree({'dc/file': 'data'})
        wt = self.bzrdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.assertRaises(DivergedBranches, 
                          svndir.open_branch().pull,
                          self.bzrdir.open_branch())

    def test_change(self):
        self.build_tree({'dc/foo/bla': 'other data'})
        wt = self.bzrdir.open_workingtree()
        newid = wt.commit(message="Commit from Bzr")

        svnbranch = self.svndir.open_branch()
        svnbranch.pull(self.bzrdir.open_branch())

        repos = self.svndir.find_repository()
        mapping = repos.get_mapping()
        self.assertEquals(newid, svnbranch.last_revision())
        inv = repos.get_inventory(repos.generate_revision_id(2, "", mapping))
        self.assertEqual(newid, inv[inv.path2id('foo/bla')].revision)
        self.assertEqual(wt.branch.last_revision(),
          repos.generate_revision_id(2, "", mapping))
        self.assertEqual(repos.generate_revision_id(2, "", mapping),
                        self.svndir.open_branch().last_revision())
        self.assertEqual("other data", 
            repos.revision_tree(repos.generate_revision_id(2, "", 
                                mapping)).get_file_text(inv.path2id("foo/bla")))

    def test_simple(self):
        self.build_tree({'dc/file': 'data'})
        wt = self.bzrdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.svndir.open_branch().pull(self.bzrdir.open_branch())

        repos = self.svndir.find_repository()
        mapping = repos.get_mapping()
        inv = repos.get_inventory(repos.generate_revision_id(2, "", mapping))
        self.assertTrue(inv.has_filename('file'))
        self.assertEquals(wt.branch.last_revision(),
                repos.generate_revision_id(2, "", mapping))
        self.assertEqual(repos.generate_revision_id(2, "", mapping),
                        self.svndir.open_branch().last_revision())

    def test_override_revprops(self):
        self.svndir.find_repository().get_config().set_user_option("override-svn-revprops", "True")
        self.build_tree({'dc/file': 'data'})
        wt = self.bzrdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr", committer="Sombody famous", timestamp=1012604400, timezone=0)

        self.svndir.open_branch().pull(self.bzrdir.open_branch())

        self.assertEquals(("Sombody famous", "2002-02-01T23:00:00.000000Z", "Commit from Bzr"), 
            self.client_log(self.repos_url, 0, 2)[2][1:])

    def test_empty_file(self):
        self.build_tree({'dc/file': ''})
        wt = self.bzrdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.svndir.open_branch().pull(self.bzrdir.open_branch())

        repos = self.svndir.find_repository()
        mapping = repos.get_mapping()
        inv = repos.get_inventory(repos.generate_revision_id(2, "", mapping))
        self.assertTrue(inv.has_filename('file'))
        self.assertEquals(wt.branch.last_revision(),
                repos.generate_revision_id(2, "", mapping))
        self.assertEqual(repos.generate_revision_id(2, "", mapping),
                        self.svndir.open_branch().last_revision())

    def test_symlink(self):
        if not has_symlinks():
            return
        os.symlink("bla", "dc/south")
        assert os.path.islink("dc/south")
        wt = self.bzrdir.open_workingtree()
        wt.add('south')
        wt.commit(message="Commit from Bzr")

        self.svndir.open_branch().pull(self.bzrdir.open_branch())

        repos = self.svndir.find_repository()
        mapping = repos.get_mapping() 
        inv = repos.get_inventory(repos.generate_revision_id(2, "", mapping))
        self.assertTrue(inv.has_filename('south'))
        self.assertEquals('symlink', inv[inv.path2id('south')].kind)
        self.assertEquals('bla', inv[inv.path2id('south')].symlink_target)

    def test_pull_after_push(self):
        self.build_tree({'dc/file': 'data'})
        wt = self.bzrdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.svndir.open_branch().pull(self.bzrdir.open_branch())

        repos = self.svndir.find_repository()
        mapping = repos.get_mapping()
        inv = repos.get_inventory(repos.generate_revision_id(2, "", mapping))
        self.assertTrue(inv.has_filename('file'))
        self.assertEquals(wt.branch.last_revision(),
                         repos.generate_revision_id(2, "", mapping))
        self.assertEqual(repos.generate_revision_id(2, "", mapping),
                        self.svndir.open_branch().last_revision())

        self.bzrdir.open_branch().pull(self.svndir.open_branch())

        self.assertEqual(repos.generate_revision_id(2, "", mapping),
                        self.bzrdir.open_branch().last_revision())

    def test_branch_after_push(self):
        self.build_tree({'dc/file': 'data'})
        wt = self.bzrdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.svndir.open_branch().pull(self.bzrdir.open_branch())

        os.mkdir("b")
        repos = self.svndir.sprout("b")

        self.assertEqual(Branch.open("dc").revision_history(), 
                         Branch.open("b").revision_history())

    def test_message(self):
        self.build_tree({'dc/file': 'data'})
        wt = self.bzrdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.svndir.open_branch().pull(self.bzrdir.open_branch())

        repos = self.svndir.find_repository()
        mapping = repos.get_mapping()
        self.assertEqual("Commit from Bzr",
          repos.get_revision(repos.generate_revision_id(2, "", mapping)).message)

    def test_commit_set_revid(self):
        self.build_tree({'dc/file': 'data'})
        wt = self.bzrdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr", rev_id="some-rid")

        self.svndir.open_branch().pull(self.bzrdir.open_branch())

        c = ra.RemoteAccess(self.repos_url)
        self.assertEqual("3 some-rid\n", 
                c.get_dir("", c.get_latest_revnum())[2][SVN_PROP_BZR_REVISION_ID+"none"])

    def test_commit_check_rev_equal(self):
        self.build_tree({'dc/file': 'data'})
        wt = self.bzrdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.svndir.open_branch().pull(self.bzrdir.open_branch())

        rev1 = self.svndir.find_repository().get_revision(wt.branch.last_revision())
        rev2 = self.bzrdir.find_repository().get_revision(wt.branch.last_revision())

        self.assertEqual(rev1.committer, rev2.committer)
        self.assertEqual(rev1.timestamp, rev2.timestamp)
        self.assertEqual(rev1.timezone, rev2.timezone)
        self.assertEqual(rev1.properties, rev2.properties)
        self.assertEqual(rev1.message, rev2.message)
        self.assertEqual(rev1.revision_id, rev2.revision_id)

    def test_multiple(self):
        self.build_tree({'dc/file': 'data'})
        wt = self.bzrdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.build_tree({'dc/file': 'data2', 'dc/adir': None})
        wt.add('adir')
        wt.commit(message="Another commit from Bzr")

        self.svndir.open_branch().pull(self.bzrdir.open_branch())

        repos = self.svndir.find_repository()

        mapping = repos.get_mapping()

        self.assertEqual(repos.generate_revision_id(3, "", mapping), 
                        self.svndir.open_branch().last_revision())

        inv = repos.get_inventory(repos.generate_revision_id(2, "", mapping))
        self.assertTrue(inv.has_filename('file'))
        self.assertFalse(inv.has_filename('adir'))

        inv = repos.get_inventory(repos.generate_revision_id(3, "", mapping))
        self.assertTrue(inv.has_filename('file'))
        self.assertTrue(inv.has_filename('adir'))

        self.assertEqual(self.svndir.open_branch().revision_history(),
                         self.bzrdir.open_branch().revision_history())

        self.assertEqual(wt.branch.last_revision(), 
                repos.generate_revision_id(3, "", mapping))
        self.assertEqual(
                wt.branch.repository.get_ancestry(wt.branch.last_revision()), 
                repos.get_ancestry(wt.branch.last_revision()))

    def test_multiple_diverged(self):
        oc_url = self.make_repository("o")

        self.build_tree({'dc/file': 'data'})
        wt = self.bzrdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        oc = self.get_commit_editor(oc_url)
        oc.add_file("file").modify("data2")
        oc.add_dir("adir")
        oc.close()

        self.assertRaises(DivergedBranches, 
                lambda: Branch.open(oc_url).pull(self.bzrdir.open_branch()))

    def test_different_branch_path(self):
        # A       ,> C
        # \ -> B /
        dc = self.commit_editor()
        trunk = dc.add_dir("trunk")
        trunk.add_file('trunk/foo').modify("data")
        dc.add_dir("branches")
        dc.close()

        dc = self.commit_editor()
        branches = dc.open_dir('branches')
        mybranch = branches.add_dir('branches/mybranch', 'trunk')
        mybranch.open_file("branches/mybranch/foo").modify('data2')
        dc.close()

        self.svndir = BzrDir.open("%s/branches/mybranch" % self.repos_url)
        os.mkdir("mybranch")
        self.bzrdir = self.svndir.sprout("mybranch")

        self.build_tree({'mybranch/foo': 'bladata'})
        wt = self.bzrdir.open_workingtree()
        revid = wt.commit(message="Commit from Bzr")
        push(Branch.open("%s/trunk" % self.repos_url), wt.branch, 
             wt.branch.revision_history()[-2])
        mutter('log %r' % self.client_log("%s/trunk" % self.repos_url, 0, 4)[4][0])
        self.assertEquals('M',
            self.client_log("%s/trunk" % self.repos_url, 0, 4)[4][0]['/trunk'][0])
        push(Branch.open("%s/trunk" % self.repos_url), wt.branch, wt.branch.last_revision())
        mutter('log %r' % self.client_log("%s/trunk" % self.repos_url, 0, 5)[5][0])
        self.assertEquals("/branches/mybranch", 
            self.client_log("%s/trunk" % self.repos_url, 0, 5)[5][0]['/trunk'][1])

class PushNewBranchTests(TestCaseWithSubversionRepository):
    def test_single_revision(self):
        repos_url = self.make_repository("a")
        bzrwt = BzrDir.create_standalone_workingtree("c", 
            format=format.get_rich_root_format())
        self.build_tree({'c/test': "Tour"})
        bzrwt.add("test")
        revid = bzrwt.commit("Do a commit")
        newdir = BzrDir.open("%s/trunk" % repos_url)
        newbranch = newdir.import_branch(bzrwt.branch)
        newtree = newbranch.repository.revision_tree(revid)
        bzrwt.lock_read()
        self.assertEquals(bzrwt.inventory.root.file_id,
                          newtree.inventory.root.file_id)
        bzrwt.unlock()
        self.assertEquals(revid, newbranch.last_revision())
        self.assertEquals([revid], newbranch.revision_history())

    def test_single_revision_single_branching_scheme(self):
        repos_url = self.make_repository("a")
        bzrwt = BzrDir.create_standalone_workingtree("c", 
            format=format.get_rich_root_format())
        self.build_tree({'c/test': "Tour"})
        bzrwt.add("test")
        revid = bzrwt.commit("Do a commit")

        dc = self.get_commit_editor(repos_url)
        some = dc.add_dir("some")
        funny = some.add_dir("some/funny")
        funny.add_dir("some/funny/branch")
        dc.close()
        newdir = BzrDir.open("%s/some/funny/branch/name" % repos_url)
        newbranch = newdir.import_branch(bzrwt.branch)
        self.assertEquals(revid, newbranch.last_revision())

    # revision graph for the two tests below:
    # svn-1
    # |
    # base
    # |    \
    # diver svn2
    # |    /
    # merge

    def test_push_replace_existing_root(self):
        repos_url = self.make_client("test", "svnco")
        self.build_tree({'svnco/foo.txt': 'foo'})
        self.client_add("svnco/foo.txt")
        self.client_commit("svnco", "add file") #1
        self.client_update("svnco")

        os.mkdir('bzrco')
        dir = BzrDir.open(repos_url).sprout("bzrco")
        wt = dir.open_workingtree()
        self.build_tree({'bzrco/bar.txt': 'bar'})
        wt.add("bar.txt")
        base_revid = wt.commit("add another file", rev_id="mybase")
        wt.branch.push(Branch.open(repos_url))

        self.build_tree({"svnco/baz.txt": "baz"})
        self.client_add("svnco/baz.txt")
        self.assertEquals(3, 
                self.client_commit("svnco", "add yet another file")[0])
        self.client_update("svnco")

        self.build_tree({"bzrco/qux.txt": "qux"})
        wt.add("qux.txt")
        wt.commit("add still more files", rev_id="mydiver")

        repos = Repository.open(repos_url)
        wt.branch.repository.fetch(repos)
        mapping = repos.get_mapping()
        other_rev = repos.generate_revision_id(3, "", mapping)
        wt.lock_write()
        try:
            merge = Merger.from_revision_ids(DummyProgress(), wt, other=other_rev)
            merge.merge_type = Merge3Merger
            merge.do_merge()
            self.assertEquals(base_revid, merge.base_rev_id)
            merge.set_pending()
            self.assertEquals([wt.last_revision(), other_rev], wt.get_parent_ids())
            wt.commit("merge", rev_id="mymerge")
        finally:
            wt.unlock()
        self.assertTrue(os.path.exists("bzrco/baz.txt"))
        self.assertRaises(BzrError, 
                lambda: wt.branch.push(Branch.open(repos_url)))

    def test_push_replace_existing_branch(self):
        repos_url = self.make_client("test", "svnco")
        self.build_tree({'svnco/trunk/foo.txt': 'foo'})
        self.client_add("svnco/trunk")
        self.client_commit("svnco", "add file") #1
        self.client_update("svnco")

        os.mkdir('bzrco')
        dir = BzrDir.open(repos_url+"/trunk").sprout("bzrco")
        wt = dir.open_workingtree()
        self.build_tree({'bzrco/bar.txt': 'bar'})
        wt.add("bar.txt")
        base_revid = wt.commit("add another file", rev_id="mybase")
        wt.branch.push(Branch.open(repos_url+"/trunk"))

        self.build_tree({"svnco/trunk/baz.txt": "baz"})
        self.client_add("svnco/trunk/baz.txt")
        self.assertEquals(3, 
                self.client_commit("svnco", "add yet another file")[0])
        self.client_update("svnco")

        self.build_tree({"bzrco/qux.txt": "qux"})
        wt.add("qux.txt")
        wt.commit("add still more files", rev_id="mydiver")

        repos = Repository.open(repos_url)
        wt.branch.repository.fetch(repos)
        mapping = repos.get_mapping()
        other_rev = repos.generate_revision_id(3, "trunk", mapping)
        wt.lock_write()
        try:
            merge = Merger.from_revision_ids(DummyProgress(), wt, other=other_rev)
            merge.merge_type = Merge3Merger
            merge.do_merge()
            self.assertEquals(base_revid, merge.base_rev_id)
            merge.set_pending()
            self.assertEquals([wt.last_revision(), other_rev], wt.get_parent_ids())
            wt.commit("merge", rev_id="mymerge")
        finally:
            wt.unlock()
        self.assertTrue(os.path.exists("bzrco/baz.txt"))
        wt.branch.push(Branch.open(repos_url+"/trunk"))

    def test_missing_prefix_error(self):
        repos_url = self.make_repository("a")
        bzrwt = BzrDir.create_standalone_workingtree("c", 
            format=format.get_rich_root_format())
        self.build_tree({'c/test': "Tour"})
        bzrwt.add("test")
        revid = bzrwt.commit("Do a commit")
        newdir = BzrDir.open(repos_url+"/foo/trunk")
        self.assertRaises(MissingPrefix, 
                          lambda: newdir.import_branch(bzrwt.branch))

    def test_repeat(self):
        repos_url = self.make_repository("a")
        bzrwt = BzrDir.create_standalone_workingtree("c", 
            format=format.get_rich_root_format())
        self.build_tree({'c/test': "Tour"})
        bzrwt.add("test")
        revid = bzrwt.commit("Do a commit")
        newdir = BzrDir.open(repos_url+"/trunk")
        newbranch = newdir.import_branch(bzrwt.branch)
        self.assertEquals(revid, newbranch.last_revision())
        self.assertEquals([revid], newbranch.revision_history())
        self.build_tree({'c/test': "Tour de France"})
        bzrwt.commit("Do a commit")
        newdir = BzrDir.open(repos_url+"/trunk")
        self.assertRaises(AlreadyBranchError, newdir.import_branch, 
                          bzrwt.branch)

    def test_multiple(self):
        repos_url = self.make_repository("a")
        bzrwt = BzrDir.create_standalone_workingtree("c", 
            format=format.get_rich_root_format())
        self.build_tree({'c/test': "Tour"})
        bzrwt.add("test")
        revid1 = bzrwt.commit("Do a commit")
        self.build_tree({'c/test': "Tour de France"})
        revid2 = bzrwt.commit("Do a commit")
        newdir = BzrDir.open(repos_url+"/trunk")
        newbranch = newdir.import_branch(bzrwt.branch)
        self.assertEquals(revid2, newbranch.last_revision())
        self.assertEquals([revid1, revid2], newbranch.revision_history())

    def test_dato(self):
        repos_url = self.make_repository("a")
        bzrwt = BzrDir.create_standalone_workingtree("c", 
            format=format.get_rich_root_format())
        self.build_tree({'c/foo.txt': "foo"})
        bzrwt.add("foo.txt")
        revid1 = bzrwt.commit("Do a commit", 
                              committer=u"Adeodato Simó <dato@net.com.org.es>")
        newdir = BzrDir.open(repos_url+"/trunk")
        newdir.import_branch(bzrwt.branch)
        self.assertEquals(u"Adeodato Simó <dato@net.com.org.es>", 
                Repository.open(repos_url).get_revision(revid1).committer)

    def test_utf8_commit_msg(self):
        repos_url = self.make_repository("a")
        bzrwt = BzrDir.create_standalone_workingtree("c", 
            format=format.get_rich_root_format())
        self.build_tree({'c/foo.txt': "foo"})
        bzrwt.add("foo.txt")
        revid1 = bzrwt.commit(u"Do á commït")
        newdir = BzrDir.open(repos_url+"/trunk")
        newdir.import_branch(bzrwt.branch)
        self.assertEquals(u"Do á commït",
                Repository.open(repos_url).get_revision(revid1).message)

    def test_multiple_part_exists(self):
        repos_url = self.make_repository("a")

        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_dir('trunk')
        trunk.add_file("trunk/myfile").modify("data")
        dc.add_dir("branches")
        dc.close()

        svnrepos = Repository.open(repos_url)
        os.mkdir("c")
        bzrdir = BzrDir.open(repos_url+"/trunk").sprout("c")
        bzrwt = bzrdir.open_workingtree()
        self.build_tree({'c/myfile': "Tour"})
        revid1 = bzrwt.commit("Do a commit")
        self.build_tree({'c/myfile': "Tour de France"})
        revid2 = bzrwt.commit("Do a commit")
        newdir = BzrDir.open(repos_url+"/branches/mybranch")
        newbranch = newdir.import_branch(bzrwt.branch)
        self.assertEquals(revid2, newbranch.last_revision())
        mapping = svnrepos.get_mapping()
        self.assertEquals([
            svnrepos.generate_revision_id(1, "trunk", mapping) 
            , revid1, revid2], newbranch.revision_history())

    def test_push_overwrite(self):
        repos_url = self.make_repository("a")

        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_dir("trunk")
        trunk.add_file("trunk/bloe").modify("text")
        dc.close()

        os.mkdir("d1")
        bzrdir = BzrDir.open(repos_url+"/trunk").sprout("d1")
        bzrwt1 = bzrdir.open_workingtree()

        os.mkdir("d2")
        bzrdir = BzrDir.open(repos_url+"/trunk").sprout("d2")
        bzrwt2 = bzrdir.open_workingtree()

        self.build_tree({'d1/myfile': "Tour"})
        bzrwt1.add("myfile")
        revid1 = bzrwt1.commit("Do a commit")

        self.build_tree({'d2/myfile': "France"})
        bzrwt2.add("myfile")
        revid2 = bzrwt1.commit("Do a commit")

        bzrwt1.branch.push(Branch.open(repos_url+"/trunk"))

        raise KnownFailure("push --overwrite not supported yet")

        bzrwt2.branch.push(Branch.open(repos_url+"/trunk"), overwrite=True)

        self.assertEquals([revid2], 
                Branch.open(repos_url+"/trunk").revision_history())

    def test_complex_rename(self):
        repos_url = self.make_repository("a")
        bzrwt = BzrDir.create_standalone_workingtree("c", 
            format=format.get_rich_root_format())
        self.build_tree({'c/registry/generic.c': "Tour"})
        bzrwt.add("registry")
        bzrwt.add("registry/generic.c")
        revid1 = bzrwt.commit("Add initial directory + file")
        bzrwt.rename_one("registry", "registry.moved")
        os.unlink("c/registry.moved/generic.c")
        bzrwt.remove("registry.moved/generic.c")
        self.build_tree({'c/registry/generic.c': "bla"})
        bzrwt.add("registry")
        bzrwt.add("registry/generic.c")
        revid2 = bzrwt.commit("Do some funky things")
        newdir = BzrDir.open(repos_url+"/trunk")
        newbranch = newdir.import_branch(bzrwt.branch)
        self.assertEquals(revid2, newbranch.last_revision())
        self.assertEquals([revid1, revid2], newbranch.revision_history())
        tree = newbranch.repository.revision_tree(revid2)
        mutter("inventory: %r" % tree.inventory.entries())
        delta = tree.changes_from(bzrwt)
        self.assertFalse(delta.has_changed())
        self.assertTrue(tree.inventory.has_filename("registry"))
        self.assertTrue(tree.inventory.has_filename("registry.moved"))
        self.assertTrue(tree.inventory.has_filename("registry/generic.c"))
        self.assertFalse(tree.inventory.has_filename("registry.moved/generic.c"))
        os.mkdir("n")
        BzrDir.open(repos_url+"/trunk").sprout("n")

    def test_rename_dir_changing_contents(self):
        repos_url = self.make_repository("a")
        bzrwt = BzrDir.create_standalone_workingtree("c", 
            format=format.get_rich_root_format())
        self.build_tree({'c/registry/generic.c': "Tour"})
        bzrwt.add("registry", "dirid")
        bzrwt.add("registry/generic.c", "origid")
        revid1 = bzrwt.commit("Add initial directory + file")
        bzrwt.rename_one("registry/generic.c", "registry/c.c")
        self.build_tree({'c/registry/generic.c': "Tour2"})
        bzrwt.add("registry/generic.c", "newid")
        revid2 = bzrwt.commit("Other change")
        bzrwt.rename_one("registry", "registry.moved")
        revid3 = bzrwt.commit("Rename")
        newdir = BzrDir.open(repos_url+"/trunk")
        newbranch = newdir.import_branch(bzrwt.branch)
        def check(b):
            self.assertEquals([revid1, revid2, revid3], b.revision_history())
            tree = b.repository.revision_tree(revid3)
            self.assertEquals("origid", tree.path2id("registry.moved/c.c"))
            self.assertEquals("newid", tree.path2id("registry.moved/generic.c"))
            self.assertEquals("dirid", tree.path2id("registry.moved"))
        check(newbranch)
        os.mkdir("n")
        BzrDir.open(repos_url+"/trunk").sprout("n")
        copybranch = Branch.open("n")
        check(copybranch)
    
    def test_rename_dir(self):
        repos_url = self.make_repository("a")
        bzrwt = BzrDir.create_standalone_workingtree("c", 
            format=format.get_rich_root_format())
        self.build_tree({'c/registry/generic.c': "Tour"})
        bzrwt.add("registry", "dirid")
        bzrwt.add("registry/generic.c", "origid")
        revid1 = bzrwt.commit("Add initial directory + file")
        bzrwt.rename_one("registry", "registry.moved")
        revid2 = bzrwt.commit("Rename")
        newdir = BzrDir.open(repos_url+"/trunk")
        newbranch = newdir.import_branch(bzrwt.branch)
        def check(b):
            self.assertEquals([revid1, revid2], b.revision_history())
            tree = b.repository.revision_tree(revid2)
            self.assertEquals("origid", tree.path2id("registry.moved/generic.c"))
            self.assertEquals("dirid", tree.path2id("registry.moved"))
        check(newbranch)
        os.mkdir("n")
        BzrDir.open(repos_url+"/trunk").sprout("n")
        copybranch = Branch.open("n")
        check(copybranch)

    def test_push_non_lhs_parent(self):        
        from bzrlib.debug import debug_flags
        debug_flags.add("commit")
        debug_flags.add("fetch")
        repos_url = self.make_repository("a")
        bzrwt = BzrDir.create_standalone_workingtree("c", 
            format=format.get_rich_root_format())
        self.build_tree({'c/registry/generic.c': "Tour"})
        bzrwt.add("registry")
        bzrwt.add("registry/generic.c")
        revid1 = bzrwt.commit("Add initial directory + file", 
                              rev_id="initialrevid")

        # Push first branch into Subversion
        newdir = BzrDir.open(repos_url+"/trunk")
        mapping = newdir.find_repository().get_mapping()
        newbranch = newdir.import_branch(bzrwt.branch)

        # Should create dc/trunk

        dc = self.get_commit_editor(repos_url)
        branches = dc.add_dir("branches")
        branches.add_dir('branches/foo', 'trunk')
        dc.close()

        dc = self.get_commit_editor(repos_url)
        branches = dc.open_dir("branches")
        foo = branches.open_dir("branches/foo")
        registry = foo.open_dir("branches/foo/registry")
        registry.open_file("branches/foo/registry/generic.c").modify("France")
        dc.close()

        merge_revno = ra.RemoteAccess(repos_url).get_latest_revnum()
        merge_revid = newdir.find_repository().generate_revision_id(merge_revno, "branches/foo", mapping)

        self.build_tree({'c/registry/generic.c': "de"})
        revid2 = bzrwt.commit("Change something", rev_id="changerevid")

        # Merge 
        self.build_tree({'c/registry/generic.c': "France"})
        bzrwt.add_pending_merge(merge_revid)
        revid3 = bzrwt.commit("Merge something", rev_id="mergerevid")

        trunk = Branch.open(repos_url + "/branches/foo")
        trunk.pull(bzrwt.branch)

        self.assertEquals([revid1, revid2, revid3], trunk.revision_history())
        self.assertEquals(
                '1 initialrevid\n2 changerevid\n3 mergerevid\n',
                self.client_get_prop(repos_url+"/branches/foo", SVN_PROP_BZR_REVISION_ID+"trunk0"))

    def test_complex_replace_dir(self):
        repos_url = self.make_repository("a")
        bzrwt = BzrDir.create_standalone_workingtree("c", 
            format=format.get_rich_root_format())
        self.build_tree({'c/registry/generic.c': "Tour"})
        bzrwt.add(["registry"], ["origdir"])
        bzrwt.add(["registry/generic.c"], ["file"])
        revid1 = bzrwt.commit("Add initial directory + file")

        bzrwt.remove('registry/generic.c')
        bzrwt.remove('registry')
        bzrwt.add(["registry"], ["newdir"])
        bzrwt.add(["registry/generic.c"], ["file"])
        revid2 = bzrwt.commit("Do some funky things")

        newdir = BzrDir.open(repos_url+"/trunk")
        newbranch = newdir.import_branch(bzrwt.branch)
        self.assertEquals(revid2, newbranch.last_revision())
        self.assertEquals([revid1, revid2], newbranch.revision_history())

        os.mkdir("n")
        BzrDir.open(repos_url+"/trunk").sprout("n")

    def test_push_unnecessary_merge(self):        
        from bzrlib.debug import debug_flags
        debug_flags.add("commit")
        debug_flags.add("fetch")
        repos_url = self.make_repository("a")
        bzrwt = BzrDir.create_standalone_workingtree("c", 
            format=format.get_rich_root_format())
        self.build_tree({'c/registry/generic.c': "Tour"})
        bzrwt.add("registry")
        bzrwt.add("registry/generic.c")
        revid1 = bzrwt.commit("Add initial directory + file", 
                              rev_id="initialrevid")

        # Push first branch into Subversion
        newdir = BzrDir.open(repos_url+"/trunk")
        newbranch = newdir.import_branch(bzrwt.branch)

        c = ra.RemoteAccess(repos_url)
        self.assertTrue(c.check_path("trunk/registry/generic.c", c.get_latest_revnum()) == core.NODE_FILE)

        dc = self.get_commit_editor(repos_url)
        trunk = dc.open_dir("trunk")
        registry = trunk.open_dir("trunk/registry")
        registry.open_file("trunk/registry/generic.c").modify("BLA")
        dc.close()
        mapping = newdir.find_repository().get_mapping()
        merge_revid = newdir.find_repository().generate_revision_id(2, "trunk", mapping)

        # Merge 
        self.build_tree({'c/registry/generic.c': "DE"})
        bzrwt.add_pending_merge(merge_revid)
        self.assertEquals(bzrwt.get_parent_ids()[1], merge_revid)
        revid2 = bzrwt.commit("Merge something", rev_id="mergerevid")
        bzr_parents = bzrwt.branch.repository.get_revision(revid2).parent_ids
        trunk = Branch.open(repos_url + "/trunk")
        trunk.pull(bzrwt.branch)

        self.assertEquals(tuple(bzr_parents), 
                trunk.repository.get_revision(revid2).parent_ids)

        self.assertEquals([revid1, revid2], trunk.revision_history())
        self.assertEquals(
                '1 initialrevid\n2 mergerevid\n',
                self.client_get_prop(repos_url+"/trunk", SVN_PROP_BZR_REVISION_ID+"trunk0"))


class TestPushTwice(TestCaseWithSubversionRepository):
    def test_push_twice(self):
        # bug 208566
        repos_url = self.make_repository('d')

        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_dir("trunk")
        foo = trunk.add_dir("trunk/foo")
        foo.add_file("trunk/foo/bla").modify("data")
        dc.add_dir("branches")
        dc.close()

        svndir = BzrDir.open(repos_url+"/trunk")
        os.mkdir("dc")
        bzrdir = svndir.sprout("dc")
        wt = bzrdir.open_workingtree()
        revid = wt.commit(message="Commit from Bzr")
        expected_history = wt.branch.revision_history()

        svndir1 = BzrDir.open(repos_url+"/branches/a")
        svndir1.import_branch(wt.branch)
        self.assertEquals(expected_history, svndir1.open_branch().revision_history())

        svndir2 = BzrDir.open(repos_url+"/branches/b")
        svndir2.import_branch(wt.branch)
        self.assertEquals(expected_history, svndir2.open_branch().revision_history())

        revid = wt.commit(message="Commit from Bzr")
        expected_history = wt.branch.revision_history()

        svndir1.open_branch().pull(wt.branch)
        self.assertEquals(expected_history, svndir1.open_branch().revision_history())
        svndir2.open_branch().pull(wt.branch)
        self.assertEquals(expected_history, svndir2.open_branch().revision_history())
