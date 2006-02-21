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

from bzrlib.add import smart_add
from bzrlib.builtins import merge
from bzrlib.delta import compare_trees
from bzrlib.merge import merge_inner
from bzrlib.revision import common_ancestor
from bzrlib.tests.repository_implementations.test_repository import TestCaseWithRepository
from bzrlib.workingtree import WorkingTree


class FileIdInvolvedBase(TestCaseWithRepository):

    def touch(self,filename):
        f = file(filename,"a")
        f.write("appended line\n")
        f.close( )

    def merge(self, branch_from, wt_to):
        # minimal ui-less merge.
        wt_to.branch.fetch(branch_from)
        base_rev = common_ancestor(branch_from.last_revision(),
                                    wt_to.branch.last_revision(),
                                    wt_to.branch.repository)
        merge_inner(wt_to.branch, branch_from.basis_tree(), 
                    wt_to.branch.repository.revision_tree(base_rev),
                    this_tree=wt_to)
        wt_to.add_pending_merge(branch_from.last_revision())

    def compare_tree_fileids(self, branch, old_rev, new_rev):
        old_tree = self.branch.repository.revision_tree(old_rev)
        new_tree = self.branch.repository.revision_tree(new_rev)
        delta = compare_trees(old_tree, new_tree)

        l2 = [id for path, id, kind in delta.added] + \
             [id for oldpath, newpath, id, kind, text_modified, \
                meta_modified in delta.renamed] + \
             [id for path, id, kind, text_modified, meta_modified in \
                delta.modified]
        return set(l2)

    
class TestFileIdInvolved(FileIdInvolvedBase):

    def setUp(self):
        super(TestFileIdInvolved, self).setUp()
        # create three branches, and merge it
        #
        #           /-->J ------>K                (branch2)
        #          /              \
        #  A ---> B --->C ---->D->G               (main)
        #  \           /      /
        #   \---> E---/----> F                 (branch1)

        main_wt = self.make_branch_and_tree('main')
        main_branch = main_wt.branch
        self.build_tree(["main/a","main/b","main/c"])

        main_wt.add(['a', 'b', 'c'], ['a-file-id-2006-01-01-abcd',
                                 'b-file-id-2006-01-01-defg',
                                 'c-funky<file-id> quiji%bo'])
        main_wt.commit("Commit one", rev_id="rev-A")
        #-------- end A -----------

        d1 = main_branch.bzrdir.clone('branch1')
        b1 = d1.open_branch()
        self.build_tree(["branch1/d"])
        bt1 = d1.open_workingtree()
        bt1.add('d')
        bt1.commit("branch1, Commit one", rev_id="rev-E")

        #-------- end E -----------

        self.touch("main/a")
        main_wt.commit("Commit two", rev_id="rev-B")

        #-------- end B -----------

        d2 = main_branch.bzrdir.clone('branch2')
        branch2_branch = d2.open_branch()
        bt2 = d2.open_workingtree()
        os.chmod("branch2/b",0770)
        bt2.commit("branch2, Commit one", rev_id="rev-J")

        #-------- end J -----------

        self.merge(b1, main_wt)
        main_wt.commit("merge branch1, rev-11", rev_id="rev-C")

        #-------- end C -----------

        bt1.rename_one("d","e")
        bt1.commit("branch1, commit two", rev_id="rev-F")

        #-------- end F -----------

        self.touch("branch2/c")
        bt2.commit("branch2, commit two", rev_id="rev-K")

        #-------- end K -----------

        self.touch("main/b")
        self.merge(b1, main_wt)
        # D gets some funky characters to make sure the unescaping works
        main_wt.commit("merge branch1, rev-12", rev_id="rev-<D>")

        # end D

        self.merge(branch2_branch, main_wt)
        main_wt.commit("merge branch1, rev-22",  rev_id="rev-G")

        # end G
        self.branch = main_branch


    def test_fileid_involved_all_revs(self):

        l = self.branch.repository.fileid_involved( )
        self.assertEquals( sorted(map( lambda x: x[0], l )), ["a","b","c","d"])

    def test_fileid_involved_one_rev(self):

        l = self.branch.repository.fileid_involved("rev-B" )
        self.assertEquals( sorted(map( lambda x: x[0], l )), ["a","b","c"])

    def test_fileid_involved_two_revs(self):

        l = self.branch.repository.fileid_involved_between_revs("rev-B","rev-K" )
        self.assertEquals( sorted(map( lambda x: x[0], l )), ["b","c"])

        l = self.branch.repository.fileid_involved_between_revs("rev-C","rev-<D>" )
        self.assertEquals( sorted(map( lambda x: x[0], l )), ["b","d"])

        l = self.branch.repository.fileid_involved_between_revs("rev-C","rev-G" )
        self.assertEquals( sorted(map( lambda x: x[0], l )), ["b","c","d"])

        l = self.branch.repository.fileid_involved_between_revs("rev-E","rev-G" )
        self.assertEquals( sorted(map( lambda x: x[0], l )), ["a", "b","c","d"])

    def test_fileid_involved_sets(self):

        l = self.branch.repository.fileid_involved_by_set(set(["rev-B"]))
        self.assertEquals( sorted(map( lambda x: x[0], l )), ["a"])

        l = self.branch.repository.fileid_involved_by_set(set(["rev-<D>"]))
        self.assertEquals( sorted(map( lambda x: x[0], l )), ["b"])

    def test_fileid_involved_compare(self):

        l1 = self.branch.repository.fileid_involved_between_revs("rev-E", "rev-<D>")
        l2 = self.branch.repository.fileid_involved_by_set(set(["rev-<D>","rev-F","rev-C","rev-B"]))
        self.assertEquals( l1, l2 )

        l1 = self.branch.repository.fileid_involved_between_revs("rev-C", "rev-G")
        l2 = self.branch.repository.fileid_involved_by_set(
            set(["rev-G","rev-<D>","rev-F","rev-K","rev-J"]))
        self.assertEquals( l1, l2 )

    def test_fileid_involved_full_compare(self):
        from bzrlib.tsort import topo_sort
        pp=[]
        history = self.branch.revision_history( )

        if len(history) < 2: return

        for start in range(0,len(history)-1):
            start_id = history[start]
            for end in range(start+1,len(history)):
                end_id = history[end]
                l1 = self.branch.repository.fileid_involved_between_revs(
                    start_id, end_id)
                l2 = self.compare_tree_fileids(self.branch, start_id, end_id)
                self.assertEquals(l1, l2)


class TestFileIdInvolvedSuperset(FileIdInvolvedBase):

    def setUp(self):
        super(TestFileIdInvolvedSuperset, self).setUp()

        main_wt = self.make_branch_and_tree('main')
        main_branch = main_wt.branch
        self.build_tree(["main/a","main/b","main/c"])

        main_wt.add(['a', 'b', 'c'], ['a-file-id-2006-01-01-abcd',
                                 'b-file-id-2006-01-01-defg',
                                 'c-funky<file-id> quiji%bo'])
        main_wt.commit("Commit one", rev_id="rev-A")

        branch2_bzrdir = main_branch.bzrdir.sprout("branch2")
        branch2_branch = branch2_bzrdir.open_branch()
        branch2_wt = branch2_bzrdir.open_workingtree()
        os.chmod("branch2/b",0770)
        branch2_wt.commit("branch2, Commit one", rev_id="rev-J")

        self.merge(branch2_branch, main_wt)
        os.chmod("main/b",0660)
        main_wt.commit("merge branch1, rev-22",  rev_id="rev-G")

        # end G
        self.branch = main_branch

    def test_fileid_involved_full_compare2(self):
        history = self.branch.revision_history()
        old_rev = history[0]
        new_rev = history[1]

        l1 = self.branch.repository.fileid_involved_between_revs(old_rev, new_rev)

        l2 = self.compare_tree_fileids(self.branch, old_rev, new_rev)
        self.assertNotEqual(l2, l1)
        self.AssertSubset(l2, l1)
