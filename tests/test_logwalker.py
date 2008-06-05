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

"""Log walker tests."""

from bzrlib.errors import NoSuchRevision

import os
from bzrlib.plugins.svn import logwalker
from bzrlib import debug
from bzrlib.plugins.svn.tests import TestCaseWithSubversionRepository
from bzrlib.plugins.svn.transport import SvnRaTransport

class TestLogWalker(TestCaseWithSubversionRepository):
    def setUp(self):
        super(TestLogWalker, self).setUp()
        debug.debug_flags.add("transport")

    def get_log_walker(self, transport):
        return logwalker.LogWalker(transport)

    def test_create(self):
        repos_url = self.make_repository("a")
        self.get_log_walker(transport=SvnRaTransport(repos_url))

    def test_get_branch_log(self):
        repos_url = self.make_repository("a")
        cb = self.commit_editor(repos_url)
        cb.add_file("foo")
        cb.done()

        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))

        self.assertEqual(2, len(list(walker.iter_changes(None, 1))))

    def test_get_branch_follow_branch(self):
        repos_url = self.make_repository("a")
        cb = self.commit_editor(repos_url)
        cb.add_dir("trunk")
        cb.done()

        cb = self.commit_editor(repos_url)
        cb.add_dir("branches")
        cb.done()
        
        cb = self.commit_editor(repos_url)
        cb.add_dir("branches/foo", "trunk")
        cb.done()

        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))

        self.assertEqual(2, len(list(walker.iter_changes(["branches/foo"], 3))))

    def test_get_branch_follow_branch_changing_parent(self):
        repos_url = self.make_repository("a")
        cb = self.commit_editor(repos_url)
        cb.add_dir("trunk")
        cb.add_file("trunk/foo")
        cb.done()

        cb = self.commit_editor(repos_url)
        cb.add_dir("branches")
        cb.done()

        cb = self.commit_editor(repos_url)
        cb.add_dir("branches/abranch", "trunk")
        cb.done()

        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))

        self.assertEquals([
            ({"branches/abranch": ('A', 'trunk', 2)}, 3),
            ({"trunk/foo": ('A', None, -1), 
                           "trunk": ('A', None, -1)}, 1)
            ], [l[:2] for l in walker.iter_changes(["branches/abranch/foo"], 3)])

    def test_get_revision_paths(self):
        repos_url = self.make_repository("a")
        cb = self.commit_editor(repos_url)
        cb.add_file("foo")
        cb.done()
        walker = self.get_log_walker(SvnRaTransport(repos_url))
        self.assertEqual({"foo": ('A', None, -1)}, walker.get_revision_paths(1))
        self.assertEqual({"": ('A', None, -1)}, walker.get_revision_paths(0))

    def test_get_revision_paths_zero(self):
        repos_url = self.make_repository("a")
        walker = self.get_log_walker(SvnRaTransport(repos_url))
        self.assertEqual({'': ('A', None, -1)}, walker.get_revision_paths(0))

    def test_get_revision_paths_invalid(self):
        repos_url = self.make_repository("a")
        walker = self.get_log_walker(SvnRaTransport(repos_url))
        self.assertRaises(NoSuchRevision, lambda: walker.get_revision_paths(42))

    def test_get_branch_invalid_revision(self):
        repos_url = self.make_repository("a")
        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))
        self.assertRaises(NoSuchRevision, list, 
                          walker.iter_changes(["/"], 20))

    def test_branch_log_all(self):
        repos_url = self.make_repository("a")
        cb = self.commit_editor(repos_url)
        cb.add_dir("trunk")
        cb.add_file("trunk/file")
        cb.add_dir("foo")
        cb.add_file("foo/file")
        cb.done()

        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))

        self.assertEqual(2, len(list(walker.iter_changes([""], 1))))

    def test_branch_log_specific(self):
        repos_url = self.make_repository("a")
        cb = self.commit_editor(repos_url)
        cb.add_dir("branches")
        cb.add_dir("branches/brancha")
        cb.add_dir("branches/branchb")
        cb.add_dir("branches/branchab")
        cb.add_file("branches/brancha/data")
        cb.add_file("branches/branchab/data")
        cb.done()

        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))

        self.assertEqual(1, len(list(walker.iter_changes(["branches/brancha"],
            1))))

    def test_iter_changes_ignore_unchanged(self):
        repos_url = self.make_repository("a")
        cb = self.commit_editor(repos_url)
        cb.add_dir("branches")
        cb.add_dir("branches/brancha")
        cb.add_dir("branches/branchab")
        cb.add_file("branches/brancha/data")
        cb.done()

        cb = self.commit_editor(repos_url)
        cb.add_file("branches/branchab/data")
        cb.done()

        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))

        self.assertEqual(1, len(list(walker.iter_changes(["branches/brancha"],
            2))))

    def test_find_latest_none(self):
        repos_url = self.make_repository("a")
        cb = self.commit_editor(repos_url)
        cb.add_dir("branches")
        cb.done()

        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))

        self.assertEqual(1, walker.find_latest_change("", 1))
    
    def test_find_latest_children_root(self):
        repos_url = self.make_repository("a")
        cb = self.commit_editor(repos_url)
        cb.add_file("branches")
        cb.done()

        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))

        self.assertEqual(1, 
            walker.find_latest_change("", 1))

    def test_find_latest_case(self):
        repos_url = self.make_repository("a")
        cb = self.commit_editor(repos_url)
        cb.add_dir("branches")
        cb.add_file("branches/child")
        cb.done()

        cb = self.commit_editor(repos_url)
        cb.add_dir("BRANCHES")
        cb.add_file("BRANCHES/child")
        cb.done()

        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))

        self.assertEqual(1, 
            walker.find_latest_change("branches", 2))

    def test_find_latest_parent(self):
        repos_url = self.make_repository("a")
        cb = self.commit_editor(repos_url)
        cb.add_dir("branches")
        cb.add_dir("tags")
        cb.add_dir("branches/tmp")
        cb.add_dir("branches/tmp/foo")
        cb.done()

        cb = self.commit_editor(repos_url)
        cb.add_dir("tags/tmp", "branches/tmp")
        cb.done()

        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))

        self.assertEqual(2, walker.find_latest_change("tags/tmp/foo", 2))

    def test_find_latest_parent_just_modify(self):
        repos_url = self.make_repository("a")

        cb = self.commit_editor(repos_url)
        cb.add_dir("branches")
        cb.add_dir("branches/tmp")
        cb.add_dir("branches/tmp/foo")
        cb.add_dir("tags")
        cb.done()

        cb = self.commit_editor(repos_url)
        cb.add_dir("tags/tmp", "branches/tmp")
        cb.done()

        cb = self.commit_editor(repos_url)
        cb.change_dir_prop("tags", "myprop", "mydata")
        cb.done()

        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))
        self.assertEqual(2, walker.find_latest_change("tags/tmp/foo", 3))

    def test_find_latest_parentmoved(self):
        repos_url = self.make_repository("a")

        cb = self.commit_editor(repos_url)
        cb.add_dir("branches")
        cb.add_dir("branches/tmp")
        cb.done()

        cb = self.commit_editor(repos_url)
        cb.add_dir("bla", "branches")
        cb.done()

        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))

        self.assertIs(2, walker.find_latest_change("bla/tmp", 2))

    def test_find_latest_nonexistant(self):
        repos_url = self.make_repository("a")

        cb = self.commit_editor(repos_url)
        cb.add_dir("branches")
        cb.add_dir("branches/tmp")
        cb.done()

        cb = self.commit_editor(repos_url)
        cb.add_dir("bla", "branches")
        cb.done()

        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))

        self.assertIs(None, walker.find_latest_change("bloe", 2))
        self.assertIs(None, walker.find_latest_change("bloe/bla", 2))

    def test_find_latest_change(self):
        repos_url = self.make_repository("a")

        cb = self.commit_editor(repos_url)
        cb.add_dir("branches")
        cb.done()

        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))

        self.assertEqual(1, walker.find_latest_change("branches", 1))

    def test_find_latest_change_children(self):
        repos_url = self.make_repository("a")

        cb = self.commit_editor(repos_url)
        cb.add_dir("branches")
        cb.done()

        cb = self.commit_editor(repos_url)
        cb.add_file("branches/foo")
        cb.done()

        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))

        self.assertEqual(2, walker.find_latest_change("branches", 2))

    def test_find_latest_change_prop(self):
        repos_url = self.make_repository("a")

        cb = self.commit_editor(repos_url)
        cb.add_dir("branches")
        cb.done()

        cb = self.commit_editor(repos_url)
        cb.change_dir_prop("branches", "myprop", "mydata")
        cb.done()

        cb = self.commit_editor(repos_url)
        cb.add_file("branches/foo")
        cb.done()

        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))

        self.assertEqual(3, walker.find_latest_change("branches", 3))

    def test_find_latest_change_file(self):
        repos_url = self.make_repository("a")

        cb = self.commit_editor(repos_url)
        cb.add_dir("branches")
        cb.done()

        cb = self.commit_editor(repos_url)
        cb.add_file("branches/foo")
        cb.done()

        cb = self.commit_editor(repos_url)
        cb.change_file("branches/foo")
        cb.done()

        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))

        self.assertEqual(3, walker.find_latest_change("branches/foo", 3))

    def test_find_latest_change_newer(self):
        repos_url = self.make_repository("a")

        cb = self.commit_editor(repos_url)
        cb.add_dir("branches")
        cb.done()

        cb = self.commit_editor(repos_url)
        cb.add_file("branches/foo")
        cb.done()

        cb = self.commit_editor(repos_url)
        cb.change_file("branches/foo")
        cb.done()

        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))

        self.assertEqual(2, walker.find_latest_change("branches/foo", 2))

    def test_follow_history_branch_replace(self):
        repos_url = self.make_repository("a")

        cb = self.commit_editor(repos_url)
        cb.add_dir("trunk")
        cb.add_file("trunk/data")
        cb.done()
        
        cb = self.commit_editor(repos_url)
        cb.delete("trunk")
        cb.done()

        cb = self.commit_editor(repos_url)
        cb.add_dir("trunk")
        cb.add_file("trunk/data")
        cb.done()

        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))
        self.assertEqual([({"trunk/data": ('A', None, -1),
                                     "trunk": ('A', None, -1)}, 3)], 
                                     [l[:2] for l in walker.iter_changes(["trunk"], 3)])

    def test_follow_history(self):
        repos_url = self.make_repository("a")
        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))

        cb = self.commit_editor(repos_url)
        cb.add_file("foo")
        cb.done()

        for (paths, rev, revprops) in walker.iter_changes([""], 1):
            self.assertTrue(rev == 0 or paths.has_key("foo"))
            self.assertTrue(rev in (0,1))

    def test_follow_history_nohist(self):
        repos_url = self.make_repository("a")
        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))

        self.assertEqual([({'': ('A', None, -1)}, 0)], [l[:2] for l in walker.iter_changes([""], 0)])

    def test_later_update(self):
        repos_url = self.make_repository("a")

        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))

        cb = self.commit_editor(repos_url)
        cb.add_file("foo")
        cb.done()

        for (paths, rev, revprops) in walker.iter_changes([""], 1):
            self.assertTrue(rev == 0 or paths.has_key("foo"))
            self.assertTrue(rev in (0,1))

        iter = walker.iter_changes([""], 2)
        self.assertRaises(NoSuchRevision, list, iter)

    def test_get_branch_log_follow(self):
        repos_url = self.make_repository("a")
        cb = self.commit_editor(repos_url)
        cb.add_dir("trunk")
        cb.add_dir("branches")
        cb.add_file("trunk/afile")
        cb.done()

        cb = self.commit_editor(repos_url)
        cb.add_dir("branches/abranch", "trunk")
        cb.done()

        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))

        items = [l[:2] for l in walker.iter_changes(["branches/abranch"], 2)]
        self.assertEqual([({'branches/abranch': ('A', 'trunk', 1)}, 2), 
                          ({'branches': (u'A', None, -1),
                                     'trunk/afile': ('A', None, -1), 
                                     'trunk': (u'A', None, -1)}, 1)], items)

    def test_get_previous_root(self):
        repos_url = self.make_repository("a")

        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))

        self.assertEqual((None, -1), walker.get_previous("", 0))

    def test_get_previous_simple(self):
        repos_url = self.make_repository("a")

        cb = self.commit_editor(repos_url)
        cb.add_dir("trunk")
        cb.add_file("trunk/file")
        cb.done()

        cb = self.commit_editor(repos_url)
        cb.add_file("trunk/afile")
        cb.change_dir_prop("trunk", "myprop", "mydata")
        cb.done()

        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))

        self.assertEqual(("trunk", 1), walker.get_previous("trunk", 2))

    def test_get_previous_added(self):
        repos_url = self.make_repository("a")

        cb = self.commit_editor(repos_url)
        cb.add_dir("trunk")
        cb.add_file("trunk/afile")
        cb.done()

        cb = self.commit_editor(repos_url)
        cb.change_file("trunk/afile")
        cb.change_dir_prop("trunk", "myprop", "mydata")
        cb.done()

        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))

        self.assertEqual((None, -1), walker.get_previous("trunk", 1))

    def test_get_previous_copy(self):
        repos_url = self.make_repository("a")

        cb = self.commit_editor(repos_url)
        cb.add_dir("trunk")
        cb.add_file("trunk/afile")
        cb.done()

        cb = self.commit_editor(repos_url)
        cb.add_dir("anotherfile", "trunk")
        cb.done()

        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))

        self.assertEqual(("trunk", 1), walker.get_previous("anotherfile", 2))

    def test_find_children_empty(self):
        repos_url = self.make_repository("a")

        cb = self.commit_editor(repos_url)
        cb.add_dir("trunk")
        cb.done()

        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))

        self.assertEqual([], list(walker.find_children("trunk", 1)))

    def test_find_children_one(self):
        repos_url = self.make_repository("a")

        cb = self.commit_editor(repos_url)
        cb.add_dir("trunk")
        cb.add_file("trunk/data")
        cb.done()

        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))

        self.assertEqual(['trunk/data'], list(walker.find_children("trunk", 1)))

    def test_find_children_nested(self):
        repos_url = self.make_repository("a")

        cb = self.commit_editor(repos_url)
        cb.add_dir("trunk")
        cb.add_dir("trunk/data")
        cb.add_file("trunk/data/bla")
        cb.add_file("trunk/file")
        cb.done()

        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))

        self.assertEqual(
                set(['trunk/data', 'trunk/data/bla', 'trunk/file']), 
                set(walker.find_children("trunk", 1)))

    def test_find_children_later(self):
        repos_url = self.make_repository("a")

        cb = self.commit_editor(repos_url)
        cb.add_dir("trunk")
        cb.add_dir("trunk/data")
        cb.add_file("trunk/data/bla")
        cb.done()

        cb = self.commit_editor(repos_url)
        cb.add_file("trunk/file")
        cb.done()
        
        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))

        self.assertEqual(set(['trunk/data', 'trunk/data/bla']), 
                set(walker.find_children("trunk", 1)))
        self.assertEqual(set(['trunk/data', 'trunk/data/bla', 'trunk/file']), 
                set(walker.find_children("trunk", 2)))

    def test_find_children_copy(self):
        repos_url = self.make_repository("a")

        cb = self.commit_editor(repos_url)
        cb.add_dir("trunk")
        cb.add_dir("trunk/data")
        cb.add_dir("trunk/db")
        cb.add_file("trunk/data/bla")
        cb.add_file("trunk/db/f1")
        cb.add_file("trunk/db/f2")
        cb.done()

        cb = self.commit_editor(repos_url)
        cb.add_dir("trunk/data/fg", "trunk/db")
        cb.done()

        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))

        self.assertEqual(set(['trunk/data', 'trunk/data/bla', 
                          'trunk/data/fg', 'trunk/data/fg/f1', 
                          'trunk/data/fg/f2', 'trunk/db',
                          'trunk/db/f1', 'trunk/db/f2']), 
                set(walker.find_children("trunk", 2)))

    def test_find_children_copy_del(self):
        repos_url = self.make_repository("a")

        cb = self.commit_editor(repos_url)
        cb.add_dir("trunk")
        cb.add_dir("trunk/data")
        cb.add_file("trunk/data/bla")
        cb.add_dir("trunk/db")
        cb.add_file("trunk/db/f1")
        cb.add_file("trunk/db/f2")
        cb.done()

        cb = self.commit_editor(repos_url)
        cb.add_dir("trunk/data/fg", "trunk/db")
        cb.done()

        cb = self.commit_editor(repos_url)
        cb.delete("trunk/data/fg/f2")
        cb.done()

        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))

        self.assertEqual(set(['trunk/data', 'trunk/data/bla', 
                          'trunk/data/fg', 'trunk/data/fg/f1', 'trunk/db',
                          'trunk/db/f1', 'trunk/db/f2']), 
                set(walker.find_children("trunk", 3)))

    def test_fetch_property_change_only_trunk(self):
        repos_url = self.make_repository('d')

        cb = self.commit_editor(repos_url)
        cb.add_dir("trunk")
        cb.add_file("trunk/bla")
        cb.done()

        cb = self.commit_editor(repos_url)
        cb.change_dir_prop("trunk", "some:property", "some data\n")
        cb.done()

        cb = self.commit_editor(repos_url)
        cb.change_dir_prop("trunk", "some2:property", "some data\n")
        cb.done()

        cb = self.commit_editor(repos_url)
        cb.change_dir_prop("trunk", "some:property", "some data4\n")
        cb.done()

        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))
        self.assertEquals({'trunk': ('M', None, -1)}, walker.get_revision_paths(3))

    def test_iter_changes_property_change(self):
        repos_url = self.make_repository('d')

        cb = self.commit_editor(repos_url)
        cb.add_dir("trunk")
        cb.add_file("trunk/bla")
        cb.done()

        cb = self.commit_editor(repos_url)
        cb.change_dir_prop("trunk", "some:property", "some data\n")
        cb.done()

        cb = self.commit_editor(repos_url)
        cb.change_dir_prop("trunk", "some2:property", "some data\n")
        cb.done()

        cb = self.commit_editor(repos_url)
        cb.change_dir_prop("trunk", "some:property", "some other data\n")
        cb.done()

        walker = self.get_log_walker(transport=SvnRaTransport(repos_url))
        self.assertEquals([({'trunk': (u'M', None, -1)}, 3), 
                           ({'trunk': (u'M', None, -1)}, 2), 
                           ({'trunk/bla': (u'A', None, -1), 'trunk': (u'A', None, -1)}, 1)], [l[:2] for l in walker.iter_changes(["trunk"], 3)])


class TestCachingLogWalker(TestLogWalker):
    def setUp(self):
        super(TestCachingLogWalker, self).setUp()

        logwalker.cache_dir = os.path.join(self.test_dir, "cache-dir")

    def get_log_walker(self, transport):
        return logwalker.CachingLogWalker(super(TestCachingLogWalker, self).get_log_walker(transport))


