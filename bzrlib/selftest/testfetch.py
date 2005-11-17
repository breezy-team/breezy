# Copyright (C) 2005 by Canonical Ltd

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

import os
import sys

import bzrlib.errors
from bzrlib.selftest.testrevision import make_branches
from bzrlib.trace import mutter
from bzrlib.branch import Branch
from bzrlib.fetch import greedy_fetch
from bzrlib.merge import merge
from bzrlib.clone import copy_branch

from bzrlib.selftest import TestCaseInTempDir
from bzrlib.selftest.HTTPTestUtil import TestCaseWithWebserver


def has_revision(branch, revision_id):
    try:
        branch.get_revision_xml_file(revision_id)
        return True
    except bzrlib.errors.NoSuchRevision:
        return False

def fetch_steps(self, br_a, br_b, writable_a):
    """A foreign test method for testing fetch locally and remotely."""
    def new_branch(name):
        os.mkdir(name)
        return Branch.initialize(name)
            
    self.assertFalse(has_revision(br_b, br_a.revision_history()[3]))
    self.assert_(has_revision(br_b, br_a.revision_history()[2]))
    self.assertEquals(len(br_b.revision_history()), 7)
    self.assertEquals(greedy_fetch(br_b, br_a, br_a.revision_history()[2])[0], 0)

    # greedy_fetch is not supposed to alter the revision history
    self.assertEquals(len(br_b.revision_history()), 7)
    self.assertFalse(has_revision(br_b, br_a.revision_history()[3]))

    self.assertEquals(len(br_b.revision_history()), 7)
    self.assertEquals(greedy_fetch(br_b, br_a, br_a.revision_history()[3])[0], 1)
    self.assert_(has_revision(br_b, br_a.revision_history()[3]))
    self.assertFalse(has_revision(br_a, br_b.revision_history()[6]))
    self.assert_(has_revision(br_a, br_b.revision_history()[5]))

    # When a non-branch ancestor is missing, it should be unlisted...
    # as its not reference from the inventory weave.
    br_b4 = new_branch('br_4')
    count, failures = greedy_fetch(br_b4, br_b)
    self.assertEqual(count, 7)
    self.assertEqual(failures, [])

    self.assertEqual(greedy_fetch(writable_a, br_b)[0], 1)
    self.assert_(has_revision(br_a, br_b.revision_history()[3]))
    self.assert_(has_revision(br_a, br_b.revision_history()[4]))
        
    br_b2 = new_branch('br_b2')
    self.assertEquals(greedy_fetch(br_b2, br_b)[0], 7)
    self.assert_(has_revision(br_b2, br_b.revision_history()[4]))
    self.assert_(has_revision(br_b2, br_a.revision_history()[2]))
    self.assertFalse(has_revision(br_b2, br_a.revision_history()[3]))

    br_a2 = new_branch('br_a2')
    self.assertEquals(greedy_fetch(br_a2, br_a)[0], 9)
    self.assert_(has_revision(br_a2, br_b.revision_history()[4]))
    self.assert_(has_revision(br_a2, br_a.revision_history()[3]))
    self.assert_(has_revision(br_a2, br_a.revision_history()[2]))

    br_a3 = new_branch('br_a3')
    self.assertEquals(greedy_fetch(br_a3, br_a2)[0], 0)
    for revno in range(4):
        self.assertFalse(has_revision(br_a3, br_a.revision_history()[revno]))
    self.assertEqual(greedy_fetch(br_a3, br_a2, br_a.revision_history()[2])[0], 3)
    fetched = greedy_fetch(br_a3, br_a2, br_a.revision_history()[3])[0]
    self.assertEquals(fetched, 3, "fetched %d instead of 3" % fetched)
    # InstallFailed should be raised if the branch is missing the revision
    # that was requested.
    self.assertRaises(bzrlib.errors.InstallFailed, greedy_fetch, br_a3,
                      br_a2, 'pizza')
    # InstallFailed should be raised if the branch is missing a revision
    # from its own revision history
    br_a2.append_revision('a-b-c')
    self.assertRaises(bzrlib.errors.InstallFailed, greedy_fetch, br_a3,
                      br_a2)


    #TODO: test that fetch correctly does reweaving when needed. RBC 20051008

class TestFetch(TestCaseInTempDir):

    def test_fetch(self):
        #highest indices a: 5, b: 7
        br_a, br_b = make_branches(self)
        fetch_steps(self, br_a, br_b, br_a)


class TestMergeFetch(TestCaseInTempDir):

    def test_merge_fetches_unrelated(self):
        """Merge brings across history from unrelated source"""
        os.mkdir('br1')
        br1 = Branch.initialize('br1')
        br1.working_tree().commit(message='rev 1-1', rev_id='1-1')
        br1.working_tree().commit(message='rev 1-2', rev_id='1-2')
        os.mkdir('br2')
        br2 = Branch.initialize('br2')
        br2.working_tree().commit(message='rev 2-1', rev_id='2-1')
        merge(other_revision=['br1', -1], base_revision=['br1', 0],
              this_dir='br2')
        self._check_revs_present(br2)

    def test_merge_fetches(self):
        """Merge brings across history from source"""
        os.mkdir('br1')
        br1 = Branch.initialize('br1')
        br1.working_tree().commit(message='rev 1-1', rev_id='1-1')
        copy_branch(br1, 'br2')
        br2 = Branch.open('br2')
        br1.working_tree().commit(message='rev 1-2', rev_id='1-2')
        br2.working_tree().commit(message='rev 2-1', rev_id='2-1')
        merge(other_revision=['br1', -1], base_revision=[None, None], 
              this_dir='br2')
        self._check_revs_present(br2)

    def _check_revs_present(self, br2):
        for rev_id in '1-1', '1-2', '2-1':
            self.assertTrue(br2.has_revision(rev_id))
            rev = br2.get_revision(rev_id)
            self.assertEqual(rev.revision_id, rev_id)
            self.assertTrue(br2.get_inventory(rev_id))



class TestMergeFileHistory(TestCaseInTempDir):
    def setUp(self):
        TestCaseInTempDir.setUp(self)
        os.mkdir('br1')
        br1 = Branch.initialize('br1')
        self.build_tree_contents([('br1/file', 'original contents\n')])
        br1.working_tree().add(['file'], ['this-file-id'])
        br1.working_tree().commit(message='rev 1-1', rev_id='1-1')
        copy_branch(br1, 'br2')
        br2 = Branch.open('br2')
        self.build_tree_contents([('br1/file', 'original from 1\n')])
        br1.working_tree().commit(message='rev 1-2', rev_id='1-2')
        self.build_tree_contents([('br1/file', 'agreement\n')])
        br1.working_tree().commit(message='rev 1-3', rev_id='1-3')
        self.build_tree_contents([('br2/file', 'contents in 2\n')])
        br2.working_tree().commit(message='rev 2-1', rev_id='2-1')
        self.build_tree_contents([('br2/file', 'agreement\n')])
        br2.working_tree().commit(message='rev 2-2', rev_id='2-2')

    def test_merge_fetches_file_history(self):
        """Merge brings across file histories"""
        br2 = Branch.open('br2')
        merge(other_revision=['br1', -1], base_revision=[None, None], 
              this_dir='br2')
        for rev_id, text in [('1-2', 'original from 1\n'),
                             ('1-3', 'agreement\n'),
                             ('2-1', 'contents in 2\n'),
                             ('2-2', 'agreement\n')]:
            self.assertEqualDiff(br2.revision_tree(rev_id).get_file_text('this-file-id'),
                                 text)




class TestHttpFetch(TestCaseWithWebserver):

    def setUp(self):
        super(TestHttpFetch, self).setUp()
        self.weblogs = []

    def test_fetch(self):
        #highest indices a: 5, b: 7
        br_a, br_b = make_branches(self)
        br_rem_a = Branch.open(self.get_remote_url(br_a._transport.base))
        fetch_steps(self, br_rem_a, br_b, br_a)

    def log(self, *args):
        """Capture web server log messages for introspection."""
        super(TestHttpFetch, self).log(*args)
        if args[0].startswith("webserver"):
            self.weblogs.append(args[0])

    def test_weaves_are_retrieved_once(self):
        self.build_tree(("source/", "source/file", "target/"))
        branch = Branch.initialize("source")
        branch.working_tree().add(["file"], ["id"])
        branch.working_tree().commit("added file")
        print >>open("source/file", 'w'), "blah"
        branch.working_tree().commit("changed file")
        target = Branch.initialize("target/")
        source = Branch.open(self.get_remote_url("source/"))
        self.assertEqual(greedy_fetch(target, source), (2, []))
        # this is the path to the literal file. As format changes 
        # occur it needs to be updated. FIXME: ask the store for the
        # path.
        weave_suffix = 'weaves/ce/id.weave HTTP/1.1" 200 -'
        self.assertEqual(1,
            len([log for log in self.weblogs if log.endswith(weave_suffix)]))
        inventory_weave_suffix = 'inventory.weave HTTP/1.1" 200 -'
        self.assertEqual(1,
            len([log for log in self.weblogs if log.endswith(
                inventory_weave_suffix)]))
        # this r-h check test will prevent regressions, but it currently already 
        # passes, before the patch to cache-rh is applied :[
        revision_history_suffix = 'revision-history HTTP/1.1" 200 -'
        self.assertEqual(1,
            len([log for log in self.weblogs if log.endswith(
                revision_history_suffix)]))
        self.weblogs = []
        # check there is nothing more to fetch
        source = Branch.open(self.get_remote_url("source/"))
        self.assertEqual(greedy_fetch(target, source), (0, []))
        self.failUnless(self.weblogs[0].endswith('branch-format HTTP/1.1" 200 -'))
        self.failUnless(self.weblogs[1].endswith('revision-history HTTP/1.1" 200 -'))
        self.assertEqual(2, len(self.weblogs))
