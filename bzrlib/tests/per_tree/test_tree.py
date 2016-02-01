# Copyright (C) 2006-2009, 2011, 2012, 2016 Canonical Ltd
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

from bzrlib import (
    errors,
    conflicts,
    osutils,
    revisiontree,
    tests,
    workingtree_4,
    )
from bzrlib.tests import TestSkipped
from bzrlib.tests.per_tree import TestCaseWithTree
from bzrlib.symbol_versioning import (
    deprecated_in,
    )


class TestAnnotate(TestCaseWithTree):

    def test_annotate(self):
        work_tree = self.make_branch_and_tree('wt')
        tree = self.get_tree_no_parents_abc_content(work_tree)
        tree_revision = getattr(tree, 'get_revision_id', lambda: 'current:')()
        tree.lock_read()
        self.addCleanup(tree.unlock)
        for revision, line in tree.annotate_iter('a-id'):
            self.assertEqual('contents of a\n', line)
            self.assertEqual(tree_revision, revision)
        tree_revision = getattr(tree, 'get_revision_id', lambda: 'random:')()
        for revision, line in tree.annotate_iter('a-id', 'random:'):
            self.assertEqual('contents of a\n', line)
            self.assertEqual(tree_revision, revision)


class TestPlanFileMerge(TestCaseWithTree):

    def test_plan_file_merge(self):
        work_a = self.make_branch_and_tree('wta')
        self.build_tree_contents([('wta/file', 'a\nb\nc\nd\n')])
        work_a.add('file', 'file-id')
        work_a.commit('base version')
        work_b = work_a.bzrdir.sprout('wtb').open_workingtree()
        self.build_tree_contents([('wta/file', 'b\nc\nd\ne\n')])
        tree_a = self.workingtree_to_test_tree(work_a)
        tree_a.lock_read()
        self.addCleanup(tree_a.unlock)
        self.build_tree_contents([('wtb/file', 'a\nc\nd\nf\n')])
        tree_b = self.workingtree_to_test_tree(work_b)
        tree_b.lock_read()
        self.addCleanup(tree_b.unlock)
        self.assertEqual([
            ('killed-a', 'a\n'),
            ('killed-b', 'b\n'),
            ('unchanged', 'c\n'),
            ('unchanged', 'd\n'),
            ('new-a', 'e\n'),
            ('new-b', 'f\n'),
        ], list(tree_a.plan_file_merge('file-id', tree_b)))


class TestReference(TestCaseWithTree):

    def skip_if_no_reference(self, tree):
        if not getattr(tree, 'supports_tree_reference', lambda: False)():
            raise tests.TestNotApplicable('Tree references not supported')

    def create_nested(self):
        work_tree = self.make_branch_and_tree('wt')
        work_tree.lock_write()
        try:
            self.skip_if_no_reference(work_tree)
            subtree = self.make_branch_and_tree('wt/subtree')
            subtree.set_root_id('sub-root')
            subtree.commit('foo', rev_id='sub-1')
            work_tree.add_reference(subtree)
        finally:
            work_tree.unlock()
        tree = self._convert_tree(work_tree)
        self.skip_if_no_reference(tree)
        return tree

    def test_get_reference_revision(self):
        tree = self.create_nested()
        tree.lock_read()
        self.addCleanup(tree.unlock)
        path = tree.id2path('sub-root')
        self.assertEqual('sub-1',
            tree.get_reference_revision('sub-root', path))

    def test_iter_references(self):
        tree = self.create_nested()
        tree.lock_read()
        self.addCleanup(tree.unlock)
        entry = tree.root_inventory['sub-root']
        self.assertEqual([(u'subtree', 'sub-root')],
            list(tree.iter_references()))

    def test_get_root_id(self):
        # trees should return some kind of root id; it can be none
        tree = self.make_branch_and_tree('tree')
        root_id = tree.get_root_id()
        if root_id is not None:
            self.assertIsInstance(root_id, str)


class TestFileIds(TestCaseWithTree):

    def test_id2path(self):
        # translate from file-id back to path
        work_tree = self.make_branch_and_tree('wt')
        tree = self.get_tree_no_parents_abc_content(work_tree)
        tree.lock_read()
        try:
            self.assertEqual(u'a', tree.id2path('a-id'))
            # other ids give an error- don't return None for this case
            self.assertRaises(errors.NoSuchId, tree.id2path, 'a')
        finally:
            tree.unlock()

    def test_all_file_ids(self):
        work_tree = self.make_branch_and_tree('wt')
        tree = self.get_tree_no_parents_abc_content(work_tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual(tree.all_file_ids(),
                         set(['b-id', 'root-id', 'c-id', 'a-id']))


class TestStoredKind(TestCaseWithTree):

    def test_stored_kind(self):
        tree = self.make_branch_and_tree('tree')
        work_tree = self.make_branch_and_tree('wt')
        tree = self.get_tree_no_parents_abc_content(work_tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual('file', tree.stored_kind('a-id'))
        self.assertEqual('directory', tree.stored_kind('b-id'))


class TestFileContent(TestCaseWithTree):

    def test_get_file(self):
        work_tree = self.make_branch_and_tree('wt')
        tree = self.get_tree_no_parents_abc_content_2(work_tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        # Test lookup without path works
        file_without_path = tree.get_file('a-id')
        try:
            lines = file_without_path.readlines()
            self.assertEqual(['foobar\n'], lines)
        finally:
            file_without_path.close()
        # Test lookup with path works
        file_with_path = tree.get_file('a-id', path='a')
        try:
            lines = file_with_path.readlines()
            self.assertEqual(['foobar\n'], lines)
        finally:
            file_with_path.close()

    def test_get_file_text(self):
        work_tree = self.make_branch_and_tree('wt')
        tree = self.get_tree_no_parents_abc_content_2(work_tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        # test read by file-id
        self.assertEqual('foobar\n', tree.get_file_text('a-id'))
        # test read by path
        self.assertEqual('foobar\n', tree.get_file_text('a-id', path='a'))

    def test_get_file_lines(self):
        work_tree = self.make_branch_and_tree('wt')
        tree = self.get_tree_no_parents_abc_content_2(work_tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        # test read by file-id
        self.assertEqual(['foobar\n'], tree.get_file_lines('a-id'))
        # test read by path
        self.assertEqual(['foobar\n'], tree.get_file_lines('a-id', path='a'))

    def test_get_file_lines_multi_line_breaks(self):
        work_tree = self.make_branch_and_tree('wt')
        self.build_tree_contents([('wt/foobar', 'a\rb\nc\r\nd')])
        work_tree.add('foobar', 'foobar-id')
        tree = self._convert_tree(work_tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual(['a\rb\n', 'c\r\n', 'd'],
                         tree.get_file_lines('foobar-id'))


class TestExtractFilesBytes(TestCaseWithTree):

    def test_iter_files_bytes(self):
        work_tree = self.make_branch_and_tree('wt')
        self.build_tree_contents([('wt/foo', 'foo'),
                                  ('wt/bar', 'bar'),
                                  ('wt/baz', 'baz')])
        work_tree.add(['foo', 'bar', 'baz'], ['foo-id', 'bar-id', 'baz-id'])
        tree = self._convert_tree(work_tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        extracted = dict((i, ''.join(b)) for i, b in
                         tree.iter_files_bytes([('foo-id', 'id1'),
                                                ('bar-id', 'id2'),
                                                ('baz-id', 'id3')]))
        self.assertEqual('foo', extracted['id1'])
        self.assertEqual('bar', extracted['id2'])
        self.assertEqual('baz', extracted['id3'])
        self.assertRaises(errors.NoSuchId, lambda: list(
                          tree.iter_files_bytes(
                          [('qux-id', 'file1-notpresent')])))


class TestConflicts(TestCaseWithTree):

    def test_conflicts(self):
        """Tree.conflicts() should return a ConflictList instance."""
        work_tree = self.make_branch_and_tree('wt')
        tree = self._convert_tree(work_tree)
        self.assertIsInstance(tree.conflicts(), conflicts.ConflictList)


class TestIterEntriesByDir(TestCaseWithTree):

    def test_iteration_order(self):
        work_tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/b/', 'a/b/c', 'a/d/', 'a/d/e', 'f/', 'f/g'])
        work_tree.add(['a', 'a/b', 'a/b/c', 'a/d', 'a/d/e', 'f', 'f/g'])
        tree = self._convert_tree(work_tree)
        output_order = [p for p, e in tree.iter_entries_by_dir()]
        self.assertEqual(['', 'a', 'f', 'a/b', 'a/d', 'a/b/c', 'a/d/e', 'f/g'],
                         output_order)


class TestIterChildEntries(TestCaseWithTree):

    def test_iteration_order(self):
        work_tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/b/', 'a/b/c', 'a/d/', 'a/d/e', 'f/', 'f/g'])
        work_tree.add(['a', 'a/b', 'a/b/c', 'a/d', 'a/d/e', 'f', 'f/g'])
        tree = self._convert_tree(work_tree)
        output = [e.name for e in
            tree.iter_child_entries(tree.get_root_id())]
        self.assertEqual(set(['a', 'f']), set(output))
        output = [e.name for e in
            tree.iter_child_entries(tree.path2id('a'))]
        self.assertEqual(set(['b', 'd']), set(output))

    def test_does_not_exist(self):
        work_tree = self.make_branch_and_tree('.')
        self.build_tree(['a/'])
        work_tree.add(['a'])
        tree = self._convert_tree(work_tree)
        self.assertRaises(errors.NoSuchId, lambda:
            list(tree.iter_child_entries('unknown')))


class TestHasId(TestCaseWithTree):

    def test_has_id(self):
        work_tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/file'])
        work_tree.add('file', 'file-id')
        tree = self._convert_tree(work_tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertTrue(tree.has_id('file-id'))
        self.assertFalse(tree.has_id('dir-id'))

    def test___contains__(self):
        work_tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/file'])
        work_tree.add('file', 'file-id')
        tree = self._convert_tree(work_tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertTrue(
            self.applyDeprecated(
                deprecated_in((2, 4, 0)),
                tree.__contains__, 'file-id'))
        self.assertFalse(
            self.applyDeprecated(
                deprecated_in((2, 4, 0)),
                tree.__contains__, 'dir-id'))


class TestExtras(TestCaseWithTree):

    def test_extras(self):
        work_tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/file', 'tree/versioned-file'])
        work_tree.add(['file', 'versioned-file'])
        work_tree.commit('add files')
        work_tree.remove('file')
        tree = self._convert_tree(work_tree)
        if isinstance(tree,
                      (revisiontree.RevisionTree,
                       workingtree_4.DirStateRevisionTree)):
            expected = []
        else:
            expected = ['file']
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual(expected, list(tree.extras()))


class TestGetFileSha1(TestCaseWithTree):

    def test_get_file_sha1(self):
        work_tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/file', 'file content')])
        work_tree.add('file', 'file-id')
        tree = self._convert_tree(work_tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        expected = osutils.sha_strings('file content')
        self.assertEqual(expected, tree.get_file_sha1('file-id'))


class TestGetFileVerifier(TestCaseWithTree):

    def test_get_file_verifier(self):
        work_tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([
            ('tree/file1', 'file content'),
            ('tree/file2', 'file content')])
        work_tree.add(['file1', 'file2'], ['file-id-1', 'file-id-2'])
        tree = self._convert_tree(work_tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        (kind, data) = tree.get_file_verifier('file-id-1')
        self.assertEqual(
            tree.get_file_verifier('file-id-1'),
            tree.get_file_verifier('file-id-2'))
        if kind == "SHA1":
            expected = osutils.sha_strings('file content')
            self.assertEqual(expected, data)


class TestHasVersionedDirectories(TestCaseWithTree):

    def test_has_versioned_directories(self):
        work_tree = self.make_branch_and_tree('tree')
        tree = self._convert_tree(work_tree)
        self.assertSubset([tree.has_versioned_directories()], (True, False))
