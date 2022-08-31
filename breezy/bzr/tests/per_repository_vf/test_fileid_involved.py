# Copyright (C) 2011, 2016 Canonical Ltd
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

import sys
import time

from breezy import (
    errors,
    revision as _mod_revision,
    tests,
    transform,
    )
from breezy.bzr import (
    inventory,
    remote,
    )
from breezy.tests.scenarios import load_tests_apply_scenarios
from breezy.bzr.tests.per_repository_vf import (
    TestCaseWithRepository,
    all_repository_vf_format_scenarios,
    )


load_tests = load_tests_apply_scenarios


class FileIdInvolvedWGhosts(TestCaseWithRepository):

    scenarios = all_repository_vf_format_scenarios()

    def create_branch_with_ghost_text(self):
        builder = self.make_branch_builder('ghost')
        builder.build_snapshot(None, [
            ('add', ('', b'root-id', 'directory', None)),
            ('add', ('a', b'a-file-id', 'file', b'some content\n'))],
            revision_id=b'A-id')
        b = builder.get_branch()
        old_rt = b.repository.revision_tree(b'A-id')
        new_inv = inventory.mutable_inventory_from_tree(old_rt)
        new_inv.revision_id = b'B-id'
        new_inv.get_entry(b'a-file-id').revision = b'ghost-id'
        new_rev = _mod_revision.Revision(b'B-id',
                                         timestamp=time.time(),
                                         timezone=0,
                                         message='Committing against a ghost',
                                         committer='Joe Foo <joe@foo.com>',
                                         properties={},
                                         parent_ids=(b'A-id', b'ghost-id'),
                                         )
        b.lock_write()
        self.addCleanup(b.unlock)
        b.repository.start_write_group()
        b.repository.add_revision(b'B-id', new_rev, new_inv)
        self.disable_commit_write_group_paranoia(b.repository)
        b.repository.commit_write_group()
        return b

    def disable_commit_write_group_paranoia(self, repo):
        if isinstance(repo, remote.RemoteRepository):
            # We can't easily disable the checks in a remote repo.
            repo.abort_write_group()
            raise tests.TestSkipped(
                "repository format does not support storing revisions with "
                "missing texts.")
        pack_coll = getattr(repo, '_pack_collection', None)
        if pack_coll is not None:
            # Monkey-patch the pack collection instance to allow storing
            # incomplete revisions.
            pack_coll._check_new_inventories = lambda: []

    def test_file_ids_include_ghosts(self):
        b = self.create_branch_with_ghost_text()
        repo = b.repository
        self.assertEqual(
            {b'a-file-id': {b'ghost-id'}},
            repo.fileids_altered_by_revision_ids([b'B-id']))

    def test_file_ids_uses_fallbacks(self):
        builder = self.make_branch_builder('source',
                                           format=self.bzrdir_format)
        repo = builder.get_branch().repository
        if not repo._format.supports_external_lookups:
            raise tests.TestNotApplicable('format does not support stacking')
        builder.start_series()
        builder.build_snapshot(None, [
            ('add', ('', b'root-id', 'directory', None)),
            ('add', ('file', b'file-id', 'file', b'contents\n'))],
            revision_id=b'A-id')
        builder.build_snapshot([b'A-id'], [
            ('modify', ('file', b'new-content\n'))],
            revision_id=b'B-id')
        builder.build_snapshot([b'B-id'], [
            ('modify', ('file', b'yet more content\n'))],
            revision_id=b'C-id')
        builder.finish_series()
        source_b = builder.get_branch()
        source_b.lock_read()
        self.addCleanup(source_b.unlock)
        base = self.make_branch('base')
        base.pull(source_b, stop_revision=b'B-id')
        stacked = self.make_branch('stacked')
        stacked.set_stacked_on_url('../base')
        stacked.pull(source_b, stop_revision=b'C-id')

        stacked.lock_read()
        self.addCleanup(stacked.unlock)
        repo = stacked.repository
        keys = {b'file-id': {b'A-id'}}
        if stacked.repository.supports_rich_root():
            keys[b'root-id'] = {b'A-id'}
        self.assertEqual(keys, repo.fileids_altered_by_revision_ids([b'A-id']))


class FileIdInvolvedBase(TestCaseWithRepository):

    def touch(self, tree, filename):
        # use the trees transport to not depend on the tree's location or type.
        tree.controldir.root_transport.append_bytes(
            filename, b"appended line\n")

    def compare_tree_fileids(self, branch, old_rev, new_rev):
        old_tree = self.branch.repository.revision_tree(old_rev)
        new_tree = self.branch.repository.revision_tree(new_rev)
        delta = new_tree.changes_from(old_tree)

        l2 = [change.file_id for change in delta.added] + \
             [change.file_id for change in delta.renamed] + \
             [change.file_id for change in delta.modified] + \
             [change.file_id for change in delta.copied]
        return set(l2)


class TestFileIdInvolved(FileIdInvolvedBase):

    scenarios = all_repository_vf_format_scenarios()

    def setUp(self):
        super(TestFileIdInvolved, self).setUp()
        # create three branches, and merge it
        #
        #          ,-->J------>K                (branch2)
        #         /             \
        #  A --->B --->C---->D-->G              (main)
        #  \          /     /
        #   '--->E---+---->F                    (branch1)

        # A changes:
        # B changes: 'a-file-id-2006-01-01-abcd'
        # C changes:  Nothing (perfect merge)
        # D changes: 'b-file-id-2006-01-01-defg'
        # E changes: 'file-d'
        # F changes: 'file-d'
        # G changes: 'b-file-id-2006-01-01-defg'
        # J changes: 'b-file-id-2006-01-01-defg'
        # K changes: 'c-funky<file-id>quiji%bo'

        main_wt = self.make_branch_and_tree('main')
        main_branch = main_wt.branch
        self.build_tree(["main/a", "main/b", "main/c"])

        main_wt.add(
            ['a', 'b', 'c'],
            ids=[b'a-file-id-2006-01-01-abcd',
                 b'b-file-id-2006-01-01-defg',
                 b'c-funky<file-id>quiji%bo'])
        try:
            main_wt.commit("Commit one", rev_id=b"rev-A")
        except errors.IllegalPath:
            # TODO: jam 20060701 Consider raising a different exception
            #       newer formats do support this, and nothin can done to
            #       correct this test - its not a bug.
            if sys.platform == 'win32':
                raise tests.TestSkipped('Old repository formats do not'
                                        ' support file ids with <> on win32')
            # This is not a known error condition
            raise

        # -------- end A -----------

        bt1 = self.make_branch_and_tree('branch1')
        bt1.pull(main_branch)
        b1 = bt1.branch
        self.build_tree(["branch1/d"])
        bt1.add(['d'], ids=[b'file-d'])
        bt1.commit("branch1, Commit one", rev_id=b"rev-E")

        # -------- end E -----------

        self.touch(main_wt, "a")
        main_wt.commit("Commit two", rev_id=b"rev-B")

        # -------- end B -----------

        bt2 = self.make_branch_and_tree('branch2')
        bt2.pull(main_branch)
        branch2_branch = bt2.branch
        set_executability(bt2, 'b', True)
        bt2.commit("branch2, Commit one", rev_id=b"rev-J")

        # -------- end J -----------

        main_wt.merge_from_branch(b1)
        main_wt.commit("merge branch1, rev-11", rev_id=b"rev-C")

        # -------- end C -----------

        bt1.rename_one("d", "e")
        bt1.commit("branch1, commit two", rev_id=b"rev-F")

        # -------- end F -----------

        self.touch(bt2, "c")
        bt2.commit("branch2, commit two", rev_id=b"rev-K")

        # -------- end K -----------

        main_wt.merge_from_branch(b1)
        self.touch(main_wt, "b")
        # D gets some funky characters to make sure the unescaping works
        main_wt.commit("merge branch1, rev-12", rev_id=b"rev-<D>")

        # end D

        main_wt.merge_from_branch(branch2_branch)
        main_wt.commit("merge branch1, rev-22", rev_id=b"rev-G")

        # end G
        self.branch = main_branch

    def test_fileids_altered_between_two_revs(self):
        self.branch.lock_read()
        self.addCleanup(self.branch.unlock)
        self.branch.repository.fileids_altered_by_revision_ids(
            [b"rev-J", b"rev-K"])
        self.assertEqual(
            {b'b-file-id-2006-01-01-defg': {b'rev-J'},
             b'c-funky<file-id>quiji%bo': {b'rev-K'}
             },
            self.branch.repository.fileids_altered_by_revision_ids([b"rev-J", b"rev-K"]))

        self.assertEqual(
            {b'b-file-id-2006-01-01-defg': {b'rev-<D>'},
             b'file-d': {b'rev-F'},
             },
            self.branch.repository.fileids_altered_by_revision_ids([b'rev-<D>', b'rev-F']))

        self.assertEqual(
            {
                b'b-file-id-2006-01-01-defg': {b'rev-<D>', b'rev-G', b'rev-J'},
                b'c-funky<file-id>quiji%bo': {b'rev-K'},
                b'file-d': {b'rev-F'},
                },
            self.branch.repository.fileids_altered_by_revision_ids(
                [b'rev-<D>', b'rev-G', b'rev-F', b'rev-K', b'rev-J']))

        self.assertEqual(
            {b'a-file-id-2006-01-01-abcd': {b'rev-B'},
             b'b-file-id-2006-01-01-defg': {b'rev-<D>', b'rev-G', b'rev-J'},
             b'c-funky<file-id>quiji%bo': {b'rev-K'},
             b'file-d': {b'rev-F'},
             },
            self.branch.repository.fileids_altered_by_revision_ids(
                [b'rev-G', b'rev-F', b'rev-C', b'rev-B', b'rev-<D>', b'rev-K', b'rev-J']))

    def fileids_altered_by_revision_ids(self, revision_ids):
        """This is a wrapper to strip TREE_ROOT if it occurs"""
        repo = self.branch.repository
        root_id = self.branch.basis_tree().path2id('')
        result = repo.fileids_altered_by_revision_ids(revision_ids)
        if root_id in result:
            del result[root_id]
        return result

    def test_fileids_altered_by_revision_ids(self):
        self.branch.lock_read()
        self.addCleanup(self.branch.unlock)
        self.assertEqual(
            {b'a-file-id-2006-01-01-abcd': {b'rev-A'},
             b'b-file-id-2006-01-01-defg': {b'rev-A'},
             b'c-funky<file-id>quiji%bo': {b'rev-A'},
             },
            self.fileids_altered_by_revision_ids([b"rev-A"]))
        self.assertEqual(
            {b'a-file-id-2006-01-01-abcd': {b'rev-B'}
             },
            self.branch.repository.fileids_altered_by_revision_ids([b"rev-B"]))
        self.assertEqual(
            {b'b-file-id-2006-01-01-defg': {b'rev-<D>'}
             },
            self.branch.repository.fileids_altered_by_revision_ids([b"rev-<D>"]))

    def test_fileids_involved_full_compare(self):
        # this tests that the result of each fileid_involved calculation
        # along a revision history selects only the fileids selected by
        # comparing the trees - no less, and no more. This is correct
        # because in our sample data we do not revert any file ids along
        # the revision history.
        self.branch.lock_read()
        self.addCleanup(self.branch.unlock)
        pp = []
        graph = self.branch.repository.get_graph()
        history = list(graph.iter_lefthand_ancestry(self.branch.last_revision(),
                                                    [_mod_revision.NULL_REVISION]))
        history.reverse()

        if len(history) < 2:
            return

        for start in range(0, len(history) - 1):
            start_id = history[start]
            for end in range(start + 1, len(history)):
                end_id = history[end]
                unique_revs = graph.find_unique_ancestors(end_id, [start_id])
                l1 = self.branch.repository.fileids_altered_by_revision_ids(
                    unique_revs)
                l1 = set(l1.keys())
                l2 = self.compare_tree_fileids(self.branch, start_id, end_id)
                self.assertEqual(l1, l2)


class TestFileIdInvolvedNonAscii(FileIdInvolvedBase):

    scenarios = all_repository_vf_format_scenarios()

    def test_utf8_file_ids_and_revision_ids(self):
        main_wt = self.make_branch_and_tree('main')
        main_branch = main_wt.branch
        self.build_tree(["main/a"])

        file_id = u'a-f\xedle-id'.encode('utf8')
        main_wt.add(['a'], ids=[file_id])
        revision_id = u'r\xe9v-a'.encode('utf8')
        try:
            main_wt.commit('a', rev_id=revision_id)
        except errors.NonAsciiRevisionId:
            raise tests.TestSkipped('non-ascii revision ids not supported by %s'
                                    % self.repository_format)

        repo = main_wt.branch.repository
        repo.lock_read()
        self.addCleanup(repo.unlock)
        file_ids = repo.fileids_altered_by_revision_ids([revision_id])
        root_id = main_wt.basis_tree().path2id('')
        if root_id in file_ids:
            self.assertEqual({file_id: {revision_id},
                              root_id: {revision_id}
                              }, file_ids)
        else:
            self.assertEqual({file_id: {revision_id}}, file_ids)


class TestFileIdInvolvedSuperset(FileIdInvolvedBase):

    scenarios = all_repository_vf_format_scenarios()

    def setUp(self):
        super(TestFileIdInvolvedSuperset, self).setUp()

        self.branch = None
        main_wt = self.make_branch_and_tree('main')
        main_branch = main_wt.branch
        self.build_tree(["main/a", "main/b", "main/c"])

        main_wt.add(
            ['a', 'b', 'c'],
            ids=[b'a-file-id-2006-01-01-abcd',
                 b'b-file-id-2006-01-01-defg',
                 b'c-funky<file-id>quiji\'"%bo'])
        try:
            main_wt.commit("Commit one", rev_id=b"rev-A")
        except errors.IllegalPath:
            # TODO: jam 20060701 Consider raising a different exception
            #       newer formats do support this, and nothin can done to
            #       correct this test - its not a bug.
            if sys.platform == 'win32':
                raise tests.TestSkipped('Old repository formats do not'
                                        ' support file ids with <> on win32')
            # This is not a known error condition
            raise

        branch2_wt = self.make_branch_and_tree('branch2')
        branch2_wt.pull(main_branch)
        branch2_bzrdir = branch2_wt.controldir
        branch2_branch = branch2_bzrdir.open_branch()
        set_executability(branch2_wt, 'b', True)
        branch2_wt.commit("branch2, Commit one", rev_id=b"rev-J")

        main_wt.merge_from_branch(branch2_branch)
        set_executability(main_wt, 'b', False)
        main_wt.commit("merge branch1, rev-22", rev_id=b"rev-G")

        # end G
        self.branch = main_branch

    def test_fileid_involved_full_compare2(self):
        # this tests that fileids_altered_by_revision_ids returns
        # more information than compare_tree can, because it
        # sees each change rather than the aggregate delta.
        self.branch.lock_read()
        self.addCleanup(self.branch.unlock)
        graph = self.branch.repository.get_graph()
        history = list(graph.iter_lefthand_ancestry(self.branch.last_revision(),
                                                    [_mod_revision.NULL_REVISION]))
        history.reverse()
        old_rev = history[0]
        new_rev = history[1]
        unique_revs = graph.find_unique_ancestors(new_rev, [old_rev])

        l1 = self.branch.repository.fileids_altered_by_revision_ids(
            unique_revs)
        l1 = set(l1.keys())

        l2 = self.compare_tree_fileids(self.branch, old_rev, new_rev)
        self.assertNotEqual(l2, l1)
        self.assertSubset(l2, l1)


def set_executability(wt, path, executable=True):
    """Set the executable bit for the file at path in the working tree

    os.chmod() doesn't work on windows. But TreeTransform can mark or
    unmark a file as executable.
    """
    with wt.transform() as tt:
        tt.set_executability(executable, tt.trans_id_tree_path(path))
        tt.apply()
