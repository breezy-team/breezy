# Copyright (C) 2007 Canonical Ltd
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

"""Test that we can use smart_add on all Tree implementations."""

from cStringIO import StringIO

from bzrlib import (
    add,
    errors,
    ignores,
    osutils,
    tests,
    workingtree,
    )
from bzrlib.add import (
    AddAction,
    AddFromBaseAction,
    )
from bzrlib.tests.test_smart_add import AddCustomIDAction
from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree


class TestSmartAddTree(TestCaseWithWorkingTree):

    def test_single_file(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a'])
        tree.smart_add(['tree'])

        tree.lock_read()
        try:
            files = [(path, status, kind)
                     for path, status, kind, file_id, parent_id
                      in tree.list_files(include_root=True)]
        finally:
            tree.unlock()
        self.assertEqual([('', 'V', 'directory'), ('a', 'V', 'file')],
                         files)

    def test_save_false(self):
        """Dry-run add doesn't permanently affect the tree."""
        wt = self.make_branch_and_tree('.')
        self.build_tree(['file'])
        wt.smart_add(['file'], save=False)
        # the file should not be added - no id.
        self.assertEqual(wt.path2id('file'), None)
        # and the disk state should be the same - reopen to check.
        wt = wt.bzrdir.open_workingtree()
        self.assertEqual(wt.path2id('file'), None)

    def test_add_dot_from_root(self):
        """Test adding . from the root of the tree.""" 
        paths = ("original/", "original/file1", "original/file2")
        self.build_tree(paths)
        wt = self.make_branch_and_tree('.')
        wt.smart_add((u".",))
        for path in paths:
            self.assertNotEqual(wt.path2id(path), None)

    def test_add_dot_from_subdir(self):
        """Test adding . from a subdir of the tree.""" 
        paths = ("original/", "original/file1", "original/file2")
        self.build_tree(paths)
        wt = self.make_branch_and_tree('.')
        wt.smart_add((u".",))
        for path in paths:
            self.assertNotEqual(wt.path2id(path), None)

    def test_add_tree_from_above_tree(self):
        """Test adding a tree from above the tree.""" 
        paths = ("original/", "original/file1", "original/file2")
        branch_paths = ("branch/", "branch/original/", "branch/original/file1",
                        "branch/original/file2")
        self.build_tree(branch_paths)
        wt = self.make_branch_and_tree('branch')
        wt.smart_add(("branch",))
        for path in paths:
            self.assertNotEqual(wt.path2id(path), None)

    def test_add_above_tree_preserves_tree(self):
        """Test nested trees are not affect by an add above them."""
        paths = ("original/", "original/file1", "original/file2")
        child_paths = ("path",)
        full_child_paths = ("original/child", "original/child/path")
        build_paths = ("original/", "original/file1", "original/file2", 
                       "original/child/", "original/child/path")
        
        self.build_tree(build_paths)
        wt = self.make_branch_and_tree('.')
        child_tree = self.make_branch_and_tree('original/child')
        wt.smart_add((".",))
        for path in paths:
            self.assertNotEqual((path, wt.path2id(path)),
                                (path, None))
        for path in full_child_paths:
            self.assertEqual((path, wt.path2id(path)),
                             (path, None))
        for path in child_paths:
            self.assertEqual(child_tree.path2id(path), None)

    def test_add_paths(self):
        """Test smart-adding a list of paths."""
        paths = ("file1", "file2")
        self.build_tree(paths)
        wt = self.make_branch_and_tree('.')
        wt.smart_add(paths)
        for path in paths:
            self.assertNotEqual(wt.path2id(path), None)
    
    def test_add_ignored_nested_paths(self):
        """Test smart-adding a list of paths which includes ignored ones."""
        wt = self.make_branch_and_tree('.')
        tree_shape = ("adir/", "adir/CVS/", "adir/CVS/afile", "adir/CVS/afile2")
        add_paths = ("adir/CVS", "adir/CVS/afile", "adir")
        expected_paths = ("adir", "adir/CVS", "adir/CVS/afile", "adir/CVS/afile2")
        self.build_tree(tree_shape)
        wt.smart_add(add_paths)
        for path in expected_paths:
            self.assertNotEqual(wt.path2id(path), None, "No id added for %s" % path)

    def test_add_non_existant(self):
        """Test smart-adding a file that does not exist."""
        wt = self.make_branch_and_tree('.')
        self.assertRaises(errors.NoSuchFile, wt.smart_add, ['non-existant-file'])

    def test_returns_and_ignores(self):
        """Correctly returns added/ignored files"""
        wt = self.make_branch_and_tree('.')
        # The default ignore list includes '*.py[co]', but not CVS
        ignores._set_user_ignores(['*.py[co]'])
        self.build_tree(['inertiatic/', 'inertiatic/esp', 'inertiatic/CVS',
                        'inertiatic/foo.pyc'])
        added, ignored = wt.smart_add(u'.')
        self.assertSubset(('inertiatic', 'inertiatic/esp', 'inertiatic/CVS'),
                          added)
        self.assertSubset(('*.py[co]',), ignored)
        self.assertSubset(('inertiatic/foo.pyc',), ignored['*.py[co]'])

    def test_add_multiple_dirs(self):
        """Test smart adding multiple directories at once."""
        added_paths = ['file1', 'file2',
                       'dir1/', 'dir1/file3',
                       'dir1/subdir2/', 'dir1/subdir2/file4',
                       'dir2/', 'dir2/file5',
                      ]
        not_added = ['file6', 'dir3/', 'dir3/file7', 'dir3/file8']
        self.build_tree(added_paths)
        self.build_tree(not_added)

        wt = self.make_branch_and_tree('.')
        wt.smart_add(['file1', 'file2', 'dir1', 'dir2'])

        for path in added_paths:
            self.assertNotEqual(None, wt.path2id(path.rstrip('/')),
                    'Failed to add path: %s' % (path,))
        for path in not_added:
            self.assertEqual(None, wt.path2id(path.rstrip('/')),
                    'Accidentally added path: %s' % (path,))

    def test_custom_ids(self):
        sio = StringIO()
        action = AddCustomIDAction(to_file=sio, should_print=True)
        self.build_tree(['file1', 'dir1/', 'dir1/file2'])

        wt = self.make_branch_and_tree('.')
        wt.smart_add(['.'], action=action)
        # The order of adds is not strictly fixed:
        sio.seek(0)
        lines = sorted(sio.readlines())
        self.assertEqualDiff(['added dir1 with id directory-dir1\n',
                              'added dir1/file2 with id file-dir1%file2\n',
                              'added file1 with id file-file1\n',
                             ], lines)
        wt.lock_read()
        self.addCleanup(wt.unlock)
        self.assertEqual([('', wt.path2id('')),
                          ('dir1', 'directory-dir1'),
                          ('dir1/file2', 'file-dir1%file2'),
                          ('file1', 'file-file1'),
                         ], [(path, ie.file_id) for path, ie
                                in wt.inventory.iter_entries()])

    def make_unicode_containing_tree(self):
        try:
            self.build_tree([u'a\u030a'])
        except UnicodeError:
            raise tests.TestSkipped('Filesystem cannot create unicode filenames')
        self.wt = self.make_branch_and_tree('.')

    def test_accessible_explicit(self):
        self.make_unicode_containing_tree()
        orig = osutils.normalized_filename
        osutils.normalized_filename = osutils._accessible_normalized_filename
        try:
            self.wt.smart_add([u'a\u030a'])
            self.wt.lock_read()
            self.addCleanup(self.wt.unlock)
            self.assertEqual([('', 'directory'), (u'\xe5', 'file')],
                    [(path, ie.kind) for path,ie in 
                        self.wt.inventory.iter_entries()])
        finally:
            osutils.normalized_filename = orig

    def test_accessible_implicit(self):
        self.make_unicode_containing_tree()
        orig = osutils.normalized_filename
        osutils.normalized_filename = osutils._accessible_normalized_filename
        try:
            self.wt.smart_add([])
            self.wt.lock_read()
            self.addCleanup(self.wt.unlock)
            self.assertEqual([('', 'directory'), (u'\xe5', 'file')],
                    [(path, ie.kind) for path,ie in 
                        self.wt.inventory.iter_entries()])
        finally:
            osutils.normalized_filename = orig

    def test_inaccessible_explicit(self):
        self.make_unicode_containing_tree()
        orig = osutils.normalized_filename
        osutils.normalized_filename = osutils._inaccessible_normalized_filename
        try:
            self.assertRaises(errors.InvalidNormalization,
                    self.wt.smart_add, [u'a\u030a'])
        finally:
            osutils.normalized_filename = orig

    def test_inaccessible_implicit(self):
        self.make_unicode_containing_tree()
        orig = osutils.normalized_filename
        osutils.normalized_filename = osutils._inaccessible_normalized_filename
        try:
            # TODO: jam 20060701 In the future, this should probably
            #       just ignore files that don't fit the normalization
            #       rules, rather than exploding
            self.assertRaises(errors.InvalidNormalization,
                    self.wt.smart_add, [])
        finally:
            osutils.normalized_filename = orig
