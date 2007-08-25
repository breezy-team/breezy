# Copyright (C) 2006-2007 Jelmer Vernooij <jelmer@samba.org>

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

"""Commit and push tests."""

from bzrlib.branch import Branch, PullResult
from bzrlib.bzrdir import BzrDir
from bzrlib.errors import DivergedBranches, BzrError
from bzrlib.trace import mutter
from bzrlib.workingtree import WorkingTree

from copy import copy
from repository import MAPPING_VERSION
import os
from tests import TestCaseWithSubversionRepository

class TestNativeCommit(TestCaseWithSubversionRepository):
    def test_simple_commit(self):
        self.make_client('d', 'dc')
        self.build_tree({'dc/foo/bla': "data"})
        self.client_add("dc/foo")
        wt = self.open_checkout("dc")
        revid = wt.commit(message="data")
        self.assertEqual(wt.branch.generate_revision_id(1), revid)
        self.client_update("dc")
        self.assertEqual(wt.branch.generate_revision_id(1), 
                wt.branch.last_revision())
        wt = WorkingTree.open("dc")
        new_inventory = wt.branch.repository.get_inventory(
                            wt.branch.last_revision())
        self.assertTrue(new_inventory.has_filename("foo"))
        self.assertTrue(new_inventory.has_filename("foo/bla"))

    def test_commit_message(self):
        self.make_client('d', 'dc')
        self.build_tree({'dc/foo/bla': "data"})
        self.client_add("dc/foo")
        wt = self.open_checkout("dc")
        revid = wt.commit(message="data")
        self.assertEqual(wt.branch.generate_revision_id(1), revid)
        self.assertEqual(
                wt.branch.generate_revision_id(1), wt.branch.last_revision())
        new_revision = wt.branch.repository.get_revision(
                            wt.branch.last_revision())
        self.assertEqual(wt.branch.last_revision(), new_revision.revision_id)
        self.assertEqual("data", new_revision.message)

    def test_commit_rev_id(self):
        self.make_client('d', 'dc')
        self.build_tree({'dc/foo/bla': "data"})
        self.client_add("dc/foo")
        wt = self.open_checkout("dc")
        revid = wt.commit(message="data", rev_id="some-revid-bla")
        self.assertEqual("some-revid-bla", revid)
        self.assertEqual(wt.branch.generate_revision_id(1), revid)
        self.assertEqual(
                wt.branch.generate_revision_id(1), wt.branch.last_revision())
        new_revision = wt.branch.repository.get_revision(
                            wt.branch.last_revision())
        self.assertEqual(wt.branch.last_revision(), new_revision.revision_id)

    def test_commit_local(self):
        self.make_client('d', 'dc')
        self.build_tree({'dc/foo/bla': "data"})
        self.client_add("dc/foo")
        wt = self.open_checkout("dc")
        self.assertRaises(BzrError, wt.commit, 
                message="data", local=True)

    def test_commit_committer(self):
        self.make_client('d', 'dc')
        self.build_tree({'dc/foo/bla': "data"})
        self.client_add("dc/foo")
        wt = self.open_checkout("dc")
        revid = wt.commit(message="data", committer="john doe")
        rev = wt.branch.repository.get_revision(revid)
        self.assertEquals("john doe", rev.committer)

    def test_commit_message_nordic(self):
        self.make_client('d', 'dc')
        self.build_tree({'dc/foo/bla': "data"})
        self.client_add("dc/foo")
        wt = self.open_checkout("dc")
        revid = wt.commit(message=u"\xe6\xf8\xe5")
        self.assertEqual(revid, wt.branch.generate_revision_id(1))
        self.assertEqual(
                wt.branch.generate_revision_id(1), wt.branch.last_revision())
        new_revision = wt.branch.repository.get_revision(
                            wt.branch.last_revision())
        self.assertEqual(wt.branch.last_revision(), new_revision.revision_id)
        self.assertEqual(u"\xe6\xf8\xe5", new_revision.message.decode("utf-8"))

    def test_commit_update(self):
        self.make_client('d', 'dc')
        self.build_tree({'dc/foo/bla': "data"})
        self.client_add("dc/foo")
        wt = self.open_checkout("dc")
        wt.set_pending_merges(["some-ghost-revision"])
        wt.commit(message="data")
        self.assertEqual(
                wt.branch.generate_revision_id(1),
                wt.branch.last_revision())

    def test_commit_parents(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo/bla': "data"})
        self.client_add("dc/foo")
        wt = self.open_checkout("dc")
        wt.set_pending_merges(["some-ghost-revision"])
        self.assertEqual(["some-ghost-revision"], wt.pending_merges())
        wt.commit(message="data")
        self.assertEqual("some-ghost-revision\n", 
                self.client_get_prop(repos_url, "bzr:ancestry:v3-none", 1))
        self.assertEqual([wt.branch.generate_revision_id(0), "some-ghost-revision"],
                         wt.branch.repository.revision_parents(
                             wt.branch.last_revision()))

    def test_commit_rename_file(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/foo': "data"})
        self.client_add("dc/foo")
        wt = self.open_checkout("dc")
        wt.set_pending_merges(["some-ghost-revision"])
        oldid = wt.path2id("foo")
        wt.commit(message="data")
        wt.rename_one("foo", "bar")
        wt.commit(message="doe")
        paths = self.client_log("dc", 2, 0)[2][0]
        self.assertEquals('D', paths["/foo"].action)
        self.assertEquals('A', paths["/bar"].action)
        self.assertEquals('/foo', paths["/bar"].copyfrom_path)
        self.assertEquals(1, paths["/bar"].copyfrom_rev)
        self.assertEquals("bar\t%s\n" % oldid, 
                          self.client_get_prop(repos_url, "bzr:file-ids", 2))

    def test_commit_rename_file_from_directory(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/adir/foo': "data"})
        self.client_add("dc/adir")
        wt = self.open_checkout("dc")
        wt.commit(message="data")
        wt.rename_one("adir/foo", "bar")
        self.assertFalse(wt.has_filename("adir/foo"))
        self.assertTrue(wt.has_filename("bar"))
        wt.commit(message="doe")
        paths = self.client_log("dc", 2, 0)[2][0]
        self.assertEquals('D', paths["/adir/foo"].action)
        self.assertEquals('A', paths["/bar"].action)
        self.assertEquals('/adir/foo', paths["/bar"].copyfrom_path)
        self.assertEquals(1, paths["/bar"].copyfrom_rev)

    def test_commit_revision_id(self):
        repos_url = self.make_client('d', 'dc')
        wt = self.open_checkout("dc")
        self.build_tree({'dc/foo/bla': "data", 'dc/bla': "otherdata"})
        wt.add('bla')
        wt.commit(message="data")

        branch = Branch.open(repos_url)
        builder = branch.get_commit_builder([branch.last_revision()], 
                revision_id="my-revision-id")
        tree = branch.repository.revision_tree(branch.last_revision())
        new_tree = copy(tree)
        ie = new_tree.inventory.root
        ie.revision = None
        builder.record_entry_contents(ie, [tree.inventory], '', new_tree)
        builder.finish_inventory()
        builder.commit("foo")

        self.assertEqual("3 my-revision-id\n", 
            self.client_get_prop("dc", 
                "bzr:revision-id:v%d-none" % MAPPING_VERSION, 2))

    def test_commit_metadata(self):
        repos_url = self.make_client('d', 'dc')
        wt = self.open_checkout("dc")
        self.build_tree({'dc/foo/bla': "data", 'dc/bla': "otherdata"})
        wt.add('bla')
        wt.commit(message="data")

        branch = Branch.open(repos_url)
        builder = branch.get_commit_builder([branch.last_revision()], 
                timestamp=4534.0, timezone=2, committer="fry",
                revision_id="my-revision-id")
        tree = branch.repository.revision_tree(branch.last_revision())
        new_tree = copy(tree)
        ie = new_tree.inventory.root
        ie.revision = None
        builder.record_entry_contents(ie, [tree.inventory], '', new_tree)
        builder.finish_inventory()
        builder.commit("foo")

        self.assertEqual("3 my-revision-id\n", 
                self.client_get_prop("dc", "bzr:revision-id:v%d-none" % MAPPING_VERSION, 2))

        self.assertEqual(
                "timestamp: 1970-01-01 01:15:36.000000000 +0000\ncommitter: fry\n",
                self.client_get_prop("dc", "bzr:revision-info", 2))

    def test_mwh(self):
        repo = self.make_client('d', 'sc')
        def mv(*mvs):
            for a, b in mvs:
                self.client_copy(a, b)
                self.client_delete(a)
            self.client_commit('sc', '.')
            self.client_update('sc')
        self.build_tree({'sc/de/foo':'data', 'sc/de/bar':'DATA'})
        self.client_add('sc/de')
        self.client_commit('sc', 'blah') #1
        self.client_update('sc')
        os.mkdir('sc/de/trunk')
        self.client_add('sc/de/trunk')
        mv(('sc/de/foo', 'sc/de/trunk'), ('sc/de/bar', 'sc/de/trunk')) #2
        mv(('sc/de', 'sc/pyd'))  #3
        self.client_delete('sc/pyd/trunk/foo')
        self.client_commit('sc', '.') #4
        self.client_update('sc')

        self.make_checkout(repo + '/pyd/trunk', 'pyd')
        self.assertEqual("DATA", open('pyd/bar').read())

        olddir = BzrDir.open("pyd")
        os.mkdir('bc')
        newdir = olddir.sprout("bc")
        newdir.open_branch().pull(olddir.open_branch())
        wt = newdir.open_workingtree()
        self.assertEqual("DATA", open('bc/bar').read())
        open('bc/bar', 'w').write('data')
        wt.commit(message="Commit from Bzr")
        olddir.open_branch().pull(newdir.open_branch())

        self.client_update('pyd')
        self.assertEqual("data", open('pyd/bar').read())
        

class TestPush(TestCaseWithSubversionRepository):
    def setUp(self):
        super(TestPush, self).setUp()
        self.repos_url = self.make_client('d', 'sc')

        self.build_tree({'sc/foo/bla': "data"})
        self.client_add("sc/foo")
        self.client_commit("sc", "foo")

        self.olddir = self.open_checkout_bzrdir("sc")
        os.mkdir("dc")
        self.newdir = self.olddir.sprout("dc")

    def test_empty(self):
        self.assertEqual(0, int(self.olddir.open_branch().pull(
                                self.newdir.open_branch())))

    def test_empty_result(self):
        result = self.olddir.open_branch().pull(self.newdir.open_branch())
        self.assertIsInstance(result, PullResult)
        self.assertEqual(result.old_revno, self.olddir.open_branch().revno())
        self.assertEqual(result.master_branch, None)
        self.assertEqual(result.target_branch.bzrdir.transport.base, self.olddir.transport.base)
        self.assertEqual(result.source_branch.bzrdir.transport.base, self.newdir.transport.base)

    def test_child(self):
        self.build_tree({'sc/foo/bar': "data"})
        self.client_add("sc/foo/bar")
        self.client_commit("sc", "second message")

        self.assertEqual(0, int(self.olddir.open_branch().pull(
                                self.newdir.open_branch())))

    def test_diverged(self):
        self.build_tree({'sc/foo/bar': "data"})
        self.client_add("sc/foo/bar")
        self.client_commit("sc", "second message")

        olddir = BzrDir.open("sc")

        self.build_tree({'dc/file': 'data'})
        wt = self.newdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.assertRaises(DivergedBranches, 
                          olddir.open_branch().pull,
                          self.newdir.open_branch())

    def test_change(self):
        self.build_tree({'dc/foo/bla': 'other data'})
        wt = self.newdir.open_workingtree()
        wt.commit(message="Commit from Bzr")

        self.olddir.open_branch().pull(self.newdir.open_branch())

        repos = self.olddir.find_repository()
        inv = repos.get_inventory(repos.generate_revision_id(2, "", "none"))
        self.assertEqual(repos.generate_revision_id(2, "", "none"),
                         inv[inv.path2id('foo/bla')].revision)
        self.assertEqual(wt.branch.last_revision(),
          repos.generate_revision_id(2, "", "none"))
        self.assertEqual(wt.branch.last_revision(),
                        self.olddir.open_branch().last_revision())
        self.assertEqual("other data", 
            repos.revision_tree(repos.generate_revision_id(2, "", "none")).get_file_text( inv.path2id("foo/bla")))

    def test_simple(self):
        self.build_tree({'dc/file': 'data'})
        wt = self.newdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.olddir.open_branch().pull(self.newdir.open_branch())

        repos = self.olddir.find_repository()
        inv = repos.get_inventory(repos.generate_revision_id(2, "", "none"))
        self.assertTrue(inv.has_filename('file'))
        self.assertEqual(wt.branch.last_revision(), 
                repos.generate_revision_id(2, "", "none"))
        self.assertEqual(repos.generate_revision_id(2, "", "none"),
                        self.olddir.open_branch().last_revision())

    def test_pull_after_push(self):
        self.build_tree({'dc/file': 'data'})
        wt = self.newdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.olddir.open_branch().pull(self.newdir.open_branch())

        repos = self.olddir.find_repository()
        inv = repos.get_inventory(repos.generate_revision_id(2, "", "none"))
        self.assertTrue(inv.has_filename('file'))
        self.assertEquals(wt.branch.last_revision(), 
                         repos.generate_revision_id(2, "", "none"))

        self.assertEqual(repos.generate_revision_id(2, "", "none"),
                        self.olddir.open_branch().last_revision())

        self.newdir.open_branch().pull(self.olddir.open_branch())

        self.assertEqual(repos.generate_revision_id(2, "", "none"),
                        self.newdir.open_branch().last_revision())

    def test_message(self):
        self.build_tree({'dc/file': 'data'})
        wt = self.newdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")

        self.olddir.open_branch().pull(self.newdir.open_branch())

        repos = self.olddir.find_repository()
        self.assertEqual("Commit from Bzr",
            repos.get_revision(
                repos.generate_revision_id(2, "", "none")).message)

    def test_message_nordic(self):
        self.build_tree({'dc/file': 'data'})
        wt = self.newdir.open_workingtree()
        wt.add('file')
        wt.commit(message=u"\xe6\xf8\xe5")

        self.olddir.open_branch().pull(self.newdir.open_branch())

        repos = self.olddir.find_repository()
        self.assertEqual(u"\xe6\xf8\xe5", repos.get_revision(
            repos.generate_revision_id(2, "", "none")).message.decode("utf-8"))

    def test_commit_rename_file(self):
        self.build_tree({'dc/vla': "data"})
        wt = self.newdir.open_workingtree()
        wt.add("vla")
        wt.set_pending_merges(["some-ghost-revision"])
        wt.commit(message="data")
        wt.rename_one("vla", "bar")
        wt.commit(message="doe")
        self.olddir.open_branch().pull(self.newdir.open_branch())
        paths = self.client_log(self.repos_url, 3, 0)[3][0]
        self.assertEquals('D', paths["/vla"].action)
        self.assertEquals('A', paths["/bar"].action)
        self.assertEquals('/vla', paths["/bar"].copyfrom_path)
        self.assertEquals(2, paths["/bar"].copyfrom_rev)

    def test_commit_rename_file_from_directory(self):
        wt = self.newdir.open_workingtree()
        self.build_tree({'dc/adir/foo': "data"})
        wt.add("adir")
        wt.add("adir/foo")
        wt.commit(message="data")
        wt.rename_one("adir/foo", "bar")
        self.assertTrue(wt.has_filename("bar"))
        self.assertFalse(wt.has_filename("adir/foo"))
        wt.commit(message="doe")
        self.olddir.open_branch().pull(self.newdir.open_branch())
        paths = self.client_log(self.repos_url, 3, 0)[3][0]
        mutter('paths %r' % paths)
        self.assertEquals('D', paths["/adir/foo"].action)
        self.assertEquals('A', paths["/bar"].action)
        self.assertEquals('/adir/foo', paths["/bar"].copyfrom_path)
        self.assertEquals(2, paths["/bar"].copyfrom_rev)

    def test_commit_remove(self):
        wt = self.newdir.open_workingtree()
        self.build_tree({'dc/foob': "data"})
        wt.add("foob")
        wt.commit(message="data")
        wt.remove(["foob"])
        wt.commit(message="doe")
        self.olddir.open_branch().pull(self.newdir.open_branch())
        paths = self.client_log(self.repos_url, 3, 0)[3][0]
        mutter('paths %r' % paths)
        self.assertEquals('D', paths["/foob"].action)

    def test_commit_rename_remove_parent(self):
        wt = self.newdir.open_workingtree()
        self.build_tree({'dc/adir/foob': "data"})
        wt.add("adir")
        wt.add("adir/foob")
        wt.commit(message="data")
        wt.rename_one("adir/foob", "bar")
        wt.remove(["adir"])
        wt.commit(message="doe")
        self.olddir.open_branch().pull(self.newdir.open_branch())
        paths = self.client_log(self.repos_url, 3, 0)[3][0]
        mutter('paths %r' % paths)
        self.assertEquals('D', paths["/adir"].action)
        self.assertEquals('A', paths["/bar"].action)
        self.assertEquals('/adir/foob', paths["/bar"].copyfrom_path)
        self.assertEquals(2, paths["/bar"].copyfrom_rev)

    def test_commit_remove_nested(self):
        wt = self.newdir.open_workingtree()
        self.build_tree({'dc/adir/foob': "data"})
        wt.add("adir")
        wt.add("adir/foob")
        wt.commit(message="data")
        wt.remove(["adir/foob"])
        wt.commit(message="doe")
        self.olddir.open_branch().pull(self.newdir.open_branch())
        paths = self.client_log(self.repos_url, 3, 0)[3][0]
        mutter('paths %r' % paths)
        self.assertEquals('D', paths["/adir/foob"].action)


class TestPushNested(TestCaseWithSubversionRepository):
    def setUp(self):
        super(TestPushNested, self).setUp()
        self.repos_url = self.make_client('d', 'sc')

        self.build_tree({'sc/foo/trunk/bla': "data"})
        self.client_add("sc/foo")
        self.client_commit("sc", "foo")

        self.olddir = self.open_checkout_bzrdir("sc/foo/trunk")
        os.mkdir("dc")
        self.newdir = self.olddir.sprout("dc")

    def test_simple(self):
        self.build_tree({'dc/file': 'data'})
        wt = self.newdir.open_workingtree()
        wt.add('file')
        wt.commit(message="Commit from Bzr")
        self.olddir.open_branch().pull(self.newdir.open_branch())
        repos = self.olddir.find_repository()
        self.client_update("sc")
        self.assertTrue(os.path.exists("sc/foo/trunk/file"))
        self.assertFalse(os.path.exists("sc/foo/trunk/filel"))


class HeavyWeightCheckoutTests(TestCaseWithSubversionRepository):
    def test_bind(self):
        repos_url = self.make_client("d", "sc")
        master_branch = Branch.open(repos_url)
        os.mkdir("b")
        local_dir = master_branch.bzrdir.sprout("b")
        wt = local_dir.open_workingtree()
        local_dir.open_branch().bind(master_branch)
        local_dir.open_branch().unbind()

    def test_commit(self):
        repos_url = self.make_client("d", "sc")
        master_branch = Branch.open(repos_url)
        os.mkdir("b")
        local_dir = master_branch.bzrdir.sprout("b")
        wt = local_dir.open_workingtree()
        local_dir.open_branch().bind(master_branch)
        self.build_tree({'b/file': 'data'})
        wt.add('file')
        revid = wt.commit(message="Commit from Bzr")
        master_branch = Branch.open(repos_url)
        self.assertEquals(revid, master_branch.last_revision())

    def test_fileid(self):
        repos_url = self.make_client("d", "sc")
        master_branch = Branch.open(repos_url)
        os.mkdir("b")
        local_dir = master_branch.bzrdir.sprout("b")
        wt = local_dir.open_workingtree()
        local_dir.open_branch().bind(master_branch)
        self.build_tree({'b/file': 'data'})
        wt.add('file')
        oldid = wt.path2id("file")
        revid1 = wt.commit(message="Commit from Bzr")
        wt.rename_one('file', 'file2')
        revid2 = wt.commit(message="Commit from Bzr")
        master_branch = Branch.open(repos_url)
        self.assertEquals("file\t%s\n" % oldid, 
                          self.client_get_prop(repos_url, "bzr:file-ids", 1))
        self.assertEquals("file2\t%s\n" % oldid, 
                          self.client_get_prop(repos_url, "bzr:file-ids", 2))
        tree1 = master_branch.repository.revision_tree(revid1)
        tree2 = master_branch.repository.revision_tree(revid2)
        delta = tree2.changes_from(tree1)
        self.assertEquals(0, len(delta.added))
        self.assertEquals(0, len(delta.removed))
        self.assertEquals(1, len(delta.renamed))

    def test_nested_fileid(self):
        repos_url = self.make_client("d", "sc")
        master_branch = Branch.open(repos_url)
        os.mkdir("b")
        local_dir = master_branch.bzrdir.sprout("b")
        wt = local_dir.open_workingtree()
        local_dir.open_branch().bind(master_branch)
        self.build_tree({'b/dir/file': 'data'})
        wt.add('dir')
        wt.add('dir/file')
        dirid = wt.path2id("dir")
        fileid = wt.path2id("dir/file")
        revid1 = wt.commit(message="Commit from Bzr")
        master_branch = Branch.open(repos_url)
        self.assertEquals("dir\t%s\n" % dirid +
                          "dir/file\t%s\n" % fileid, 
                          self.client_get_prop(repos_url, "bzr:file-ids", 1))
