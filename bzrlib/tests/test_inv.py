# Copyright (C) 2005, 2006, 2007, 2008, 2009 Canonical Ltd
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
    chk_map,
    groupcompress,
    bzrdir,
    errors,
    inventory,
    osutils,
    repository,
    revision,
    tests,
    )
from bzrlib.inventory import (CHKInventory, Inventory, ROOT_ID, InventoryFile,
    InventoryDirectory, InventoryEntry, TreeReference)
from bzrlib.tests import (
    TestCase,
    TestCaseWithTransport,
    condition_isinstance,
    multiply_tests,
    split_suite_by_condition,
    )
from bzrlib.tests.per_workingtree import workingtree_formats


def load_tests(standard_tests, module, loader):
    """Parameterise some inventory tests."""
    to_adapt, result = split_suite_by_condition(standard_tests,
        condition_isinstance(TestDeltaApplication))
    scenarios = [
        ('Inventory', {'apply_delta':apply_inventory_Inventory}),
        ]
    # Working tree basis delta application
    # Repository add_inv_by_delta.
    # Reduce form of the per_repository test logic - that logic needs to be
    # be able to get /just/ repositories whereas these tests are fine with
    # just creating trees.
    formats = set()
    for _, format in repository.format_registry.iteritems():
        scenarios.append((str(format.__name__), {
            'apply_delta':apply_inventory_Repository_add_inventory_by_delta,
            'format':format}))
    for format in workingtree_formats():
        scenarios.append(
            (str(format.__class__.__name__) + ".update_basis_by_delta", {
            'apply_delta':apply_inventory_WT_basis,
            'format':format}))
        scenarios.append(
            (str(format.__class__.__name__) + ".apply_inventory_delta", {
            'apply_delta':apply_inventory_WT,
            'format':format}))
    return multiply_tests(to_adapt, scenarios, result)


def create_texts_for_inv(repo, inv):
    for path, ie in inv.iter_entries():
        if ie.text_size:
            lines = ['a' * ie.text_size]
        else:
            lines = []
        repo.texts.add_lines((ie.file_id, ie.revision), [], lines)
    
def apply_inventory_Inventory(self, basis, delta):
    """Apply delta to basis and return the result.
    
    :param basis: An inventory to be used as the basis.
    :param delta: The inventory delta to apply:
    :return: An inventory resulting from the application.
    """
    basis.apply_delta(delta)
    return basis


def apply_inventory_WT(self, basis, delta):
    """Apply delta to basis and return the result.

    This sets the tree state to be basis, and then calls apply_inventory_delta.
    
    :param basis: An inventory to be used as the basis.
    :param delta: The inventory delta to apply:
    :return: An inventory resulting from the application.
    """
    control = self.make_bzrdir('tree', format=self.format._matchingbzrdir)
    control.create_repository()
    control.create_branch()
    tree = self.format.initialize(control)
    tree.lock_write()
    try:
        tree._write_inventory(basis)
    finally:
        tree.unlock()
    # Fresh object, reads disk again.
    tree = tree.bzrdir.open_workingtree()
    tree.lock_write()
    try:
        tree.apply_inventory_delta(delta)
    finally:
        tree.unlock()
    # reload tree - ensure we get what was written.
    tree = tree.bzrdir.open_workingtree()
    tree.lock_read()
    self.addCleanup(tree.unlock)
    # One could add 'tree._validate' here but that would cause 'early' failues 
    # as far as higher level code is concerned. Possibly adding an
    # expect_fail parameter to this function and if that is False then do a
    # validate call.
    return tree.inventory


def apply_inventory_WT_basis(self, basis, delta):
    """Apply delta to basis and return the result.

    This sets the parent and then calls update_basis_by_delta.
    It also puts the basis in the repository under both 'basis' and 'result' to
    allow safety checks made by the WT to succeed, and finally ensures that all
    items in the delta with a new path are present in the WT before calling
    update_basis_by_delta.
    
    :param basis: An inventory to be used as the basis.
    :param delta: The inventory delta to apply:
    :return: An inventory resulting from the application.
    """
    control = self.make_bzrdir('tree', format=self.format._matchingbzrdir)
    control.create_repository()
    control.create_branch()
    tree = self.format.initialize(control)
    tree.lock_write()
    try:
        repo = tree.branch.repository
        repo.start_write_group()
        try:
            rev = revision.Revision('basis', timestamp=0, timezone=None,
                message="", committer="foo@example.com")
            basis.revision_id = 'basis'
            create_texts_for_inv(tree.branch.repository, basis)
            repo.add_revision('basis', rev, basis)
            # Add a revision for the result, with the basis content - 
            # update_basis_by_delta doesn't check that the delta results in
            # result, and we want inconsistent deltas to get called on the
            # tree, or else the code isn't actually checked.
            rev = revision.Revision('result', timestamp=0, timezone=None,
                message="", committer="foo@example.com")
            basis.revision_id = 'result'
            repo.add_revision('result', rev, basis)
            repo.commit_write_group()
        except:
            repo.abort_write_group()
            raise
        # Set the basis state as the trees current state
        tree._write_inventory(basis)
        # This reads basis from the repo and puts it into the tree's local
        # cache, if it has one.
        tree.set_parent_ids(['basis'])
        paths = {}
        parents = set()
        for old, new, id, entry in delta:
            if None in (new, entry):
                continue
            paths[new] = (entry.file_id, entry.kind)
            parents.add(osutils.dirname(new))
        parents = osutils.minimum_path_selection(parents)
        parents.discard('')
        # Put place holders in the tree to permit adding the other entries.
        for pos, parent in enumerate(parents):
            if not tree.path2id(parent):
                # add a synthetic directory in the tree so we can can put the
                # tree0 entries in place for dirstate.
                tree.add([parent], ["id%d" % pos], ["directory"])
        if paths:
            # Many deltas may cause this mini-apply to fail, but we want to see what
            # the delta application code says, not the prep that we do to deal with 
            # limitations of dirstate's update_basis code.
            for path, (file_id, kind) in sorted(paths.items()):
                try:
                    tree.add([path], [file_id], [kind])
                except (KeyboardInterrupt, SystemExit):
                    raise
                except:
                    pass
    finally:
        tree.unlock()
    # Fresh lock, reads disk again.
    tree.lock_write()
    try:
        tree.update_basis_by_delta('result', delta)
    finally:
        tree.unlock()
    # reload tree - ensure we get what was written.
    tree = tree.bzrdir.open_workingtree()
    basis_tree = tree.basis_tree()
    basis_tree.lock_read()
    self.addCleanup(basis_tree.unlock)
    # Note, that if the tree does not have a local cache, the trick above of
    # setting the result as the basis, will come back to bite us. That said,
    # all the implementations in bzr do have a local cache.
    return basis_tree.inventory


def apply_inventory_Repository_add_inventory_by_delta(self, basis, delta):
    """Apply delta to basis and return the result.
    
    This inserts basis as a whole inventory and then uses
    add_inventory_by_delta to add delta.

    :param basis: An inventory to be used as the basis.
    :param delta: The inventory delta to apply:
    :return: An inventory resulting from the application.
    """
    format = self.format()
    control = self.make_bzrdir('tree', format=format._matchingbzrdir)
    repo = format.initialize(control)
    repo.lock_write()
    try:
        repo.start_write_group()
        try:
            rev = revision.Revision('basis', timestamp=0, timezone=None,
                message="", committer="foo@example.com")
            basis.revision_id = 'basis'
            create_texts_for_inv(repo, basis)
            repo.add_revision('basis', rev, basis)
            repo.commit_write_group()
        except:
            repo.abort_write_group()
            raise
    finally:
        repo.unlock()
    repo.lock_write()
    try:
        repo.start_write_group()
        try:
            inv_sha1 = repo.add_inventory_by_delta('basis', delta,
                'result', ['basis'])
        except:
            repo.abort_write_group()
            raise
        else:
            repo.commit_write_group()
    finally:
        repo.unlock()
    # Fresh lock, reads disk again.
    repo = repo.bzrdir.open_repository()
    repo.lock_read()
    self.addCleanup(repo.unlock)
    return repo.get_inventory('result')


class TestInventoryUpdates(TestCase):

    def test_creation_from_root_id(self):
        # iff a root id is passed to the constructor, a root directory is made
        inv = inventory.Inventory(root_id='tree-root')
        self.assertNotEqual(None, inv.root)
        self.assertEqual('tree-root', inv.root.file_id)

    def test_add_path_of_root(self):
        # if no root id is given at creation time, there is no root directory
        inv = inventory.Inventory(root_id=None)
        self.assertIs(None, inv.root)
        # add a root entry by adding its path
        ie = inv.add_path("", "directory", "my-root")
        ie.revision = 'test-rev'
        self.assertEqual("my-root", ie.file_id)
        self.assertIs(ie, inv.root)

    def test_add_path(self):
        inv = inventory.Inventory(root_id='tree_root')
        ie = inv.add_path('hello', 'file', 'hello-id')
        self.assertEqual('hello-id', ie.file_id)
        self.assertEqual('file', ie.kind)

    def test_copy(self):
        """Make sure copy() works and creates a deep copy."""
        inv = inventory.Inventory(root_id='some-tree-root')
        ie = inv.add_path('hello', 'file', 'hello-id')
        inv2 = inv.copy()
        inv.root.file_id = 'some-new-root'
        ie.name = 'file2'
        self.assertEqual('some-tree-root', inv2.root.file_id)
        self.assertEqual('hello', inv2['hello-id'].name)

    def test_copy_empty(self):
        """Make sure an empty inventory can be copied."""
        inv = inventory.Inventory(root_id=None)
        inv2 = inv.copy()
        self.assertIs(None, inv2.root)

    def test_copy_copies_root_revision(self):
        """Make sure the revision of the root gets copied."""
        inv = inventory.Inventory(root_id='someroot')
        inv.root.revision = 'therev'
        inv2 = inv.copy()
        self.assertEquals('someroot', inv2.root.file_id)
        self.assertEquals('therev', inv2.root.revision)

    def test_create_tree_reference(self):
        inv = inventory.Inventory('tree-root-123')
        inv.add(TreeReference('nested-id', 'nested', parent_id='tree-root-123',
                              revision='rev', reference_revision='rev2'))

    def test_error_encoding(self):
        inv = inventory.Inventory('tree-root')
        inv.add(InventoryFile('a-id', u'\u1234', 'tree-root'))
        e = self.assertRaises(errors.InconsistentDelta, inv.add,
            InventoryFile('b-id', u'\u1234', 'tree-root'))
        self.assertContainsRe(str(e), r'\\u1234')

    def test_add_recursive(self):
        parent = InventoryDirectory('src-id', 'src', 'tree-root')
        child = InventoryFile('hello-id', 'hello.c', 'src-id')
        parent.children[child.file_id] = child
        inv = inventory.Inventory('tree-root')
        inv.add(parent)
        self.assertEqual('src/hello.c', inv.id2path('hello-id'))



class TestDeltaApplication(TestCaseWithTransport):
 
    def get_empty_inventory(self, reference_inv=None):
        """Get an empty inventory.

        Note that tests should not depend on the revision of the root for
        setting up test conditions, as it has to be flexible to accomodate non
        rich root repositories.

        :param reference_inv: If not None, get the revision for the root from
            this inventory. This is useful for dealing with older repositories
            that routinely discarded the root entry data. If None, the root's
            revision is set to 'basis'.
        """
        inv = inventory.Inventory()
        if reference_inv is not None:
            inv.root.revision = reference_inv.root.revision
        else:
            inv.root.revision = 'basis'
        return inv

    def test_empty_delta(self):
        inv = self.get_empty_inventory()
        delta = []
        inv = self.apply_delta(self, inv, delta)
        inv2 = self.get_empty_inventory(inv)
        self.assertEqual([], inv2._make_delta(inv))

    def test_None_file_id(self):
        inv = self.get_empty_inventory()
        dir1 = inventory.InventoryDirectory(None, 'dir1', inv.root.file_id)
        dir1.revision = 'result'
        delta = [(None, u'dir1', None, dir1)]
        self.assertRaises(errors.InconsistentDelta, self.apply_delta, self,
            inv, delta)

    def test_unicode_file_id(self):
        inv = self.get_empty_inventory()
        dir1 = inventory.InventoryDirectory(u'dirid', 'dir1', inv.root.file_id)
        dir1.revision = 'result'
        delta = [(None, u'dir1', dir1.file_id, dir1)]
        self.assertRaises(errors.InconsistentDelta, self.apply_delta, self,
            inv, delta)

    def test_repeated_file_id(self):
        inv = self.get_empty_inventory()
        file1 = inventory.InventoryFile('id', 'path1', inv.root.file_id)
        file1.revision = 'result'
        file1.text_size = 0
        file1.text_sha1 = ""
        file2 = inventory.InventoryFile('id', 'path2', inv.root.file_id)
        file2.revision = 'result'
        file2.text_size = 0
        file2.text_sha1 = ""
        delta = [(None, u'path1', 'id', file1), (None, u'path2', 'id', file2)]
        self.assertRaises(errors.InconsistentDelta, self.apply_delta, self,
            inv, delta)

    def test_repeated_new_path(self):
        inv = self.get_empty_inventory()
        file1 = inventory.InventoryFile('id1', 'path', inv.root.file_id)
        file1.revision = 'result'
        file1.text_size = 0
        file1.text_sha1 = ""
        file2 = inventory.InventoryFile('id2', 'path', inv.root.file_id)
        file2.revision = 'result'
        file2.text_size = 0
        file2.text_sha1 = ""
        delta = [(None, u'path', 'id1', file1), (None, u'path', 'id2', file2)]
        self.assertRaises(errors.InconsistentDelta, self.apply_delta, self,
            inv, delta)

    def test_repeated_old_path(self):
        inv = self.get_empty_inventory()
        file1 = inventory.InventoryFile('id1', 'path', inv.root.file_id)
        file1.revision = 'result'
        file1.text_size = 0
        file1.text_sha1 = ""
        # We can't *create* a source inventory with the same path, but
        # a badly generated partial delta might claim the same source twice.
        # This would be buggy in two ways: the path is repeated in the delta,
        # And the path for one of the file ids doesn't match the source
        # location. Alternatively, we could have a repeated fileid, but that
        # is separately checked for.
        file2 = inventory.InventoryFile('id2', 'path2', inv.root.file_id)
        file2.revision = 'result'
        file2.text_size = 0
        file2.text_sha1 = ""
        inv.add(file1)
        inv.add(file2)
        delta = [(u'path', None, 'id1', None), (u'path', None, 'id2', None)]
        self.assertRaises(errors.InconsistentDelta, self.apply_delta, self,
            inv, delta)

    def test_mismatched_id_entry_id(self):
        inv = self.get_empty_inventory()
        file1 = inventory.InventoryFile('id1', 'path', inv.root.file_id)
        file1.revision = 'result'
        file1.text_size = 0
        file1.text_sha1 = ""
        delta = [(None, u'path', 'id', file1)]
        self.assertRaises(errors.InconsistentDelta, self.apply_delta, self,
            inv, delta)

    def test_mismatched_new_path_entry_None(self):
        inv = self.get_empty_inventory()
        delta = [(None, u'path', 'id', None)]
        self.assertRaises(errors.InconsistentDelta, self.apply_delta, self,
            inv, delta)

    def test_mismatched_new_path_None_entry(self):
        inv = self.get_empty_inventory()
        file1 = inventory.InventoryFile('id1', 'path', inv.root.file_id)
        file1.revision = 'result'
        file1.text_size = 0
        file1.text_sha1 = ""
        delta = [(u"path", None, 'id1', file1)]
        self.assertRaises(errors.InconsistentDelta, self.apply_delta, self,
            inv, delta)

    def test_parent_is_not_directory(self):
        inv = self.get_empty_inventory()
        file1 = inventory.InventoryFile('id1', 'path', inv.root.file_id)
        file1.revision = 'result'
        file1.text_size = 0
        file1.text_sha1 = ""
        file2 = inventory.InventoryFile('id2', 'path2', 'id1')
        file2.revision = 'result'
        file2.text_size = 0
        file2.text_sha1 = ""
        inv.add(file1)
        delta = [(None, u'path/path2', 'id2', file2)]
        self.assertRaises(errors.InconsistentDelta, self.apply_delta, self,
            inv, delta)

    def test_parent_is_missing(self):
        inv = self.get_empty_inventory()
        file2 = inventory.InventoryFile('id2', 'path2', 'missingparent')
        file2.revision = 'result'
        file2.text_size = 0
        file2.text_sha1 = ""
        delta = [(None, u'path/path2', 'id2', file2)]
        self.assertRaises(errors.InconsistentDelta, self.apply_delta, self,
            inv, delta)

    def test_new_parent_path_has_wrong_id(self):
        inv = self.get_empty_inventory()
        parent1 = inventory.InventoryDirectory('p-1', 'dir', inv.root.file_id)
        parent1.revision = 'result'
        parent2 = inventory.InventoryDirectory('p-2', 'dir2', inv.root.file_id)
        parent2.revision = 'result'
        file1 = inventory.InventoryFile('id', 'path', 'p-2')
        file1.revision = 'result'
        file1.text_size = 0
        file1.text_sha1 = ""
        inv.add(parent1)
        inv.add(parent2)
        # This delta claims that file1 is at dir/path, but actually its at
        # dir2/path if you follow the inventory parent structure.
        delta = [(None, u'dir/path', 'id', file1)]
        self.assertRaises(errors.InconsistentDelta, self.apply_delta, self,
            inv, delta)

    def test_old_parent_path_is_wrong(self):
        inv = self.get_empty_inventory()
        parent1 = inventory.InventoryDirectory('p-1', 'dir', inv.root.file_id)
        parent1.revision = 'result'
        parent2 = inventory.InventoryDirectory('p-2', 'dir2', inv.root.file_id)
        parent2.revision = 'result'
        file1 = inventory.InventoryFile('id', 'path', 'p-2')
        file1.revision = 'result'
        file1.text_size = 0
        file1.text_sha1 = ""
        inv.add(parent1)
        inv.add(parent2)
        inv.add(file1)
        # This delta claims that file1 was at dir/path, but actually it was at
        # dir2/path if you follow the inventory parent structure.
        delta = [(u'dir/path', None, 'id', None)]
        self.assertRaises(errors.InconsistentDelta, self.apply_delta, self,
            inv, delta)

    def test_old_parent_path_is_for_other_id(self):
        inv = self.get_empty_inventory()
        parent1 = inventory.InventoryDirectory('p-1', 'dir', inv.root.file_id)
        parent1.revision = 'result'
        parent2 = inventory.InventoryDirectory('p-2', 'dir2', inv.root.file_id)
        parent2.revision = 'result'
        file1 = inventory.InventoryFile('id', 'path', 'p-2')
        file1.revision = 'result'
        file1.text_size = 0
        file1.text_sha1 = ""
        file2 = inventory.InventoryFile('id2', 'path', 'p-1')
        file2.revision = 'result'
        file2.text_size = 0
        file2.text_sha1 = ""
        inv.add(parent1)
        inv.add(parent2)
        inv.add(file1)
        inv.add(file2)
        # This delta claims that file1 was at dir/path, but actually it was at
        # dir2/path if you follow the inventory parent structure. At dir/path
        # is another entry we should not delete.
        delta = [(u'dir/path', None, 'id', None)]
        self.assertRaises(errors.InconsistentDelta, self.apply_delta, self,
            inv, delta)

    def test_add_existing_id_new_path(self):
        inv = self.get_empty_inventory()
        parent1 = inventory.InventoryDirectory('p-1', 'dir1', inv.root.file_id)
        parent1.revision = 'result'
        parent2 = inventory.InventoryDirectory('p-1', 'dir2', inv.root.file_id)
        parent2.revision = 'result'
        inv.add(parent1)
        delta = [(None, u'dir2', 'p-1', parent2)]
        self.assertRaises(errors.InconsistentDelta, self.apply_delta, self,
            inv, delta)

    def test_add_new_id_existing_path(self):
        inv = self.get_empty_inventory()
        parent1 = inventory.InventoryDirectory('p-1', 'dir1', inv.root.file_id)
        parent1.revision = 'result'
        parent2 = inventory.InventoryDirectory('p-2', 'dir1', inv.root.file_id)
        parent2.revision = 'result'
        inv.add(parent1)
        delta = [(None, u'dir1', 'p-2', parent2)]
        self.assertRaises(errors.InconsistentDelta, self.apply_delta, self,
            inv, delta)

    def test_remove_dir_leaving_dangling_child(self):
        inv = self.get_empty_inventory()
        dir1 = inventory.InventoryDirectory('p-1', 'dir1', inv.root.file_id)
        dir1.revision = 'result'
        dir2 = inventory.InventoryDirectory('p-2', 'child1', 'p-1')
        dir2.revision = 'result'
        dir3 = inventory.InventoryDirectory('p-3', 'child2', 'p-1')
        dir3.revision = 'result'
        inv.add(dir1)
        inv.add(dir2)
        inv.add(dir3)
        delta = [(u'dir1', None, 'p-1', None),
            (u'dir1/child2', None, 'p-3', None)]
        self.assertRaises(errors.InconsistentDelta, self.apply_delta, self,
            inv, delta)


class TestInventory(TestCase):

    def test_is_root(self):
        """Ensure our root-checking code is accurate."""
        inv = inventory.Inventory('TREE_ROOT')
        self.assertTrue(inv.is_root('TREE_ROOT'))
        self.assertFalse(inv.is_root('booga'))
        inv.root.file_id = 'booga'
        self.assertFalse(inv.is_root('TREE_ROOT'))
        self.assertTrue(inv.is_root('booga'))
        # works properly even if no root is set
        inv.root = None
        self.assertFalse(inv.is_root('TREE_ROOT'))
        self.assertFalse(inv.is_root('booga'))


class TestInventoryEntry(TestCase):

    def test_file_kind_character(self):
        file = inventory.InventoryFile('123', 'hello.c', ROOT_ID)
        self.assertEqual(file.kind_character(), '')

    def test_dir_kind_character(self):
        dir = inventory.InventoryDirectory('123', 'hello.c', ROOT_ID)
        self.assertEqual(dir.kind_character(), '/')

    def test_link_kind_character(self):
        dir = inventory.InventoryLink('123', 'hello.c', ROOT_ID)
        self.assertEqual(dir.kind_character(), '')

    def test_dir_detect_changes(self):
        left = inventory.InventoryDirectory('123', 'hello.c', ROOT_ID)
        left.text_sha1 = 123
        left.executable = True
        left.symlink_target='foo'
        right = inventory.InventoryDirectory('123', 'hello.c', ROOT_ID)
        right.text_sha1 = 321
        right.symlink_target='bar'
        self.assertEqual((False, False), left.detect_changes(right))
        self.assertEqual((False, False), right.detect_changes(left))

    def test_file_detect_changes(self):
        left = inventory.InventoryFile('123', 'hello.c', ROOT_ID)
        left.text_sha1 = 123
        right = inventory.InventoryFile('123', 'hello.c', ROOT_ID)
        right.text_sha1 = 123
        self.assertEqual((False, False), left.detect_changes(right))
        self.assertEqual((False, False), right.detect_changes(left))
        left.executable = True
        self.assertEqual((False, True), left.detect_changes(right))
        self.assertEqual((False, True), right.detect_changes(left))
        right.text_sha1 = 321
        self.assertEqual((True, True), left.detect_changes(right))
        self.assertEqual((True, True), right.detect_changes(left))

    def test_symlink_detect_changes(self):
        left = inventory.InventoryLink('123', 'hello.c', ROOT_ID)
        left.text_sha1 = 123
        left.executable = True
        left.symlink_target='foo'
        right = inventory.InventoryLink('123', 'hello.c', ROOT_ID)
        right.text_sha1 = 321
        right.symlink_target='foo'
        self.assertEqual((False, False), left.detect_changes(right))
        self.assertEqual((False, False), right.detect_changes(left))
        left.symlink_target = 'different'
        self.assertEqual((True, False), left.detect_changes(right))
        self.assertEqual((True, False), right.detect_changes(left))

    def test_file_has_text(self):
        file = inventory.InventoryFile('123', 'hello.c', ROOT_ID)
        self.failUnless(file.has_text())

    def test_directory_has_text(self):
        dir = inventory.InventoryDirectory('123', 'hello.c', ROOT_ID)
        self.failIf(dir.has_text())

    def test_link_has_text(self):
        link = inventory.InventoryLink('123', 'hello.c', ROOT_ID)
        self.failIf(link.has_text())

    def test_make_entry(self):
        self.assertIsInstance(inventory.make_entry("file", "name", ROOT_ID),
            inventory.InventoryFile)
        self.assertIsInstance(inventory.make_entry("symlink", "name", ROOT_ID),
            inventory.InventoryLink)
        self.assertIsInstance(inventory.make_entry("directory", "name", ROOT_ID),
            inventory.InventoryDirectory)

    def test_make_entry_non_normalized(self):
        orig_normalized_filename = osutils.normalized_filename

        try:
            osutils.normalized_filename = osutils._accessible_normalized_filename
            entry = inventory.make_entry("file", u'a\u030a', ROOT_ID)
            self.assertEqual(u'\xe5', entry.name)
            self.assertIsInstance(entry, inventory.InventoryFile)

            osutils.normalized_filename = osutils._inaccessible_normalized_filename
            self.assertRaises(errors.InvalidNormalization,
                    inventory.make_entry, 'file', u'a\u030a', ROOT_ID)
        finally:
            osutils.normalized_filename = orig_normalized_filename


class TestDescribeChanges(TestCase):

    def test_describe_change(self):
        # we need to test the following change combinations:
        # rename
        # reparent
        # modify
        # gone
        # added
        # renamed/reparented and modified
        # change kind (perhaps can't be done yet?)
        # also, merged in combination with all of these?
        old_a = InventoryFile('a-id', 'a_file', ROOT_ID)
        old_a.text_sha1 = '123132'
        old_a.text_size = 0
        new_a = InventoryFile('a-id', 'a_file', ROOT_ID)
        new_a.text_sha1 = '123132'
        new_a.text_size = 0

        self.assertChangeDescription('unchanged', old_a, new_a)

        new_a.text_size = 10
        new_a.text_sha1 = 'abcabc'
        self.assertChangeDescription('modified', old_a, new_a)

        self.assertChangeDescription('added', None, new_a)
        self.assertChangeDescription('removed', old_a, None)
        # perhaps a bit questionable but seems like the most reasonable thing...
        self.assertChangeDescription('unchanged', None, None)

        # in this case it's both renamed and modified; show a rename and
        # modification:
        new_a.name = 'newfilename'
        self.assertChangeDescription('modified and renamed', old_a, new_a)

        # reparenting is 'renaming'
        new_a.name = old_a.name
        new_a.parent_id = 'somedir-id'
        self.assertChangeDescription('modified and renamed', old_a, new_a)

        # reset the content values so its not modified
        new_a.text_size = old_a.text_size
        new_a.text_sha1 = old_a.text_sha1
        new_a.name = old_a.name

        new_a.name = 'newfilename'
        self.assertChangeDescription('renamed', old_a, new_a)

        # reparenting is 'renaming'
        new_a.name = old_a.name
        new_a.parent_id = 'somedir-id'
        self.assertChangeDescription('renamed', old_a, new_a)

    def assertChangeDescription(self, expected_change, old_ie, new_ie):
        change = InventoryEntry.describe_change(old_ie, new_ie)
        self.assertEqual(expected_change, change)


class TestCHKInventory(tests.TestCaseWithMemoryTransport):

    def get_chk_bytes(self):
        factory = groupcompress.make_pack_factory(True, True, 1)
        trans = self.get_transport('')
        return factory(trans)

    def read_bytes(self, chk_bytes, key):
        stream = chk_bytes.get_record_stream([key], 'unordered', True)
        return stream.next().get_bytes_as("fulltext")

    def test_deserialise_gives_CHKInventory(self):
        inv = Inventory()
        inv.revision_id = "revid"
        inv.root.revision = "rootrev"
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        bytes = ''.join(chk_inv.to_lines())
        new_inv = CHKInventory.deserialise(chk_bytes, bytes, ("revid",))
        self.assertEqual("revid", new_inv.revision_id)
        self.assertEqual("directory", new_inv.root.kind)
        self.assertEqual(inv.root.file_id, new_inv.root.file_id)
        self.assertEqual(inv.root.parent_id, new_inv.root.parent_id)
        self.assertEqual(inv.root.name, new_inv.root.name)
        self.assertEqual("rootrev", new_inv.root.revision)
        self.assertEqual('plain', new_inv._search_key_name)

    def test_deserialise_wrong_revid(self):
        inv = Inventory()
        inv.revision_id = "revid"
        inv.root.revision = "rootrev"
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        bytes = ''.join(chk_inv.to_lines())
        self.assertRaises(ValueError, CHKInventory.deserialise, chk_bytes,
            bytes, ("revid2",))

    def test_captures_rev_root_byid(self):
        inv = Inventory()
        inv.revision_id = "foo"
        inv.root.revision = "bar"
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        lines = chk_inv.to_lines()
        self.assertEqual([
            'chkinventory:\n',
            'revision_id: foo\n',
            'root_id: TREE_ROOT\n',
            'parent_id_basename_to_file_id: sha1:eb23f0ad4b07f48e88c76d4c94292be57fb2785f\n',
            'id_to_entry: sha1:debfe920f1f10e7929260f0534ac9a24d7aabbb4\n',
            ], lines)
        chk_inv = CHKInventory.deserialise(chk_bytes, ''.join(lines), ('foo',))
        self.assertEqual('plain', chk_inv._search_key_name)

    def test_captures_parent_id_basename_index(self):
        inv = Inventory()
        inv.revision_id = "foo"
        inv.root.revision = "bar"
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        lines = chk_inv.to_lines()
        self.assertEqual([
            'chkinventory:\n',
            'revision_id: foo\n',
            'root_id: TREE_ROOT\n',
            'parent_id_basename_to_file_id: sha1:eb23f0ad4b07f48e88c76d4c94292be57fb2785f\n',
            'id_to_entry: sha1:debfe920f1f10e7929260f0534ac9a24d7aabbb4\n',
            ], lines)
        chk_inv = CHKInventory.deserialise(chk_bytes, ''.join(lines), ('foo',))
        self.assertEqual('plain', chk_inv._search_key_name)

    def test_captures_search_key_name(self):
        inv = Inventory()
        inv.revision_id = "foo"
        inv.root.revision = "bar"
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv,
                                              search_key_name='hash-16-way')
        lines = chk_inv.to_lines()
        self.assertEqual([
            'chkinventory:\n',
            'search_key_name: hash-16-way\n',
            'root_id: TREE_ROOT\n',
            'parent_id_basename_to_file_id: sha1:eb23f0ad4b07f48e88c76d4c94292be57fb2785f\n',
            'revision_id: foo\n',
            'id_to_entry: sha1:debfe920f1f10e7929260f0534ac9a24d7aabbb4\n',
            ], lines)
        chk_inv = CHKInventory.deserialise(chk_bytes, ''.join(lines), ('foo',))
        self.assertEqual('hash-16-way', chk_inv._search_key_name)

    def test_directory_children_on_demand(self):
        inv = Inventory()
        inv.revision_id = "revid"
        inv.root.revision = "rootrev"
        inv.add(InventoryFile("fileid", "file", inv.root.file_id))
        inv["fileid"].revision = "filerev"
        inv["fileid"].executable = True
        inv["fileid"].text_sha1 = "ffff"
        inv["fileid"].text_size = 1
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        bytes = ''.join(chk_inv.to_lines())
        new_inv = CHKInventory.deserialise(chk_bytes, bytes, ("revid",))
        root_entry = new_inv[inv.root.file_id]
        self.assertEqual(None, root_entry._children)
        self.assertEqual(['file'], root_entry.children.keys())
        file_direct = new_inv["fileid"]
        file_found = root_entry.children['file']
        self.assertEqual(file_direct.kind, file_found.kind)
        self.assertEqual(file_direct.file_id, file_found.file_id)
        self.assertEqual(file_direct.parent_id, file_found.parent_id)
        self.assertEqual(file_direct.name, file_found.name)
        self.assertEqual(file_direct.revision, file_found.revision)
        self.assertEqual(file_direct.text_sha1, file_found.text_sha1)
        self.assertEqual(file_direct.text_size, file_found.text_size)
        self.assertEqual(file_direct.executable, file_found.executable)

    def test_from_inventory_maximum_size(self):
        # from_inventory supports the maximum_size parameter.
        inv = Inventory()
        inv.revision_id = "revid"
        inv.root.revision = "rootrev"
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv, 120)
        chk_inv.id_to_entry._ensure_root()
        self.assertEqual(120, chk_inv.id_to_entry._root_node.maximum_size)
        self.assertEqual(1, chk_inv.id_to_entry._root_node._key_width)
        p_id_basename = chk_inv.parent_id_basename_to_file_id
        p_id_basename._ensure_root()
        self.assertEqual(120, p_id_basename._root_node.maximum_size)
        self.assertEqual(2, p_id_basename._root_node._key_width)

    def test___iter__(self):
        inv = Inventory()
        inv.revision_id = "revid"
        inv.root.revision = "rootrev"
        inv.add(InventoryFile("fileid", "file", inv.root.file_id))
        inv["fileid"].revision = "filerev"
        inv["fileid"].executable = True
        inv["fileid"].text_sha1 = "ffff"
        inv["fileid"].text_size = 1
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        bytes = ''.join(chk_inv.to_lines())
        new_inv = CHKInventory.deserialise(chk_bytes, bytes, ("revid",))
        fileids = list(new_inv.__iter__())
        fileids.sort()
        self.assertEqual([inv.root.file_id, "fileid"], fileids)

    def test__len__(self):
        inv = Inventory()
        inv.revision_id = "revid"
        inv.root.revision = "rootrev"
        inv.add(InventoryFile("fileid", "file", inv.root.file_id))
        inv["fileid"].revision = "filerev"
        inv["fileid"].executable = True
        inv["fileid"].text_sha1 = "ffff"
        inv["fileid"].text_size = 1
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        self.assertEqual(2, len(chk_inv))

    def test___getitem__(self):
        inv = Inventory()
        inv.revision_id = "revid"
        inv.root.revision = "rootrev"
        inv.add(InventoryFile("fileid", "file", inv.root.file_id))
        inv["fileid"].revision = "filerev"
        inv["fileid"].executable = True
        inv["fileid"].text_sha1 = "ffff"
        inv["fileid"].text_size = 1
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        bytes = ''.join(chk_inv.to_lines())
        new_inv = CHKInventory.deserialise(chk_bytes, bytes, ("revid",))
        root_entry = new_inv[inv.root.file_id]
        file_entry = new_inv["fileid"]
        self.assertEqual("directory", root_entry.kind)
        self.assertEqual(inv.root.file_id, root_entry.file_id)
        self.assertEqual(inv.root.parent_id, root_entry.parent_id)
        self.assertEqual(inv.root.name, root_entry.name)
        self.assertEqual("rootrev", root_entry.revision)
        self.assertEqual("file", file_entry.kind)
        self.assertEqual("fileid", file_entry.file_id)
        self.assertEqual(inv.root.file_id, file_entry.parent_id)
        self.assertEqual("file", file_entry.name)
        self.assertEqual("filerev", file_entry.revision)
        self.assertEqual("ffff", file_entry.text_sha1)
        self.assertEqual(1, file_entry.text_size)
        self.assertEqual(True, file_entry.executable)
        self.assertRaises(errors.NoSuchId, new_inv.__getitem__, 'missing')

    def test_has_id_true(self):
        inv = Inventory()
        inv.revision_id = "revid"
        inv.root.revision = "rootrev"
        inv.add(InventoryFile("fileid", "file", inv.root.file_id))
        inv["fileid"].revision = "filerev"
        inv["fileid"].executable = True
        inv["fileid"].text_sha1 = "ffff"
        inv["fileid"].text_size = 1
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        self.assertTrue(chk_inv.has_id('fileid'))
        self.assertTrue(chk_inv.has_id(inv.root.file_id))

    def test_has_id_not(self):
        inv = Inventory()
        inv.revision_id = "revid"
        inv.root.revision = "rootrev"
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        self.assertFalse(chk_inv.has_id('fileid'))

    def test_id2path(self):
        inv = Inventory()
        inv.revision_id = "revid"
        inv.root.revision = "rootrev"
        direntry = InventoryDirectory("dirid", "dir", inv.root.file_id)
        fileentry = InventoryFile("fileid", "file", "dirid")
        inv.add(direntry)
        inv.add(fileentry)
        inv["fileid"].revision = "filerev"
        inv["fileid"].executable = True
        inv["fileid"].text_sha1 = "ffff"
        inv["fileid"].text_size = 1
        inv["dirid"].revision = "filerev"
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        bytes = ''.join(chk_inv.to_lines())
        new_inv = CHKInventory.deserialise(chk_bytes, bytes, ("revid",))
        self.assertEqual('', new_inv.id2path(inv.root.file_id))
        self.assertEqual('dir', new_inv.id2path('dirid'))
        self.assertEqual('dir/file', new_inv.id2path('fileid'))

    def test_path2id(self):
        inv = Inventory()
        inv.revision_id = "revid"
        inv.root.revision = "rootrev"
        direntry = InventoryDirectory("dirid", "dir", inv.root.file_id)
        fileentry = InventoryFile("fileid", "file", "dirid")
        inv.add(direntry)
        inv.add(fileentry)
        inv["fileid"].revision = "filerev"
        inv["fileid"].executable = True
        inv["fileid"].text_sha1 = "ffff"
        inv["fileid"].text_size = 1
        inv["dirid"].revision = "filerev"
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        bytes = ''.join(chk_inv.to_lines())
        new_inv = CHKInventory.deserialise(chk_bytes, bytes, ("revid",))
        self.assertEqual(inv.root.file_id, new_inv.path2id(''))
        self.assertEqual('dirid', new_inv.path2id('dir'))
        self.assertEqual('fileid', new_inv.path2id('dir/file'))

    def test_create_by_apply_delta_sets_root(self):
        inv = Inventory()
        inv.revision_id = "revid"
        chk_bytes = self.get_chk_bytes()
        base_inv = CHKInventory.from_inventory(chk_bytes, inv)
        inv.add_path("", "directory", "myrootid", None)
        inv.revision_id = "expectedid"
        reference_inv = CHKInventory.from_inventory(chk_bytes, inv)
        delta = [("", None, base_inv.root.file_id, None),
            (None, "",  "myrootid", inv.root)]
        new_inv = base_inv.create_by_apply_delta(delta, "expectedid")
        self.assertEquals(reference_inv.root, new_inv.root)

    def test_create_by_apply_delta_empty_add_child(self):
        inv = Inventory()
        inv.revision_id = "revid"
        inv.root.revision = "rootrev"
        chk_bytes = self.get_chk_bytes()
        base_inv = CHKInventory.from_inventory(chk_bytes, inv)
        a_entry = InventoryFile("A-id", "A", inv.root.file_id)
        a_entry.revision = "filerev"
        a_entry.executable = True
        a_entry.text_sha1 = "ffff"
        a_entry.text_size = 1
        inv.add(a_entry)
        inv.revision_id = "expectedid"
        reference_inv = CHKInventory.from_inventory(chk_bytes, inv)
        delta = [(None, "A",  "A-id", a_entry)]
        new_inv = base_inv.create_by_apply_delta(delta, "expectedid")
        # new_inv should be the same as reference_inv.
        self.assertEqual(reference_inv.revision_id, new_inv.revision_id)
        self.assertEqual(reference_inv.root_id, new_inv.root_id)
        reference_inv.id_to_entry._ensure_root()
        new_inv.id_to_entry._ensure_root()
        self.assertEqual(reference_inv.id_to_entry._root_node._key,
            new_inv.id_to_entry._root_node._key)

    def test_create_by_apply_delta_empty_add_child_updates_parent_id(self):
        inv = Inventory()
        inv.revision_id = "revid"
        inv.root.revision = "rootrev"
        chk_bytes = self.get_chk_bytes()
        base_inv = CHKInventory.from_inventory(chk_bytes, inv)
        a_entry = InventoryFile("A-id", "A", inv.root.file_id)
        a_entry.revision = "filerev"
        a_entry.executable = True
        a_entry.text_sha1 = "ffff"
        a_entry.text_size = 1
        inv.add(a_entry)
        inv.revision_id = "expectedid"
        reference_inv = CHKInventory.from_inventory(chk_bytes, inv)
        delta = [(None, "A",  "A-id", a_entry)]
        new_inv = base_inv.create_by_apply_delta(delta, "expectedid")
        reference_inv.id_to_entry._ensure_root()
        reference_inv.parent_id_basename_to_file_id._ensure_root()
        new_inv.id_to_entry._ensure_root()
        new_inv.parent_id_basename_to_file_id._ensure_root()
        # new_inv should be the same as reference_inv.
        self.assertEqual(reference_inv.revision_id, new_inv.revision_id)
        self.assertEqual(reference_inv.root_id, new_inv.root_id)
        self.assertEqual(reference_inv.id_to_entry._root_node._key,
            new_inv.id_to_entry._root_node._key)
        self.assertEqual(reference_inv.parent_id_basename_to_file_id._root_node._key,
            new_inv.parent_id_basename_to_file_id._root_node._key)

    def test_iter_changes(self):
        # Low level bootstrapping smoke test; comprehensive generic tests via
        # InterTree are coming.
        inv = Inventory()
        inv.revision_id = "revid"
        inv.root.revision = "rootrev"
        inv.add(InventoryFile("fileid", "file", inv.root.file_id))
        inv["fileid"].revision = "filerev"
        inv["fileid"].executable = True
        inv["fileid"].text_sha1 = "ffff"
        inv["fileid"].text_size = 1
        inv2 = Inventory()
        inv2.revision_id = "revid2"
        inv2.root.revision = "rootrev"
        inv2.add(InventoryFile("fileid", "file", inv.root.file_id))
        inv2["fileid"].revision = "filerev2"
        inv2["fileid"].executable = False
        inv2["fileid"].text_sha1 = "bbbb"
        inv2["fileid"].text_size = 2
        # get fresh objects.
        chk_bytes = self.get_chk_bytes()
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv)
        bytes = ''.join(chk_inv.to_lines())
        inv_1 = CHKInventory.deserialise(chk_bytes, bytes, ("revid",))
        chk_inv2 = CHKInventory.from_inventory(chk_bytes, inv2)
        bytes = ''.join(chk_inv2.to_lines())
        inv_2 = CHKInventory.deserialise(chk_bytes, bytes, ("revid2",))
        self.assertEqual([('fileid', (u'file', u'file'), True, (True, True),
            ('TREE_ROOT', 'TREE_ROOT'), (u'file', u'file'), ('file', 'file'),
            (False, True))],
            list(inv_1.iter_changes(inv_2)))

    def test_parent_id_basename_to_file_id_index_enabled(self):
        inv = Inventory()
        inv.revision_id = "revid"
        inv.root.revision = "rootrev"
        inv.add(InventoryFile("fileid", "file", inv.root.file_id))
        inv["fileid"].revision = "filerev"
        inv["fileid"].executable = True
        inv["fileid"].text_sha1 = "ffff"
        inv["fileid"].text_size = 1
        # get fresh objects.
        chk_bytes = self.get_chk_bytes()
        tmp_inv = CHKInventory.from_inventory(chk_bytes, inv)
        bytes = ''.join(tmp_inv.to_lines())
        chk_inv = CHKInventory.deserialise(chk_bytes, bytes, ("revid",))
        self.assertIsInstance(chk_inv.parent_id_basename_to_file_id, chk_map.CHKMap)
        self.assertEqual(
            {('', ''): 'TREE_ROOT', ('TREE_ROOT', 'file'): 'fileid'},
            dict(chk_inv.parent_id_basename_to_file_id.iteritems()))

    def test_file_entry_to_bytes(self):
        inv = CHKInventory(None)
        ie = inventory.InventoryFile('file-id', 'filename', 'parent-id')
        ie.executable = True
        ie.revision = 'file-rev-id'
        ie.text_sha1 = 'abcdefgh'
        ie.text_size = 100
        bytes = inv._entry_to_bytes(ie)
        self.assertEqual('file: file-id\nparent-id\nfilename\n'
                         'file-rev-id\nabcdefgh\n100\nY', bytes)
        ie2 = inv._bytes_to_entry(bytes)
        self.assertEqual(ie, ie2)
        self.assertIsInstance(ie2.name, unicode)
        self.assertEqual(('filename', 'file-id', 'file-rev-id'),
                         inv._bytes_to_utf8name_key(bytes))

    def test_file2_entry_to_bytes(self):
        inv = CHKInventory(None)
        # \u30a9 == 'omega'
        ie = inventory.InventoryFile('file-id', u'\u03a9name', 'parent-id')
        ie.executable = False
        ie.revision = 'file-rev-id'
        ie.text_sha1 = '123456'
        ie.text_size = 25
        bytes = inv._entry_to_bytes(ie)
        self.assertEqual('file: file-id\nparent-id\n\xce\xa9name\n'
                         'file-rev-id\n123456\n25\nN', bytes)
        ie2 = inv._bytes_to_entry(bytes)
        self.assertEqual(ie, ie2)
        self.assertIsInstance(ie2.name, unicode)
        self.assertEqual(('\xce\xa9name', 'file-id', 'file-rev-id'),
                         inv._bytes_to_utf8name_key(bytes))

    def test_dir_entry_to_bytes(self):
        inv = CHKInventory(None)
        ie = inventory.InventoryDirectory('dir-id', 'dirname', 'parent-id')
        ie.revision = 'dir-rev-id'
        bytes = inv._entry_to_bytes(ie)
        self.assertEqual('dir: dir-id\nparent-id\ndirname\ndir-rev-id', bytes)
        ie2 = inv._bytes_to_entry(bytes)
        self.assertEqual(ie, ie2)
        self.assertIsInstance(ie2.name, unicode)
        self.assertEqual(('dirname', 'dir-id', 'dir-rev-id'),
                         inv._bytes_to_utf8name_key(bytes))

    def test_dir2_entry_to_bytes(self):
        inv = CHKInventory(None)
        ie = inventory.InventoryDirectory('dir-id', u'dir\u03a9name',
                                          None)
        ie.revision = 'dir-rev-id'
        bytes = inv._entry_to_bytes(ie)
        self.assertEqual('dir: dir-id\n\ndir\xce\xa9name\n'
                         'dir-rev-id', bytes)
        ie2 = inv._bytes_to_entry(bytes)
        self.assertEqual(ie, ie2)
        self.assertIsInstance(ie2.name, unicode)
        self.assertIs(ie2.parent_id, None)
        self.assertEqual(('dir\xce\xa9name', 'dir-id', 'dir-rev-id'),
                         inv._bytes_to_utf8name_key(bytes))

    def test_symlink_entry_to_bytes(self):
        inv = CHKInventory(None)
        ie = inventory.InventoryLink('link-id', 'linkname', 'parent-id')
        ie.revision = 'link-rev-id'
        ie.symlink_target = u'target/path'
        bytes = inv._entry_to_bytes(ie)
        self.assertEqual('symlink: link-id\nparent-id\nlinkname\n'
                         'link-rev-id\ntarget/path', bytes)
        ie2 = inv._bytes_to_entry(bytes)
        self.assertEqual(ie, ie2)
        self.assertIsInstance(ie2.name, unicode)
        self.assertIsInstance(ie2.symlink_target, unicode)
        self.assertEqual(('linkname', 'link-id', 'link-rev-id'),
                         inv._bytes_to_utf8name_key(bytes))

    def test_symlink2_entry_to_bytes(self):
        inv = CHKInventory(None)
        ie = inventory.InventoryLink('link-id', u'link\u03a9name', 'parent-id')
        ie.revision = 'link-rev-id'
        ie.symlink_target = u'target/\u03a9path'
        bytes = inv._entry_to_bytes(ie)
        self.assertEqual('symlink: link-id\nparent-id\nlink\xce\xa9name\n'
                         'link-rev-id\ntarget/\xce\xa9path', bytes)
        ie2 = inv._bytes_to_entry(bytes)
        self.assertEqual(ie, ie2)
        self.assertIsInstance(ie2.name, unicode)
        self.assertIsInstance(ie2.symlink_target, unicode)
        self.assertEqual(('link\xce\xa9name', 'link-id', 'link-rev-id'),
                         inv._bytes_to_utf8name_key(bytes))

    def test_tree_reference_entry_to_bytes(self):
        inv = CHKInventory(None)
        ie = inventory.TreeReference('tree-root-id', u'tree\u03a9name',
                                     'parent-id')
        ie.revision = 'tree-rev-id'
        ie.reference_revision = 'ref-rev-id'
        bytes = inv._entry_to_bytes(ie)
        self.assertEqual('tree: tree-root-id\nparent-id\ntree\xce\xa9name\n'
                         'tree-rev-id\nref-rev-id', bytes)
        ie2 = inv._bytes_to_entry(bytes)
        self.assertEqual(ie, ie2)
        self.assertIsInstance(ie2.name, unicode)
        self.assertEqual(('tree\xce\xa9name', 'tree-root-id', 'tree-rev-id'),
                         inv._bytes_to_utf8name_key(bytes))


class TestCHKInventoryExpand(tests.TestCaseWithMemoryTransport):

    def get_chk_bytes(self):
        factory = groupcompress.make_pack_factory(True, True, 1)
        trans = self.get_transport('')
        return factory(trans)

    def make_dir(self, inv, name, parent_id):
        inv.add(inv.make_entry('directory', name, parent_id, name + '-id'))

    def make_file(self, inv, name, parent_id, content='content\n'):
        ie = inv.make_entry('file', name, parent_id, name + '-id')
        ie.text_sha1 = osutils.sha_string(content)
        ie.text_size = len(content)
        inv.add(ie)

    def make_simple_inventory(self):
        inv = Inventory('TREE_ROOT')
        inv.revision_id = "revid"
        inv.root.revision = "rootrev"
        # /                 TREE_ROOT
        # dir1/             dir1-id
        #   sub-file1       sub-file1-id
        #   sub-file2       sub-file2-id
        #   sub-dir1/       sub-dir1-id
        #     subsub-file1  subsub-file1-id
        # dir2/             dir2-id
        #   sub2-file1      sub2-file1-id
        # top               top-id
        self.make_dir(inv, 'dir1', 'TREE_ROOT')
        self.make_dir(inv, 'dir2', 'TREE_ROOT')
        self.make_dir(inv, 'sub-dir1', 'dir1-id')
        self.make_file(inv, 'top', 'TREE_ROOT')
        self.make_file(inv, 'sub-file1', 'dir1-id')
        self.make_file(inv, 'sub-file2', 'dir1-id')
        self.make_file(inv, 'subsub-file1', 'sub-dir1-id')
        self.make_file(inv, 'sub2-file1', 'dir2-id')
        chk_bytes = self.get_chk_bytes()
        #  use a small maximum_size to force internal paging structures
        chk_inv = CHKInventory.from_inventory(chk_bytes, inv,
                        maximum_size=100,
                        search_key_name='hash-255-way')
        bytes = ''.join(chk_inv.to_lines())
        return CHKInventory.deserialise(chk_bytes, bytes, ("revid",))

    def assert_Getitems(self, expected_fileids, inv, file_ids):
        self.assertEqual(sorted(expected_fileids),
                         sorted([ie.file_id for ie in inv._getitems(file_ids)]))

    def assertExpand(self, all_ids, inv, file_ids):
        (val_all_ids,
         val_children) = inv._expand_fileids_to_parents_and_children(file_ids)
        self.assertEqual(set(all_ids), val_all_ids)
        entries = inv._getitems(val_all_ids)
        expected_children = {}
        for entry in entries:
            s = expected_children.setdefault(entry.parent_id, [])
            s.append(entry.file_id)
        val_children = dict((k, sorted(v)) for k, v
                            in val_children.iteritems())
        expected_children = dict((k, sorted(v)) for k, v
                            in expected_children.iteritems())
        self.assertEqual(expected_children, val_children)

    def test_make_simple_inventory(self):
        inv = self.make_simple_inventory()
        layout = []
        for path, entry in inv.iter_entries_by_dir():
            layout.append((path, entry.file_id))
        self.assertEqual([
            ('', 'TREE_ROOT'),
            ('dir1', 'dir1-id'),
            ('dir2', 'dir2-id'),
            ('top', 'top-id'),
            ('dir1/sub-dir1', 'sub-dir1-id'),
            ('dir1/sub-file1', 'sub-file1-id'),
            ('dir1/sub-file2', 'sub-file2-id'),
            ('dir1/sub-dir1/subsub-file1', 'subsub-file1-id'),
            ('dir2/sub2-file1', 'sub2-file1-id'),
            ], layout)

    def test__getitems(self):
        inv = self.make_simple_inventory()
        # Reading from disk
        self.assert_Getitems(['dir1-id'], inv, ['dir1-id'])
        self.assertTrue('dir1-id' in inv._fileid_to_entry_cache)
        self.assertFalse('sub-file2-id' in inv._fileid_to_entry_cache)
        # From cache
        self.assert_Getitems(['dir1-id'], inv, ['dir1-id'])
        # Mixed
        self.assert_Getitems(['dir1-id', 'sub-file2-id'], inv,
                             ['dir1-id', 'sub-file2-id'])
        self.assertTrue('dir1-id' in inv._fileid_to_entry_cache)
        self.assertTrue('sub-file2-id' in inv._fileid_to_entry_cache)

    def test_single_file(self):
        inv = self.make_simple_inventory()
        self.assertExpand(['TREE_ROOT', 'top-id'], inv, ['top-id'])

    def test_get_all_parents(self):
        inv = self.make_simple_inventory()
        self.assertExpand(['TREE_ROOT', 'dir1-id', 'sub-dir1-id',
                           'subsub-file1-id',
                          ], inv, ['subsub-file1-id'])

    def test_get_children(self):
        inv = self.make_simple_inventory()
        self.assertExpand(['TREE_ROOT', 'dir1-id', 'sub-dir1-id',
                           'sub-file1-id', 'sub-file2-id', 'subsub-file1-id',
                          ], inv, ['dir1-id'])

    def test_from_root(self):
        inv = self.make_simple_inventory()
        self.assertExpand(['TREE_ROOT', 'dir1-id', 'dir2-id', 'sub-dir1-id',
                           'sub-file1-id', 'sub-file2-id', 'sub2-file1-id',
                           'subsub-file1-id', 'top-id'], inv, ['TREE_ROOT'])

    def test_top_level_file(self):
        inv = self.make_simple_inventory()
        self.assertExpand(['TREE_ROOT', 'top-id'], inv, ['top-id'])

    def test_subsub_file(self):
        inv = self.make_simple_inventory()
        self.assertExpand(['TREE_ROOT', 'dir1-id', 'sub-dir1-id',
                           'subsub-file1-id'], inv, ['subsub-file1-id'])

    def test_sub_and_root(self):
        inv = self.make_simple_inventory()
        self.assertExpand(['TREE_ROOT', 'dir1-id', 'sub-dir1-id', 'top-id',
                           'subsub-file1-id'], inv, ['top-id', 'subsub-file1-id'])
