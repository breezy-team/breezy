# Copyright (C) 2005, 2006 by Canonical Ltd

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

import bzrlib
from bzrlib.tests import TestCaseWithTransport
from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir, BzrDirMetaFormat1
from bzrlib.workingtree import WorkingTree
from bzrlib.commit import Commit, NullCommitReporter
from bzrlib.config import BranchConfig
from bzrlib.errors import (PointlessCommit, BzrError, SigningFailed, 
                           LockContention)


# TODO: Test commit with some added, and added-but-missing files

class MustSignConfig(BranchConfig):

    def signature_needed(self):
        return True

    def gpg_signing_command(self):
        return ['cat', '-']


class BranchWithHooks(BranchConfig):

    def post_commit(self):
        return "bzrlib.ahook bzrlib.ahook"


class CapturingReporter(NullCommitReporter):
    """This reporter captures the calls made to it for evaluation later."""

    def __init__(self):
        # a list of the calls this received
        self.calls = []

    def snapshot_change(self, change, path):
        self.calls.append(('change', change, path))

    def deleted(self, file_id):
        self.calls.append(('deleted', file_id))

    def missing(self, path):
        self.calls.append(('missing', path))

    def renamed(self, change, old_path, new_path):
        self.calls.append(('renamed', change, old_path, new_path))


class TestCommit(TestCaseWithTransport):

    def test_simple_commit(self):
        """Commit and check two versions of a single file."""
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        file('hello', 'w').write('hello world')
        wt.add('hello')
        wt.commit(message='add hello')
        file_id = wt.path2id('hello')

        file('hello', 'w').write('version 2')
        wt.commit(message='commit 2')

        eq = self.assertEquals
        eq(b.revno(), 2)
        rh = b.revision_history()
        rev = b.repository.get_revision(rh[0])
        eq(rev.message, 'add hello')

        tree1 = b.repository.revision_tree(rh[0])
        text = tree1.get_file_text(file_id)
        eq(text, 'hello world')

        tree2 = b.repository.revision_tree(rh[1])
        eq(tree2.get_file_text(file_id), 'version 2')

    def test_delete_commit(self):
        """Test a commit with a deleted file"""
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        file('hello', 'w').write('hello world')
        wt.add(['hello'], ['hello-id'])
        wt.commit(message='add hello')

        os.remove('hello')
        wt.commit('removed hello', rev_id='rev2')

        tree = b.repository.revision_tree('rev2')
        self.assertFalse(tree.has_id('hello-id'))

    def test_pointless_commit(self):
        """Commit refuses unless there are changes or it's forced."""
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        file('hello', 'w').write('hello')
        wt.add(['hello'])
        wt.commit(message='add hello')
        self.assertEquals(b.revno(), 1)
        self.assertRaises(PointlessCommit,
                          wt.commit,
                          message='fails',
                          allow_pointless=False)
        self.assertEquals(b.revno(), 1)
        
    def test_commit_empty(self):
        """Commiting an empty tree works."""
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        wt.commit(message='empty tree', allow_pointless=True)
        self.assertRaises(PointlessCommit,
                          wt.commit,
                          message='empty tree',
                          allow_pointless=False)
        wt.commit(message='empty tree', allow_pointless=True)
        self.assertEquals(b.revno(), 2)

    def test_selective_delete(self):
        """Selective commit in tree with deletions"""
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        file('hello', 'w').write('hello')
        file('buongia', 'w').write('buongia')
        wt.add(['hello', 'buongia'],
              ['hello-id', 'buongia-id'])
        wt.commit(message='add files',
                 rev_id='test@rev-1')
        
        os.remove('hello')
        file('buongia', 'w').write('new text')
        wt.commit(message='update text',
                 specific_files=['buongia'],
                 allow_pointless=False,
                 rev_id='test@rev-2')

        wt.commit(message='remove hello',
                 specific_files=['hello'],
                 allow_pointless=False,
                 rev_id='test@rev-3')

        eq = self.assertEquals
        eq(b.revno(), 3)

        tree2 = b.repository.revision_tree('test@rev-2')
        self.assertTrue(tree2.has_filename('hello'))
        self.assertEquals(tree2.get_file_text('hello-id'), 'hello')
        self.assertEquals(tree2.get_file_text('buongia-id'), 'new text')
        
        tree3 = b.repository.revision_tree('test@rev-3')
        self.assertFalse(tree3.has_filename('hello'))
        self.assertEquals(tree3.get_file_text('buongia-id'), 'new text')

    def test_commit_rename(self):
        """Test commit of a revision where a file is renamed."""
        tree = self.make_branch_and_tree('.')
        b = tree.branch
        self.build_tree(['hello'], line_endings='binary')
        tree.add(['hello'], ['hello-id'])
        tree.commit(message='one', rev_id='test@rev-1', allow_pointless=False)

        tree.rename_one('hello', 'fruity')
        tree.commit(message='renamed', rev_id='test@rev-2', allow_pointless=False)

        eq = self.assertEquals
        tree1 = b.repository.revision_tree('test@rev-1')
        eq(tree1.id2path('hello-id'), 'hello')
        eq(tree1.get_file_text('hello-id'), 'contents of hello\n')
        self.assertFalse(tree1.has_filename('fruity'))
        self.check_inventory_shape(tree1.inventory, ['hello'])
        ie = tree1.inventory['hello-id']
        eq(ie.revision, 'test@rev-1')

        tree2 = b.repository.revision_tree('test@rev-2')
        eq(tree2.id2path('hello-id'), 'fruity')
        eq(tree2.get_file_text('hello-id'), 'contents of hello\n')
        self.check_inventory_shape(tree2.inventory, ['fruity'])
        ie = tree2.inventory['hello-id']
        eq(ie.revision, 'test@rev-2')

    def test_reused_rev_id(self):
        """Test that a revision id cannot be reused in a branch"""
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        wt.commit('initial', rev_id='test@rev-1', allow_pointless=True)
        self.assertRaises(Exception,
                          wt.commit,
                          message='reused id',
                          rev_id='test@rev-1',
                          allow_pointless=True)

    def test_commit_move(self):
        """Test commit of revisions with moved files and directories"""
        eq = self.assertEquals
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        r1 = 'test@rev-1'
        self.build_tree(['hello', 'a/', 'b/'])
        wt.add(['hello', 'a', 'b'], ['hello-id', 'a-id', 'b-id'])
        wt.commit('initial', rev_id=r1, allow_pointless=False)
        wt.move(['hello'], 'a')
        r2 = 'test@rev-2'
        wt.commit('two', rev_id=r2, allow_pointless=False)
        self.check_inventory_shape(wt.read_working_inventory(),
                                   ['a', 'a/hello', 'b'])

        wt.move(['b'], 'a')
        r3 = 'test@rev-3'
        wt.commit('three', rev_id=r3, allow_pointless=False)
        self.check_inventory_shape(wt.read_working_inventory(),
                                   ['a', 'a/hello', 'a/b'])
        self.check_inventory_shape(b.repository.get_revision_inventory(r3),
                                   ['a', 'a/hello', 'a/b'])

        wt.move(['a/hello'], 'a/b')
        r4 = 'test@rev-4'
        wt.commit('four', rev_id=r4, allow_pointless=False)
        self.check_inventory_shape(wt.read_working_inventory(),
                                   ['a', 'a/b/hello', 'a/b'])

        inv = b.repository.get_revision_inventory(r4)
        eq(inv['hello-id'].revision, r4)
        eq(inv['a-id'].revision, r1)
        eq(inv['b-id'].revision, r3)
        
    def test_removed_commit(self):
        """Commit with a removed file"""
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        file('hello', 'w').write('hello world')
        wt.add(['hello'], ['hello-id'])
        wt.commit(message='add hello')
        wt.remove('hello')
        wt.commit('removed hello', rev_id='rev2')

        tree = b.repository.revision_tree('rev2')
        self.assertFalse(tree.has_id('hello-id'))

    def test_committed_ancestry(self):
        """Test commit appends revisions to ancestry."""
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        rev_ids = []
        for i in range(4):
            file('hello', 'w').write((str(i) * 4) + '\n')
            if i == 0:
                wt.add(['hello'], ['hello-id'])
            rev_id = 'test@rev-%d' % (i+1)
            rev_ids.append(rev_id)
            wt.commit(message='rev %d' % (i+1),
                     rev_id=rev_id)
        eq = self.assertEquals
        eq(b.revision_history(), rev_ids)
        for i in range(4):
            anc = b.repository.get_ancestry(rev_ids[i])
            eq(anc, [None] + rev_ids[:i+1])

    def test_commit_new_subdir_child_selective(self):
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        self.build_tree(['dir/', 'dir/file1', 'dir/file2'])
        wt.add(['dir', 'dir/file1', 'dir/file2'],
              ['dirid', 'file1id', 'file2id'])
        wt.commit('dir/file1', specific_files=['dir/file1'], rev_id='1')
        inv = b.repository.get_inventory('1')
        self.assertEqual('1', inv['dirid'].revision)
        self.assertEqual('1', inv['file1id'].revision)
        # FIXME: This should raise a KeyError I think, rbc20051006
        self.assertRaises(BzrError, inv.__getitem__, 'file2id')

    def test_strict_commit(self):
        """Try and commit with unknown files and strict = True, should fail."""
        from bzrlib.errors import StrictCommitFailed
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        file('hello', 'w').write('hello world')
        wt.add('hello')
        file('goodbye', 'w').write('goodbye cruel world!')
        self.assertRaises(StrictCommitFailed, wt.commit,
            message='add hello but not goodbye', strict=True)

    def test_strict_commit_without_unknowns(self):
        """Try and commit with no unknown files and strict = True,
        should work."""
        from bzrlib.errors import StrictCommitFailed
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        file('hello', 'w').write('hello world')
        wt.add('hello')
        wt.commit(message='add hello', strict=True)

    def test_nonstrict_commit(self):
        """Try and commit with unknown files and strict = False, should work."""
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        file('hello', 'w').write('hello world')
        wt.add('hello')
        file('goodbye', 'w').write('goodbye cruel world!')
        wt.commit(message='add hello but not goodbye', strict=False)

    def test_nonstrict_commit_without_unknowns(self):
        """Try and commit with no unknown files and strict = False,
        should work."""
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        file('hello', 'w').write('hello world')
        wt.add('hello')
        wt.commit(message='add hello', strict=False)

    def test_signed_commit(self):
        import bzrlib.gpg
        import bzrlib.commit as commit
        oldstrategy = bzrlib.gpg.GPGStrategy
        wt = self.make_branch_and_tree('.')
        branch = wt.branch
        wt.commit("base", allow_pointless=True, rev_id='A')
        self.failIf(branch.repository.has_signature_for_revision_id('A'))
        try:
            from bzrlib.testament import Testament
            # monkey patch gpg signing mechanism
            bzrlib.gpg.GPGStrategy = bzrlib.gpg.LoopbackGPGStrategy
            commit.Commit(config=MustSignConfig(branch)).commit(message="base",
                                                      allow_pointless=True,
                                                      rev_id='B',
                                                      working_tree=wt)
            self.assertEqual(Testament.from_revision(branch.repository,
                             'B').as_short_text(),
                             branch.repository.get_signature_text('B'))
        finally:
            bzrlib.gpg.GPGStrategy = oldstrategy

    def test_commit_failed_signature(self):
        import bzrlib.gpg
        import bzrlib.commit as commit
        oldstrategy = bzrlib.gpg.GPGStrategy
        wt = self.make_branch_and_tree('.')
        branch = wt.branch
        wt.commit("base", allow_pointless=True, rev_id='A')
        self.failIf(branch.repository.has_signature_for_revision_id('A'))
        try:
            from bzrlib.testament import Testament
            # monkey patch gpg signing mechanism
            bzrlib.gpg.GPGStrategy = bzrlib.gpg.DisabledGPGStrategy
            config = MustSignConfig(branch)
            self.assertRaises(SigningFailed,
                              commit.Commit(config=config).commit,
                              message="base",
                              allow_pointless=True,
                              rev_id='B',
                              working_tree=wt)
            branch = Branch.open(self.get_url('.'))
            self.assertEqual(branch.revision_history(), ['A'])
            self.failIf(branch.repository.has_revision('B'))
        finally:
            bzrlib.gpg.GPGStrategy = oldstrategy

    def test_commit_invokes_hooks(self):
        import bzrlib.commit as commit
        wt = self.make_branch_and_tree('.')
        branch = wt.branch
        calls = []
        def called(branch, rev_id):
            calls.append('called')
        bzrlib.ahook = called
        try:
            config = BranchWithHooks(branch)
            commit.Commit(config=config).commit(
                            message = "base",
                            allow_pointless=True,
                            rev_id='A', working_tree = wt)
            self.assertEqual(['called', 'called'], calls)
        finally:
            del bzrlib.ahook

    def test_commit_object_doesnt_set_nick(self):
        # using the Commit object directly does not set the branch nick.
        wt = self.make_branch_and_tree('.')
        c = Commit()
        c.commit(working_tree=wt, message='empty tree', allow_pointless=True)
        self.assertEquals(wt.branch.revno(), 1)
        self.assertEqual({},
                         wt.branch.repository.get_revision(
                            wt.branch.last_revision()).properties)

    def test_safe_master_lock(self):
        os.mkdir('master')
        master = BzrDirMetaFormat1().initialize('master')
        master.create_repository()
        master_branch = master.create_branch()
        master.create_workingtree()
        bound = master.sprout('bound')
        wt = bound.open_workingtree()
        wt.branch.set_bound_location(os.path.realpath('master'))
        master_branch.lock_write()
        try:
            self.assertRaises(LockContention, wt.commit, 'silly')
        finally:
            master_branch.unlock()

    def test_commit_bound_merge(self):
        # see bug #43959; commit of a merge in a bound branch fails to push
        # the new commit into the master
        master_branch = self.make_branch('master')
        bound_tree = self.make_branch_and_tree('bound')
        bound_tree.branch.bind(master_branch)

        self.build_tree_contents([('bound/content_file', 'initial contents\n')])
        bound_tree.add(['content_file'])
        bound_tree.commit(message='woo!')

        other_bzrdir = master_branch.bzrdir.sprout('other')
        other_tree = other_bzrdir.open_workingtree()

        # do a commit to the the other branch changing the content file so
        # that our commit after merging will have a merged revision in the
        # content file history.
        self.build_tree_contents([('other/content_file', 'change in other\n')])
        other_tree.commit('change in other')

        # do a merge into the bound branch from other, and then change the
        # content file locally to force a new revision (rather than using the
        # revision from other). This forces extra processing in commit.
        self.merge(other_tree.branch, bound_tree)
        self.build_tree_contents([('bound/content_file', 'change in bound\n')])

        # before #34959 was fixed, this failed with 'revision not present in
        # weave' when trying to implicitly push from the bound branch to the master
        bound_tree.commit(message='commit of merge in bound tree')

    def test_commit_reporting_after_merge(self):
        # when doing a commit of a merge, the reporter needs to still 
        # be called for each item that is added/removed/deleted.
        this_tree = self.make_branch_and_tree('this')
        # we need a bunch of files and dirs, to perform one action on each.
        self.build_tree([
            'this/dirtorename/',
            'this/dirtoreparent/',
            'this/dirtoleave/',
            'this/dirtoremove/',
            'this/filetoreparent',
            'this/filetorename',
            'this/filetomodify',
            'this/filetoremove',
            'this/filetoleave']
            )
        this_tree.add([
            'dirtorename',
            'dirtoreparent',
            'dirtoleave',
            'dirtoremove',
            'filetoreparent',
            'filetorename',
            'filetomodify',
            'filetoremove',
            'filetoleave']
            )
        this_tree.commit('create_files')
        other_dir = this_tree.bzrdir.sprout('other')
        other_tree = other_dir.open_workingtree()
        other_tree.lock_write()
        # perform the needed actions on the files and dirs.
        try:
            other_tree.rename_one('dirtorename', 'renameddir')
            other_tree.rename_one('dirtoreparent', 'renameddir/reparenteddir')
            other_tree.rename_one('filetorename', 'renamedfile')
            other_tree.rename_one('filetoreparent', 'renameddir/reparentedfile')
            other_tree.remove(['dirtoremove', 'filetoremove'])
            self.build_tree_contents([
                ('other/newdir/', ),
                ('other/filetomodify', 'new content'),
                ('other/newfile', 'new file content')])
            other_tree.add('newfile')
            other_tree.add('newdir/')
            other_tree.commit('modify all sample files and dirs.')
        finally:
            other_tree.unlock()
        self.merge(other_tree.branch, this_tree)
        reporter = CapturingReporter()
        this_tree.commit('do the commit', reporter=reporter)
        self.assertEqual([
            ('change', 'unchanged', 'dirtoleave'),
            ('change', 'unchanged', 'filetoleave'),
            ('change', 'modified', 'filetomodify'),
            ('change', 'added', 'newdir'),
            ('change', 'added', 'newfile'),
            ('renamed', 'renamed', 'dirtorename', 'renameddir'),
            ('renamed', 'renamed', 'dirtoreparent', 'renameddir/reparenteddir'),
            ('renamed', 'renamed', 'filetoreparent', 'renameddir/reparentedfile'),
            ('renamed', 'renamed', 'filetorename', 'renamedfile'),
            ('deleted', 'dirtoremove'),
            ('deleted', 'filetoremove'),
            ],
            reporter.calls)
