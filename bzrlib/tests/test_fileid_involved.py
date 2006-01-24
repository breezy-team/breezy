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

from bzrlib.tests import TestCaseInTempDir
import os
from bzrlib.commit import commit
from bzrlib.add import smart_add
from bzrlib.branch import Branch
from bzrlib.clone import copy_branch
from bzrlib.builtins import merge
from bzrlib.workingtree import WorkingTree
from bzrlib.delta import compare_trees


class TestFileIdInvolved(TestCaseInTempDir):

    def touch(self,filename):
        f = file(filename,"a")
        f.write("appended line\n")
        f.close( )

    def merge( self, branch_from, force=False ):
        from bzrlib._merge_core import ApplyMerge3

        merge([branch_from,-1],[None,None], merge_type=ApplyMerge3,
            check_clean=(not force) )

    def setUp(self):
        super(TestFileIdInvolved, self).setUp()
        # create three branches, and merge it
        #
        #           /-->J ------>K                (branch2)
        #          /              \
        #  A ---> B --->C ---->D->G               (main)
        #  \           /      /
        #   \---> E---/----> F                 (branch1)

        os.mkdir("main")
        os.chdir("main")

        main_branch = Branch.initialize('.')
        self.build_tree(["a","b","c"])

        b = Branch.open('.')
        wt = b.working_tree()
        wt.add(['a', 'b', 'c'], ['a-file-id-2006-01-01-abcd',
                                 'b-file-id-2006-01-01-defg',
                                 'c-funky<file-id> quiji%bo'])
        commit(b, "Commit one", rev_id="rev-A")
        del b, wt
        #-------- end A -----------

        copy_branch(main_branch,"../branch1")
        os.chdir("../branch1")

        #branch1_branch = Branch.open(".")
        self.build_tree(["d"])
        smart_add(".")
        commit(Branch.open("."), "branch1, Commit one", rev_id="rev-E")

        #-------- end E -----------

        os.chdir("../main")
        self.touch("a")
        commit(Branch.open("."), "Commit two", rev_id="rev-B")

        #-------- end B -----------

        copy_branch(Branch.open("."),"../branch2")
        os.chdir("../branch2")

        branch2_branch = Branch.open(".")
        os.chmod("b",0770)
        commit(Branch.open("."), "branch2, Commit one", rev_id="rev-J")

        #-------- end J -----------

        os.chdir("../main")

        self.merge("../branch1")
        commit(Branch.open("."), "merge branch1, rev-11", rev_id="rev-C")

        #-------- end C -----------

        os.chdir("../branch1")
        tree = WorkingTree('.', Branch.open("."))
        tree.rename_one("d","e")
        commit(Branch.open("."), "branch1, commit two", rev_id="rev-F")


        #-------- end F -----------

        os.chdir("../branch2")

        self.touch("c")
        commit(Branch.open("."), "branch2, commit two", rev_id="rev-K")

        #-------- end K -----------

        os.chdir("../main")

        self.touch("b")
        self.merge("../branch1",force=True)

        # D gets some funky characters to make sure the unescaping works
        commit(Branch.open("."), "merge branch1, rev-12", rev_id="rev-<D>")

        # end D

        self.merge("../branch2")
        commit(Branch.open("."), "merge branch1, rev-22",  rev_id="rev-G")

        # end G
        os.chdir("../main")
        self.branch = Branch.open(".")


    def test_fileid_involved_all_revs(self):

        l = self.branch.fileid_involved( )
        self.assertEquals( sorted(map( lambda x: x[0], l )), ["a","b","c","d"])

    def test_fileid_involved_one_rev(self):

        l = self.branch.fileid_involved("rev-B" )
        self.assertEquals( sorted(map( lambda x: x[0], l )), ["a","b","c"])

    def test_fileid_involved_two_revs(self):

        l = self.branch.fileid_involved_between_revs("rev-B","rev-K" )
        self.assertEquals( sorted(map( lambda x: x[0], l )), ["b","c"])

        l = self.branch.fileid_involved_between_revs("rev-C","rev-<D>" )
        self.assertEquals( sorted(map( lambda x: x[0], l )), ["b","d"])

        l = self.branch.fileid_involved_between_revs("rev-C","rev-G" )
        self.assertEquals( sorted(map( lambda x: x[0], l )), ["b","c","d"])

        l = self.branch.fileid_involved_between_revs("rev-E","rev-G" )
        self.assertEquals( sorted(map( lambda x: x[0], l )), ["a", "b","c","d"])

    def test_fileid_involved_sets(self):

        l = self.branch.fileid_involved_by_set(set(["rev-B"]))
        self.assertEquals( sorted(map( lambda x: x[0], l )), ["a"])

        l = self.branch.fileid_involved_by_set(set(["rev-<D>"]))
        self.assertEquals( sorted(map( lambda x: x[0], l )), ["b"])

    def test_fileid_involved_compare(self):

        l1 = self.branch.fileid_involved_between_revs("rev-E", "rev-<D>")
        l2 = self.branch.fileid_involved_by_set(set(["rev-<D>","rev-F","rev-C","rev-B"]))
        self.assertEquals( l1, l2 )

        l1 = self.branch.fileid_involved_between_revs("rev-C", "rev-G")
        l2 = self.branch.fileid_involved_by_set(
            set(["rev-G","rev-<D>","rev-F","rev-K","rev-J"]))
        self.assertEquals( l1, l2 )

    def test_fileid_involved_full_compare(self):
        from bzrlib.tsort import topo_sort
        pp=[]
        history = self.branch.revision_history( )

        if len(history) < 2: return

        for start in range(0,len(history)-1):
            for end in range(start+1,len(history)):

                l1 = self.branch.fileid_involved_between_revs(
                    history[start], history[end])

                old_tree = self.branch.revision_tree(history[start])
                new_tree = self.branch.revision_tree(history[end])
                delta = compare_trees(old_tree, new_tree )

                l2 = [ id for path, id, kind in delta.added ] + \
                     [ id for oldpath, newpath, id, kind, text_modified, \
                            meta_modified in delta.renamed ] + \
                     [ id for path, id, kind, text_modified, meta_modified in \
                            delta.modified ]

                self.assertEquals( l1, set(l2) )


