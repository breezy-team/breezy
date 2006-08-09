# Copyright (C) 2005, 2006 Canonical Ltd
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

from cStringIO import StringIO
import os
import unittest

from bzrlib import errors, ignores, osutils
from bzrlib.add import smart_add, smart_add_tree, AddAction
from bzrlib.tests import TestCase, TestCaseWithTransport, TestSkipped
from bzrlib.errors import NoSuchFile
from bzrlib.inventory import InventoryFile, Inventory
from bzrlib.workingtree import WorkingTree


class TestSmartAdd(TestCaseWithTransport):

    def test_add_dot_from_root(self):
        """Test adding . from the root of the tree.""" 
        from bzrlib.add import smart_add
        paths = ("original/", "original/file1", "original/file2")
        self.build_tree(paths)
        wt = self.make_branch_and_tree('.')
        smart_add_tree(wt, (u".",))
        for path in paths:
            self.assertNotEqual(wt.path2id(path), None)

    def test_add_dot_from_subdir(self):
        """Test adding . from a subdir of the tree.""" 
        from bzrlib.add import smart_add
        paths = ("original/", "original/file1", "original/file2")
        self.build_tree(paths)
        wt = self.make_branch_and_tree('.')
        os.chdir("original")
        smart_add_tree(wt, (u".",))
        for path in paths:
            self.assertNotEqual(wt.path2id(path), None)

    def test_add_tree_from_above_tree(self):
        """Test adding a tree from above the tree.""" 
        from bzrlib.add import smart_add
        paths = ("original/", "original/file1", "original/file2")
        branch_paths = ("branch/", "branch/original/", "branch/original/file1",
                        "branch/original/file2")
        self.build_tree(branch_paths)
        wt = self.make_branch_and_tree('branch')
        smart_add_tree(wt, ("branch",))
        for path in paths:
            self.assertNotEqual(wt.path2id(path), None)

    def test_add_above_tree_preserves_tree(self):
        """Test nested trees are not affect by an add above them."""
        from bzrlib.add import smart_add
        paths = ("original/", "original/file1", "original/file2")
        child_paths = ("path",)
        full_child_paths = ("original/child", "original/child/path")
        build_paths = ("original/", "original/file1", "original/file2", 
                       "original/child/", "original/child/path")
        
        self.build_tree(build_paths)
        wt = self.make_branch_and_tree('.')
        child_tree = self.make_branch_and_tree('original/child')
        smart_add_tree(wt, (".",))
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
        from bzrlib.add import smart_add
        paths = ("file1", "file2")
        self.build_tree(paths)
        wt = self.make_branch_and_tree('.')
        smart_add_tree(wt, paths)
        for path in paths:
            self.assertNotEqual(wt.path2id(path), None)
    
    def test_add_ignored_nested_paths(self):
        """Test smart-adding a list of paths which includes ignored ones."""
        wt = self.make_branch_and_tree('.')
        tree_shape = ("adir/", "adir/CVS/", "adir/CVS/afile", "adir/CVS/afile2")
        add_paths = ("adir/CVS", "adir/CVS/afile", "adir")
        expected_paths = ("adir", "adir/CVS", "adir/CVS/afile", "adir/CVS/afile2")
        self.build_tree(tree_shape)
        smart_add_tree(wt, add_paths)
        for path in expected_paths:
            self.assertNotEqual(wt.path2id(path), None, "No id added for %s" % path)

    def test_save_false(self):
        """Test smart-adding a path with save set to false."""
        wt = self.make_branch_and_tree('.')
        self.build_tree(['file'])
        smart_add_tree(wt, ['file'], save=False)
        self.assertNotEqual(wt.path2id('file'), None, "No id added for 'file'")
        wt.read_working_inventory()
        self.assertEqual(wt.path2id('file'), None)

    def test_add_dry_run(self):
        """Test a dry run add, make sure nothing is added."""
        from bzrlib.commands import run_bzr
        ignores._set_user_ignores(['./.bazaar'])
        eq = self.assertEqual
        wt = self.make_branch_and_tree('.')
        self.build_tree(['inertiatic/', 'inertiatic/esp'])
        eq(list(wt.unknowns()), ['inertiatic'])
        self.capture('add --dry-run .')
        eq(list(wt.unknowns()), ['inertiatic'])

    def test_add_non_existant(self):
        """Test smart-adding a file that does not exist."""
        from bzrlib.add import smart_add
        wt = self.make_branch_and_tree('.')
        self.assertRaises(NoSuchFile, smart_add_tree, wt, 'non-existant-file')

    def test_returns_and_ignores(self):
        """Correctly returns added/ignored files"""
        from bzrlib.commands import run_bzr
        wt = self.make_branch_and_tree('.')
        # The default ignore list includes '*.py[co]', but not CVS
        ignores._set_user_ignores(['./.bazaar', '*.py[co]'])
        self.build_tree(['inertiatic/', 'inertiatic/esp', 'inertiatic/CVS',
                        'inertiatic/foo.pyc'])
        added, ignored = smart_add_tree(wt, u'.')
        self.assertSubset(('inertiatic', 'inertiatic/esp', 'inertiatic/CVS'),
                          added)
        self.assertSubset(('*.py[co]',), ignored)
        self.assertSubset(('inertiatic/foo.pyc',), ignored['*.py[co]'])


class CustomIDAddAction(AddAction):

    def __call__(self, inv, parent_ie, path, kind):
        # The first part just logs if appropriate
        # Now generate a custom id
        file_id = kind + '-' + path.raw_path.replace('/', '%')
        if self.should_print:
            self._to_file.write('added %s with id %s\n' 
                                % (path.raw_path, file_id))
        return file_id


class TestSmartAddTree(TestCaseWithTransport):
    """Test smart adds with a specified branch."""

    def test_add_dot_from_root(self):
        """Test adding . from the root of the tree.""" 
        paths = ("original/", "original/file1", "original/file2")
        self.build_tree(paths)
        wt = self.make_branch_and_tree('.')
        smart_add_tree(wt, (u".",))
        for path in paths:
            self.assertNotEqual(wt.path2id(path), None)

    def test_add_dot_from_subdir(self):
        """Test adding . from a subdir of the tree.""" 
        paths = ("original/", "original/file1", "original/file2")
        self.build_tree(paths)
        wt = self.make_branch_and_tree('.')
        os.chdir("original")
        smart_add_tree(wt, (u".",))
        for path in paths:
            self.assertNotEqual(wt.path2id(path), None)

    def test_add_tree_from_above_tree(self):
        """Test adding a tree from above the tree.""" 
        paths = ("original/", "original/file1", "original/file2")
        branch_paths = ("branch/", "branch/original/", "branch/original/file1",
                        "branch/original/file2")
        self.build_tree(branch_paths)
        tree = self.make_branch_and_tree('branch')
        smart_add_tree(tree, ("branch",))
        for path in paths:
            self.assertNotEqual(tree.path2id(path), None)

    def test_add_above_tree_preserves_tree(self):
        """Test nested trees are not affect by an add above them."""
        paths = ("original/", "original/file1", "original/file2")
        child_paths = ("path")
        full_child_paths = ("original/child", "original/child/path")
        build_paths = ("original/", "original/file1", "original/file2", 
                       "original/child/", "original/child/path")
        self.build_tree(build_paths)
        tree = self.make_branch_and_tree('.')
        child_tree = self.make_branch_and_tree("original/child")
        smart_add_tree(tree, (u".",))
        for path in paths:
            self.assertNotEqual((path, tree.path2id(path)),
                                (path, None))
        for path in full_child_paths:
            self.assertEqual((path, tree.path2id(path)),
                             (path, None))
        for path in child_paths:
            self.assertEqual(child_tree.path2id(path), None)

    def test_add_paths(self):
        """Test smart-adding a list of paths."""
        paths = ("file1", "file2")
        self.build_tree(paths)
        wt = self.make_branch_and_tree('.')
        smart_add_tree(wt, paths)
        for path in paths:
            self.assertNotEqual(wt.path2id(path), None)

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
        smart_add_tree(wt, ['file1', 'file2', 'dir1', 'dir2'])

        for path in added_paths:
            self.assertNotEqual(None, wt.path2id(path.rstrip('/')),
                    'Failed to add path: %s' % (path,))
        for path in not_added:
            self.assertEqual(None, wt.path2id(path.rstrip('/')),
                    'Accidentally added path: %s' % (path,))

    def test_custom_ids(self):
        sio = StringIO()
        action = CustomIDAddAction(to_file=sio, should_print=True)
        self.build_tree(['file1', 'dir1/', 'dir1/file2'])

        wt = self.make_branch_and_tree('.')
        smart_add_tree(wt, ['.'], action=action)
        self.assertEqualDiff('added dir1 with id directory-dir1\n'
                             'added file1 with id file-file1\n'
                             'added dir1/file2 with id file-dir1%file2\n',
                             sio.getvalue())
        self.assertEqual([('', wt.inventory.root.file_id),
                          ('dir1', 'directory-dir1'),
                          ('dir1/file2', 'file-dir1%file2'),
                          ('file1', 'file-file1'),
                         ], [(path, ie.file_id) for path, ie
                                in wt.inventory.iter_entries()])


class TestAddNonNormalized(TestCaseWithTransport):

    def make(self):
        try:
            self.build_tree([u'a\u030a'])
        except UnicodeError:
            raise TestSkipped('Filesystem cannot create unicode filenames')

        self.wt = self.make_branch_and_tree('.')

    def test_accessible_explicit(self):
        self.make()
        orig = osutils.normalized_filename
        osutils.normalized_filename = osutils._accessible_normalized_filename
        try:
            smart_add_tree(self.wt, [u'a\u030a'])
            self.assertEqual([('', 'directory'), (u'\xe5', 'file')],
                    [(path, ie.kind) for path,ie in 
                        self.wt.inventory.iter_entries()])
        finally:
            osutils.normalized_filename = orig

    def test_accessible_implicit(self):
        self.make()
        orig = osutils.normalized_filename
        osutils.normalized_filename = osutils._accessible_normalized_filename
        try:
            smart_add_tree(self.wt, [])
            self.assertEqual([('', 'directory'), (u'\xe5', 'file')],
                    [(path, ie.kind) for path,ie in 
                        self.wt.inventory.iter_entries()])
        finally:
            osutils.normalized_filename = orig

    def test_inaccessible_explicit(self):
        self.make()
        orig = osutils.normalized_filename
        osutils.normalized_filename = osutils._inaccessible_normalized_filename
        try:
            self.assertRaises(errors.InvalidNormalization,
                    smart_add_tree, self.wt, [u'a\u030a'])
        finally:
            osutils.normalized_filename = orig

    def test_inaccessible_implicit(self):
        self.make()
        orig = osutils.normalized_filename
        osutils.normalized_filename = osutils._inaccessible_normalized_filename
        try:
            # TODO: jam 20060701 In the future, this should probably
            #       just ignore files that don't fit the normalization
            #       rules, rather than exploding
            self.assertRaises(errors.InvalidNormalization,
                    smart_add_tree, self.wt, [])
        finally:
            osutils.normalized_filename = orig


class TestAddActions(TestCase):

    def test_quiet(self):
        self.run_action("")

    def test__print(self):
        self.run_action("added path\n")

    def run_action(self, output):
        from bzrlib.add import AddAction, FastPath
        inv = Inventory()
        stdout = StringIO()
        action = AddAction(to_file=stdout, should_print=bool(output))

        self.apply_redirected(None, stdout, None, action, inv, None, FastPath('path'), 'file')
        self.assertEqual(stdout.getvalue(), output)
