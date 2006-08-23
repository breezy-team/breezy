# Copyright (C) 2005 by Canonical Ltd
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

import os
import sys

from bzrlib.add import smart_add
from bzrlib.builtins import merge
from bzrlib.errors import IllegalPath
from bzrlib.tests import TestSkipped
from bzrlib.tests.repository_implementations.test_repository import TestCaseWithRepository
from bzrlib.transform import TreeTransform
from bzrlib.workingtree import WorkingTree


class FileIdInvolvedBase(TestCaseWithRepository):

    def touch(self,filename):
        f = file(filename,"a")
        f.write("appended line\n")
        f.close( )

    def compare_tree_fileids(self, branch, old_rev, new_rev):
        old_tree = self.branch.repository.revision_tree(old_rev)
        new_tree = self.branch.repository.revision_tree(new_rev)
        delta = new_tree.changes_from(old_tree)

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

        # A changes: 
        # B changes: 'a-file-id-2006-01-01-abcd'
        # C changes:  Nothing (perfect merge)
        # D changes: 'b-file-id-2006-01-01-defg'
        # E changes: 'file-d'
        # F changes: 'file-d'
        # G changes: 'b-file-id-2006-01-01-defg'
        # J changes: 'b-file-id-2006-01-01-defg'
        # K changes: 'c-funky<file-id> quiji%bo'

        main_wt = self.make_branch_and_tree('main')
        main_branch = main_wt.branch
        self.build_tree(["main/a","main/b","main/c"])

        main_wt.add(['a', 'b', 'c'], ['a-file-id-2006-01-01-abcd',
                                 'b-file-id-2006-01-01-defg',
                                 'c-funky<file-id> quiji%bo'])
        try:
            main_wt.commit("Commit one", rev_id="rev-A")
        except IllegalPath:
            # TODO: jam 20060701 Consider raising a different exception
            #       newer formats do support this, and nothin can done to 
            #       correct this test - its not a bug.
            if sys.platform == 'win32':
                raise TestSkipped('Old repository formats do not'
                                  ' support file ids with <> on win32')
            # This is not a known error condition
            raise

        #-------- end A -----------

        d1 = main_branch.bzrdir.clone('branch1')
        b1 = d1.open_branch()
        self.build_tree(["branch1/d"])
        bt1 = d1.open_workingtree()
        bt1.add(['d'], ['file-d'])
        bt1.commit("branch1, Commit one", rev_id="rev-E")

        #-------- end E -----------

        self.touch("main/a")
        main_wt.commit("Commit two", rev_id="rev-B")

        #-------- end B -----------

        d2 = main_branch.bzrdir.clone('branch2')
        branch2_branch = d2.open_branch()
        bt2 = d2.open_workingtree()
        set_executability(bt2, 'b', True)
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

    def test_fileids_altered_between_two_revs(self):
        def foo(old, new):
            print set(self.branch.repository.get_ancestry(new)).difference(set(self.branch.repository.get_ancestry(old)))

        self.assertEqual(
            {'b-file-id-2006-01-01-defg':set(['rev-J']),
             'c-funky<file-id> quiji%bo':set(['rev-K'])
             },
            self.branch.repository.fileids_altered_by_revision_ids(["rev-J","rev-K"]))

        self.assertEqual(
            {'b-file-id-2006-01-01-defg': set(['rev-<D>']),
             'file-d': set(['rev-F']),
             },
            self.branch.repository.fileids_altered_by_revision_ids(['rev-<D>', 'rev-F']))

        self.assertEqual(
            {
             'b-file-id-2006-01-01-defg': set(['rev-<D>', 'rev-G', 'rev-J']), 
             'c-funky<file-id> quiji%bo': set(['rev-K']),
             'file-d': set(['rev-F']), 
             },
            self.branch.repository.fileids_altered_by_revision_ids(
                ['rev-<D>', 'rev-G', 'rev-F', 'rev-K', 'rev-J']))

        self.assertEqual(
            {'a-file-id-2006-01-01-abcd': set(['rev-B']),
             'b-file-id-2006-01-01-defg': set(['rev-<D>', 'rev-G', 'rev-J']),
             'c-funky<file-id> quiji%bo': set(['rev-K']),
             'file-d': set(['rev-F']),
             },
            self.branch.repository.fileids_altered_by_revision_ids(
                ['rev-G', 'rev-F', 'rev-C', 'rev-B', 'rev-<D>', 'rev-K', 'rev-J']))

    def fileids_altered_by_revision_ids(self, revision_ids):
        """This is a wrapper to strip TREE_ROOT if it occurs"""
        repo = self.branch.repository
        result = repo.fileids_altered_by_revision_ids(revision_ids)
        if 'TREE_ROOT' in result:
            del result['TREE_ROOT']
        return result

    def test_fileids_altered_by_revision_ids(self):
        self.assertEqual(
            {'a-file-id-2006-01-01-abcd':set(['rev-A']),
             'b-file-id-2006-01-01-defg': set(['rev-A']),
             'c-funky<file-id> quiji%bo': set(['rev-A']),
             }, 
            self.fileids_altered_by_revision_ids(["rev-A"]))
        self.assertEqual(
            {'a-file-id-2006-01-01-abcd':set(['rev-B'])
             }, 
            self.branch.repository.fileids_altered_by_revision_ids(["rev-B"]))
        self.assertEqual(
            {'b-file-id-2006-01-01-defg':set(['rev-<D>'])
             },
            self.branch.repository.fileids_altered_by_revision_ids(["rev-<D>"]))

    def test_fileids_involved_full_compare(self):
        # this tests that the result of each fileid_involved calculation 
        # along a revision history selects only the fileids selected by
        # comparing the trees - no less, and no more. This is correct 
        # because in our sample data we do not revert any file ids along
        # the revision history.
        pp=[]
        history = self.branch.revision_history( )

        if len(history) < 2: return

        for start in range(0,len(history)-1):
            start_id = history[start]
            for end in range(start+1,len(history)):
                end_id = history[end]
                old_revs = set(self.branch.repository.get_ancestry(start_id))
                new_revs = set(self.branch.repository.get_ancestry(end_id))
                l1 = self.branch.repository.fileids_altered_by_revision_ids(
                    new_revs.difference(old_revs))
                l1 = set(l1.keys())

                l2 = self.compare_tree_fileids(self.branch, start_id, end_id)
                self.assertEquals(l1, l2)


class TestFileIdInvolvedSuperset(FileIdInvolvedBase):

    def setUp(self):
        super(TestFileIdInvolvedSuperset, self).setUp()

        self.branch = None
        main_wt = self.make_branch_and_tree('main')
        main_branch = main_wt.branch
        self.build_tree(["main/a","main/b","main/c"])

        main_wt.add(['a', 'b', 'c'], ['a-file-id-2006-01-01-abcd',
                                 'b-file-id-2006-01-01-defg',
                                 'c-funky<file-id> quiji\'"%bo'])
        try:
            main_wt.commit("Commit one", rev_id="rev-A")
        except IllegalPath: 
            # TODO: jam 20060701 Consider raising a different exception
            #       newer formats do support this, and nothin can done to 
            #       correct this test - its not a bug.
            if sys.platform == 'win32':
                raise TestSkipped('Old repository formats do not'
                                  ' support file ids with <> on win32')
            # This is not a known error condition
            raise

        branch2_bzrdir = main_branch.bzrdir.sprout("branch2")
        branch2_branch = branch2_bzrdir.open_branch()
        branch2_wt = branch2_bzrdir.open_workingtree()
        set_executability(branch2_wt, 'b', True)
        branch2_wt.commit("branch2, Commit one", rev_id="rev-J")

        self.merge(branch2_branch, main_wt)
        set_executability(main_wt, 'b', False)
        main_wt.commit("merge branch1, rev-22",  rev_id="rev-G")

        # end G
        self.branch = main_branch

    def test_fileid_involved_full_compare2(self):
        # this tests that fileids_alteted_by_revision_ids returns 
        # more information than compare_tree can, because it 
        # sees each change rather than the aggregate delta.
        history = self.branch.revision_history()
        old_rev = history[0]
        new_rev = history[1]
        old_revs = set(self.branch.repository.get_ancestry(old_rev))
        new_revs = set(self.branch.repository.get_ancestry(new_rev))

        l1 = self.branch.repository.fileids_altered_by_revision_ids(
            new_revs.difference(old_revs))
        l1 = set(l1.keys())

        l2 = self.compare_tree_fileids(self.branch, old_rev, new_rev)
        self.assertNotEqual(l2, l1)
        self.assertSubset(l2, l1)


def set_executability(wt, path, executable=True):
    """Set the executable bit for the file at path in the working tree

    os.chmod() doesn't work on windows. But TreeTransform can mark or
    unmark a file as executable.
    """
    file_id = wt.path2id(path)
    tt = TreeTransform(wt)
    try:
        tt.set_executability(executable, tt.trans_id_tree_file_id(file_id))
        tt.apply()
    finally:
        tt.finalize()
