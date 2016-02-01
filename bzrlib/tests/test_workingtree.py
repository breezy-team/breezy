# Copyright (C) 2005-2012, 2016 Canonical Ltd
# Authors:  Robert Collins <robert.collins@canonical.com>
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
    bzrdir,
    conflicts,
    errors,
    transport,
    workingtree,
    workingtree_3,
    workingtree_4,
    )
from bzrlib.lock import write_locked
from bzrlib.lockdir import LockDir
from bzrlib.mutabletree import needs_tree_write_lock
from bzrlib.tests import TestCase, TestCaseWithTransport, TestSkipped
from bzrlib.workingtree import (
    TreeEntry,
    TreeDirectory,
    TreeFile,
    TreeLink,
    )


class TestTreeDirectory(TestCaseWithTransport):

    def test_kind_character(self):
        self.assertEqual(TreeDirectory().kind_character(), '/')


class TestTreeEntry(TestCaseWithTransport):

    def test_kind_character(self):
        self.assertEqual(TreeEntry().kind_character(), '???')


class TestTreeFile(TestCaseWithTransport):

    def test_kind_character(self):
        self.assertEqual(TreeFile().kind_character(), '')


class TestTreeLink(TestCaseWithTransport):

    def test_kind_character(self):
        self.assertEqual(TreeLink().kind_character(), '')


class TestDefaultFormat(TestCaseWithTransport):

    def test_get_set_default_format(self):
        old_format = workingtree.format_registry.get_default()
        # default is 6
        self.assertTrue(isinstance(old_format, workingtree_4.WorkingTreeFormat6))
        workingtree.format_registry.set_default(SampleTreeFormat())
        try:
            # the default branch format is used by the meta dir format
            # which is not the default bzrdir format at this point
            dir = bzrdir.BzrDirMetaFormat1().initialize('.')
            dir.create_repository()
            dir.create_branch()
            result = dir.create_workingtree()
            self.assertEqual(result, 'A tree')
        finally:
            workingtree.format_registry.set_default(old_format)
        self.assertEqual(old_format, workingtree.format_registry.get_default())

    def test_from_string(self):
        self.assertIsInstance(
            SampleTreeFormat.from_string("Sample tree format."),
            SampleTreeFormat)
        self.assertRaises(AssertionError,
            SampleTreeFormat.from_string, "Different format string.")

    def test_get_set_default_format_by_key(self):
        old_format = workingtree.format_registry.get_default()
        # default is 6
        format = SampleTreeFormat()
        workingtree.format_registry.register(format)
        self.addCleanup(workingtree.format_registry.remove, format)
        self.assertTrue(isinstance(old_format, workingtree_4.WorkingTreeFormat6))
        workingtree.format_registry.set_default_key(format.get_format_string())
        try:
            # the default branch format is used by the meta dir format
            # which is not the default bzrdir format at this point
            dir = bzrdir.BzrDirMetaFormat1().initialize('.')
            dir.create_repository()
            dir.create_branch()
            result = dir.create_workingtree()
            self.assertEqual(result, 'A tree')
        finally:
            workingtree.format_registry.set_default_key(
                old_format.get_format_string())
        self.assertEqual(old_format, workingtree.format_registry.get_default())

    def test_open(self):
        tree = self.make_branch_and_tree('.')
        open_direct = workingtree.WorkingTree.open('.')
        self.assertEqual(tree.basedir, open_direct.basedir)
        open_no_args = workingtree.WorkingTree.open()
        self.assertEqual(tree.basedir, open_no_args.basedir)

    def test_open_containing(self):
        tree = self.make_branch_and_tree('.')
        open_direct, relpath = workingtree.WorkingTree.open_containing('.')
        self.assertEqual(tree.basedir, open_direct.basedir)
        self.assertEqual('', relpath)
        open_no_args, relpath = workingtree.WorkingTree.open_containing()
        self.assertEqual(tree.basedir, open_no_args.basedir)
        self.assertEqual('', relpath)
        open_subdir, relpath = workingtree.WorkingTree.open_containing('subdir')
        self.assertEqual(tree.basedir, open_subdir.basedir)
        self.assertEqual('subdir', relpath)


class SampleTreeFormat(workingtree.WorkingTreeFormatMetaDir):
    """A sample format

    this format is initializable, unsupported to aid in testing the
    open and open_downlevel routines.
    """

    @classmethod
    def get_format_string(cls):
        """See WorkingTreeFormat.get_format_string()."""
        return "Sample tree format."

    def initialize(self, a_bzrdir, revision_id=None, from_branch=None,
                   accelerator_tree=None, hardlink=False):
        """Sample branches cannot be created."""
        t = a_bzrdir.get_workingtree_transport(self)
        t.put_bytes('format', self.get_format_string())
        return 'A tree'

    def is_supported(self):
        return False

    def open(self, transport, _found=False):
        return "opened tree."


class SampleExtraTreeFormat(workingtree.WorkingTreeFormat):
    """A sample format that does not support use in a metadir.

    """

    def get_format_string(self):
        # Not usable in a metadir, so no format string
        return None

    def initialize(self, a_bzrdir, revision_id=None, from_branch=None,
                   accelerator_tree=None, hardlink=False):
        raise NotImplementedError(self.initialize)

    def is_supported(self):
        return False

    def open(self, transport, _found=False):
        raise NotImplementedError(self.open)


class TestWorkingTreeFormat(TestCaseWithTransport):
    """Tests for the WorkingTreeFormat facility."""

    def test_find_format_string(self):
        # is the right format object found for a working tree?
        branch = self.make_branch('branch')
        self.assertRaises(errors.NoWorkingTree,
            workingtree.WorkingTreeFormatMetaDir.find_format_string, branch.bzrdir)
        transport = branch.bzrdir.get_workingtree_transport(None)
        transport.mkdir('.')
        transport.put_bytes("format", "some format name")
        # The format does not have to be known by Bazaar,
        # find_format_string just retrieves the name
        self.assertEqual("some format name",
            workingtree.WorkingTreeFormatMetaDir.find_format_string(branch.bzrdir))

    def test_find_format(self):
        # is the right format object found for a working tree?
        # create a branch with a few known format objects.
        self.build_tree(["foo/", "bar/"])
        def check_format(format, url):
            dir = format._matchingbzrdir.initialize(url)
            dir.create_repository()
            dir.create_branch()
            format.initialize(dir)
            t = transport.get_transport(url)
            found_format = workingtree.WorkingTreeFormatMetaDir.find_format(dir)
            self.assertIsInstance(found_format, format.__class__)
        check_format(workingtree_3.WorkingTreeFormat3(), "bar")

    def test_find_format_no_tree(self):
        dir = bzrdir.BzrDirMetaFormat1().initialize('.')
        self.assertRaises(errors.NoWorkingTree,
                          workingtree.WorkingTreeFormatMetaDir.find_format,
                          dir)

    def test_find_format_unknown_format(self):
        dir = bzrdir.BzrDirMetaFormat1().initialize('.')
        dir.create_repository()
        dir.create_branch()
        SampleTreeFormat().initialize(dir)
        self.assertRaises(errors.UnknownFormatError,
                          workingtree.WorkingTreeFormatMetaDir.find_format,
                          dir)

    def test_find_format_with_features(self):
        tree = self.make_branch_and_tree('.', format='2a')
        tree.update_feature_flags({"name": "necessity"})
        found_format = workingtree.WorkingTreeFormatMetaDir.find_format(
            tree.bzrdir)
        self.assertIsInstance(found_format, workingtree.WorkingTreeFormat)
        self.assertEqual(found_format.features.get("name"), "necessity")
        self.assertRaises(errors.MissingFeature, found_format.check_support_status,
            True)
        self.addCleanup(workingtree.WorkingTreeFormatMetaDir.unregister_feature,
            "name")
        workingtree.WorkingTreeFormatMetaDir.register_feature("name")
        found_format.check_support_status(True)


class TestWorkingTreeIterEntriesByDir_wSubtrees(TestCaseWithTransport):

    def make_simple_tree(self):
        tree = self.make_branch_and_tree('tree', format='development-subtree')
        self.build_tree(['tree/a/', 'tree/a/b/', 'tree/a/b/c'])
        tree.set_root_id('root-id')
        tree.add(['a', 'a/b', 'a/b/c'], ['a-id', 'b-id', 'c-id'])
        tree.commit('initial')
        return tree

    def test_just_directory(self):
        tree = self.make_simple_tree()
        self.assertEqual([('directory', 'root-id'),
                          ('directory', 'a-id'),
                          ('directory', 'b-id'),
                          ('file', 'c-id')],
                         [(ie.kind, ie.file_id)
                          for path, ie in tree.iter_entries_by_dir()])
        subtree = self.make_branch_and_tree('tree/a/b')
        self.assertEqual([('tree-reference', 'b-id')],
                         [(ie.kind, ie.file_id)
                          for path, ie in tree.iter_entries_by_dir(['b-id'])])

    def test_direct_subtree(self):
        tree = self.make_simple_tree()
        subtree = self.make_branch_and_tree('tree/a/b')
        self.assertEqual([('directory', 'root-id'),
                          ('directory', 'a-id'),
                          ('tree-reference', 'b-id')],
                         [(ie.kind, ie.file_id)
                          for path, ie in tree.iter_entries_by_dir()])

    def test_indirect_subtree(self):
        tree = self.make_simple_tree()
        subtree = self.make_branch_and_tree('tree/a')
        self.assertEqual([('directory', 'root-id'),
                          ('tree-reference', 'a-id')],
                         [(ie.kind, ie.file_id)
                          for path, ie in tree.iter_entries_by_dir()])


class TestWorkingTreeFormatRegistry(TestCase):

    def setUp(self):
        super(TestWorkingTreeFormatRegistry, self).setUp()
        self.registry = workingtree.WorkingTreeFormatRegistry()

    def test_register_unregister_format(self):
        format = SampleTreeFormat()
        self.registry.register(format)
        self.assertEqual(format, self.registry.get("Sample tree format."))
        self.registry.remove(format)
        self.assertRaises(KeyError, self.registry.get, "Sample tree format.")

    def test_get_all(self):
        format = SampleTreeFormat()
        self.assertEqual([], self.registry._get_all())
        self.registry.register(format)
        self.assertEqual([format], self.registry._get_all())

    def test_register_extra(self):
        format = SampleExtraTreeFormat()
        self.assertEqual([], self.registry._get_all())
        self.registry.register_extra(format)
        self.assertEqual([format], self.registry._get_all())

    def test_register_extra_lazy(self):
        self.assertEqual([], self.registry._get_all())
        self.registry.register_extra_lazy("bzrlib.tests.test_workingtree",
            "SampleExtraTreeFormat")
        formats = self.registry._get_all()
        self.assertEqual(1, len(formats))
        self.assertIsInstance(formats[0], SampleExtraTreeFormat)


class TestWorkingTreeFormat3(TestCaseWithTransport):
    """Tests specific to WorkingTreeFormat3."""

    def test_disk_layout(self):
        control = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        control.create_repository()
        control.create_branch()
        tree = workingtree_3.WorkingTreeFormat3().initialize(control)
        # we want:
        # format 'Bazaar-NG Working Tree format 3'
        # inventory = blank inventory
        # pending-merges = ''
        # stat-cache = ??
        # no inventory.basis yet
        t = control.get_workingtree_transport(None)
        self.assertEqualDiff('Bazaar-NG Working Tree format 3',
                             t.get('format').read())
        self.assertEqualDiff(t.get('inventory').read(),
                              '<inventory format="5">\n'
                              '</inventory>\n',
                             )
        self.assertEqualDiff('### bzr hashcache v5\n',
                             t.get('stat-cache').read())
        self.assertFalse(t.has('inventory.basis'))
        # no last-revision file means 'None' or 'NULLREVISION'
        self.assertFalse(t.has('last-revision'))
        # TODO RBC 20060210 do a commit, check the inventory.basis is created
        # correctly and last-revision file becomes present.

    def test_uses_lockdir(self):
        """WorkingTreeFormat3 uses its own LockDir:

            - lock is a directory
            - when the WorkingTree is locked, LockDir can see that
        """
        t = self.get_transport()
        url = self.get_url()
        dir = bzrdir.BzrDirMetaFormat1().initialize(url)
        repo = dir.create_repository()
        branch = dir.create_branch()
        try:
            tree = workingtree_3.WorkingTreeFormat3().initialize(dir)
        except errors.NotLocalUrl:
            raise TestSkipped('Not a local URL')
        self.assertIsDirectory('.bzr', t)
        self.assertIsDirectory('.bzr/checkout', t)
        self.assertIsDirectory('.bzr/checkout/lock', t)
        our_lock = LockDir(t, '.bzr/checkout/lock')
        self.assertEqual(our_lock.peek(), None)
        tree.lock_write()
        self.assertTrue(our_lock.peek())
        tree.unlock()
        self.assertEqual(our_lock.peek(), None)

    def test_missing_pending_merges(self):
        control = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        control.create_repository()
        control.create_branch()
        tree = workingtree_3.WorkingTreeFormat3().initialize(control)
        tree._transport.delete("pending-merges")
        self.assertEqual([], tree.get_parent_ids())


class InstrumentedTree(object):
    """A instrumented tree to check the needs_tree_write_lock decorator."""

    def __init__(self):
        self._locks = []

    def lock_tree_write(self):
        self._locks.append('t')

    @needs_tree_write_lock
    def method_with_tree_write_lock(self, *args, **kwargs):
        """A lock_tree_write decorated method that returns its arguments."""
        return args, kwargs

    @needs_tree_write_lock
    def method_that_raises(self):
        """This method causes an exception when called with parameters.

        This allows the decorator code to be checked - it should still call
        unlock.
        """

    def unlock(self):
        self._locks.append('u')


class TestInstrumentedTree(TestCase):

    def test_needs_tree_write_lock(self):
        """@needs_tree_write_lock should be semantically transparent."""
        tree = InstrumentedTree()
        self.assertEqual(
            'method_with_tree_write_lock',
            tree.method_with_tree_write_lock.__name__)
        self.assertDocstring(
            "A lock_tree_write decorated method that returns its arguments.",
            tree.method_with_tree_write_lock)
        args = (1, 2, 3)
        kwargs = {'a':'b'}
        result = tree.method_with_tree_write_lock(1,2,3, a='b')
        self.assertEqual((args, kwargs), result)
        self.assertEqual(['t', 'u'], tree._locks)
        self.assertRaises(TypeError, tree.method_that_raises, 'foo')
        self.assertEqual(['t', 'u', 't', 'u'], tree._locks)


class TestRevert(TestCaseWithTransport):

    def test_revert_conflicts_recursive(self):
        this_tree = self.make_branch_and_tree('this-tree')
        self.build_tree_contents([('this-tree/foo/',),
                                  ('this-tree/foo/bar', 'bar')])
        this_tree.add(['foo', 'foo/bar'])
        this_tree.commit('created foo/bar')
        other_tree = this_tree.bzrdir.sprout('other-tree').open_workingtree()
        self.build_tree_contents([('other-tree/foo/bar', 'baz')])
        other_tree.commit('changed bar')
        self.build_tree_contents([('this-tree/foo/bar', 'qux')])
        this_tree.commit('changed qux')
        this_tree.merge_from_branch(other_tree.branch)
        self.assertEqual(1, len(this_tree.conflicts()))
        this_tree.revert(['foo'])
        self.assertEqual(0, len(this_tree.conflicts()))


class TestAutoResolve(TestCaseWithTransport):

    def test_auto_resolve(self):
        base = self.make_branch_and_tree('base')
        self.build_tree_contents([('base/hello', 'Hello')])
        base.add('hello', 'hello_id')
        base.commit('Hello')
        other = base.bzrdir.sprout('other').open_workingtree()
        self.build_tree_contents([('other/hello', 'hELLO')])
        other.commit('Case switch')
        this = base.bzrdir.sprout('this').open_workingtree()
        self.assertPathExists('this/hello')
        self.build_tree_contents([('this/hello', 'Hello World')])
        this.commit('Add World')
        this.merge_from_branch(other.branch)
        self.assertEqual([conflicts.TextConflict('hello', 'hello_id')],
                         this.conflicts())
        this.auto_resolve()
        self.assertEqual([conflicts.TextConflict('hello', 'hello_id')],
                         this.conflicts())
        self.build_tree_contents([('this/hello', '<<<<<<<')])
        this.auto_resolve()
        self.assertEqual([conflicts.TextConflict('hello', 'hello_id')],
                         this.conflicts())
        self.build_tree_contents([('this/hello', '=======')])
        this.auto_resolve()
        self.assertEqual([conflicts.TextConflict('hello', 'hello_id')],
                         this.conflicts())
        self.build_tree_contents([('this/hello', '\n>>>>>>>')])
        remaining, resolved = this.auto_resolve()
        self.assertEqual([conflicts.TextConflict('hello', 'hello_id')],
                         this.conflicts())
        self.assertEqual([], resolved)
        self.build_tree_contents([('this/hello', 'hELLO wORLD')])
        remaining, resolved = this.auto_resolve()
        self.assertEqual([], this.conflicts())
        self.assertEqual([conflicts.TextConflict('hello', 'hello_id')],
                         resolved)
        self.assertPathDoesNotExist('this/hello.BASE')

    def test_auto_resolve_dir(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/hello/'])
        tree.add('hello', 'hello-id')
        file_conflict = conflicts.TextConflict('file', 'hello-id')
        tree.set_conflicts(conflicts.ConflictList([file_conflict]))
        tree.auto_resolve()


class TestFindTrees(TestCaseWithTransport):

    def test_find_trees(self):
        self.make_branch_and_tree('foo')
        self.make_branch_and_tree('foo/bar')
        # Sticking a tree inside a control dir is heinous, so let's skip it
        self.make_branch_and_tree('foo/.bzr/baz')
        self.make_branch('qux')
        trees = workingtree.WorkingTree.find_trees('.')
        self.assertEqual(2, len(list(trees)))


class TestStoredUncommitted(TestCaseWithTransport):

    def store_uncommitted(self):
        tree = self.make_branch_and_tree('tree')
        tree.commit('get root in there')
        self.build_tree_contents([('tree/file', 'content')])
        tree.add('file', 'file-id')
        tree.store_uncommitted()
        return tree

    def test_store_uncommitted(self):
        self.store_uncommitted()
        self.assertPathDoesNotExist('tree/file')

    def test_store_uncommitted_no_change(self):
        tree = self.make_branch_and_tree('tree')
        tree.commit('get root in there')
        tree.store_uncommitted()
        self.assertIs(None, tree.branch.get_unshelver(tree))

    def test_restore_uncommitted(self):
        with write_locked(self.store_uncommitted()) as tree:
            tree.restore_uncommitted()
            self.assertPathExists('tree/file')
            self.assertIs(None, tree.branch.get_unshelver(tree))

    def test_restore_uncommitted_none(self):
        tree = self.make_branch_and_tree('tree')
        tree.restore_uncommitted()
