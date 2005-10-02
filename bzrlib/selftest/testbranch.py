# (C) 2005 Canonical Ltd

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
from bzrlib.branch import Branch
from bzrlib.clone import copy_branch
from bzrlib.commit import commit
from bzrlib.errors import NoSuchRevision, UnlistableBranch
from bzrlib.selftest import TestCaseInTempDir
from bzrlib.trace import mutter


class TestBranch(TestCaseInTempDir):

    def test_append_revisions(self):
        """Test appending more than one revision"""
        br = Branch.initialize(".")
        br.append_revision("rev1")
        self.assertEquals(br.revision_history(), ["rev1",])
        br.append_revision("rev2", "rev3")
        self.assertEquals(br.revision_history(), ["rev1", "rev2", "rev3"])


class TestFetch(TestCaseInTempDir):

    def test_fetch_revisions(self):
        """Test fetch-revision operation."""
        from bzrlib.fetch import Fetcher
        os.mkdir('b1')
        os.mkdir('b2')
        b1 = Branch.initialize('b1')
        b2 = Branch.initialize('b2')
        file(os.sep.join(['b1', 'foo']), 'w').write('hello')
        b1.add(['foo'], ['foo-id'])
        b1.commit('lala!', rev_id='revision-1', allow_pointless=False)

        mutter('start fetch')
        f = Fetcher(from_branch=b1, to_branch=b2)
        eq = self.assertEquals
        eq(f.count_copied, 1)
        eq(f.last_revision, 'revision-1')

        rev = b2.get_revision('revision-1')
        tree = b2.revision_tree('revision-1')
        eq(tree.get_file_text('foo-id'), 'hello')

    def test_push_stores(self):
        """Copy the stores from one branch to another"""
        os.mkdir('a')
        br_a = Branch.initialize("a")
        file('a/b', 'wb').write('b')
        br_a.add('b')
        commit(br_a, "silly commit")

        os.mkdir('b')
        br_b = Branch.initialize("b")
        self.assertRaises(NoSuchRevision, br_b.get_revision, 
                          br_a.revision_history()[0])
        br_a.push_stores(br_b)
        rev = br_b.get_revision(br_a.revision_history()[0])
        tree = br_b.revision_tree(br_a.revision_history()[0])
        for file_id in tree:
            if tree.inventory[file_id].kind == "file":
                tree.get_file(file_id).read()
        return br_a, br_b

    def test_copy_branch(self):
        """Copy the stores from one branch to another"""
        br_a, br_b = self.test_push_stores()
        commit(br_b, "silly commit")
        os.mkdir('c')
        br_c = copy_branch(br_a, 'c', basis_branch=br_b)
        self.assertEqual(br_a.revision_history(), br_c.revision_history())
        ## # basis branches currently disabled for weave format
        ## self.assertFalse(br_b.last_revision() in br_c.revision_history())
        ## br_c.get_revision(br_b.last_revision())

    def test_copy_partial(self):
        """Copy only part of the history of a branch."""
        self.build_tree(['a/', 'a/one'])
        br_a = Branch.initialize('a')
        br_a.add(['one'])
        br_a.commit('commit one', rev_id='u@d-1')
        self.build_tree(['a/two'])
        br_a.add(['two'])
        br_a.commit('commit two', rev_id='u@d-2')
        br_b = copy_branch(br_a, 'b', revision='u@d-1')
        self.assertEqual(br_b.last_revision(), 'u@d-1')
        self.assertTrue(os.path.exists('b/one'))
        self.assertFalse(os.path.exists('b/two'))
        

    def test_record_initial_ghost_merge(self):
        """A pending merge with no revision present is still a merge."""
        branch = Branch.initialize('.')
        branch.add_pending_merge('non:existent@rev--ision--0--2')
        branch.commit('pretend to merge nonexistent-revision', rev_id='first')
        rev = branch.get_revision(branch.last_revision())
        self.assertEqual(len(rev.parent_ids), 1)
        # parent_sha1s is not populated now, WTF. rbc 20051003
        self.assertEqual(len(rev.parent_sha1s), 0)
        self.assertEqual(rev.parent_ids[0], 'non:existent@rev--ision--0--2')

# TODO:
# compare the gpg-to-sign info for a commit with a ghost and 
#     an identical tree without a ghost
# fetch missing should rewrite the TOC of weaves to list newly available parents.
        
# TODO: rewrite this as a regular unittest, without relying on the displayed output        
#         >>> from bzrlib.commit import commit
#         >>> bzrlib.trace.silent = True
#         >>> br1 = ScratchBranch(files=['foo', 'bar'])
#         >>> br1.add('foo')
#         >>> br1.add('bar')
#         >>> commit(br1, "lala!", rev_id="REVISION-ID-1", verbose=False)
#         >>> br2 = ScratchBranch()
#         >>> br2.update_revisions(br1)
#         Added 2 texts.
#         Added 1 inventories.
#         Added 1 revisions.
#         >>> br2.revision_history()
#         [u'REVISION-ID-1']
#         >>> br2.update_revisions(br1)
#         Added 0 revisions.
#         >>> br1.text_store.total_size() == br2.text_store.total_size()
#         True
