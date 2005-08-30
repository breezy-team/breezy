import os
import unittest

from bzrlib.selftest import TestCaseInTempDir, TestCase
from bzrlib.branch import ScratchBranch, Branch
from bzrlib.errors import NotBranchError, NotVersionedError


import unittest
import tempfile
import shutil
from bzrlib.inventory import InventoryEntry, RootEntry
from bzrlib.osutils import file_kind
from bzrlib import changeset
from bzrlib.merge_core import (ApplyMerge3, make_merge_changeset,
                                BackupBeforeChange, PermissionsMerge)
from bzrlib.changeset import Inventory, apply_changeset, invert_dict

class FalseTree(object):
    def __init__(self, realtree):
        self._realtree = realtree
        self.inventory = self

    def __getitem__(self, file_id):
        entry = self.make_inventory_entry(file_id)
        if entry is None:
            raise KeyError(file_id)
        return entry
        
    def make_inventory_entry(self, file_id):
        path = self._realtree.inventory.get(file_id)
        if path is None:
            return None
        if path == "":
            return RootEntry(file_id)
        dir, name = os.path.split(path)
        kind = file_kind(self._realtree.abs_path(path))
        for parent_id, path in self._realtree.inventory.iteritems():
            if path == dir:
                break
        if path != dir:
            raise Exception("Can't find parent for %s" % name)
        return InventoryEntry(file_id, name, kind, parent_id)


class MergeTree(object):
    def __init__(self, dir):
        self.dir = dir;
        os.mkdir(dir)
        self.inventory = {'0': ""}
        self.tree = FalseTree(self)
    
    def child_path(self, parent, name):
        return os.path.join(self.inventory[parent], name)

    def add_file(self, id, parent, name, contents, mode):
        path = self.child_path(parent, name)
        full_path = self.abs_path(path)
        assert not os.path.exists(full_path)
        file(full_path, "wb").write(contents)
        os.chmod(self.abs_path(path), mode)
        self.inventory[id] = path

    def remove_file(self, id):
        os.unlink(self.full_path(id))
        del self.inventory[id]

    def add_dir(self, id, parent, name, mode):
        path = self.child_path(parent, name)
        full_path = self.abs_path(path)
        assert not os.path.exists(full_path)
        os.mkdir(self.abs_path(path))
        os.chmod(self.abs_path(path), mode)
        self.inventory[id] = path

    def abs_path(self, path):
        return os.path.join(self.dir, path)

    def full_path(self, id):
        try:
            tree_path = self.inventory[id]
        except KeyError:
            return None
        return self.abs_path(tree_path)

    def readonly_path(self, id):
        return self.full_path(id)

    def __contains__(self, file_id):
        return file_id in self.inventory

    def has_or_had_id(self, file_id):
        return file_id in self

    def get_file(self, file_id):
        path = self.readonly_path(file_id)
        return file(path, "rb")

    def id2path(self, file_id):
        return self.inventory[file_id]

    def change_path(self, id, path):
        new = os.path.join(self.dir, self.inventory[id])
        os.rename(self.abs_path(self.inventory[id]), self.abs_path(path))
        self.inventory[id] = path


class MergeBuilder(object):
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="BaZing")
        self.base = MergeTree(os.path.join(self.dir, "base"))
        self.this = MergeTree(os.path.join(self.dir, "this"))
        self.other = MergeTree(os.path.join(self.dir, "other"))
        
        self.cset = changeset.Changeset()
        self.cset.add_entry(changeset.ChangesetEntry("0", 
                                                     changeset.NULL_ID, "./."))
    def get_cset_path(self, parent, name):
        if name is None:
            assert (parent is None)
            return None
        return os.path.join(self.cset.entries[parent].path, name)

    def add_file(self, id, parent, name, contents, mode):
        self.base.add_file(id, parent, name, contents, mode)
        self.this.add_file(id, parent, name, contents, mode)
        self.other.add_file(id, parent, name, contents, mode)
        path = self.get_cset_path(parent, name)
        self.cset.add_entry(changeset.ChangesetEntry(id, parent, path))

    def remove_file(self, id, base=False, this=False, other=False):
        for option, tree in ((base, self.base), (this, self.this), 
                             (other, self.other)):
            if option:
                tree.remove_file(id)
            if other or base:
                change = self.cset.entries[id].contents_change
                if change is None:
                    change = changeset.ReplaceContents(None, None)
                    self.cset.entries[id].contents_change = change
                    def create_file(tree):
                        return changeset.FileCreate(tree.get_file(id).read())
                    if not other:
                        change.new_contents = create_file(self.other)
                    if not base:
                        change.old_contents = create_file(self.base)
                else:
                    assert isinstance(change, changeset.ReplaceContents)
                if other:
                    change.new_contents=None
                if base:
                    change.old_contents=None
                if change.old_contents is None and change.new_contents is None:
                    change = None


    def add_dir(self, id, parent, name, mode):
        path = self.get_cset_path(parent, name)
        self.base.add_dir(id, parent, name, mode)
        self.cset.add_entry(changeset.ChangesetEntry(id, parent, path))
        self.this.add_dir(id, parent, name, mode)
        self.other.add_dir(id, parent, name, mode)


    def change_name(self, id, base=None, this=None, other=None):
        if base is not None:
            self.change_name_tree(id, self.base, base)
            self.cset.entries[id].name = base

        if this is not None:
            self.change_name_tree(id, self.this, this)

        if other is not None:
            self.change_name_tree(id, self.other, other)
            self.cset.entries[id].new_name = other

    def change_parent(self, id, base=None, this=None, other=None):
        if base is not None:
            self.change_parent_tree(id, self.base, base)
            self.cset.entries[id].parent = base
            self.cset.entries[id].dir = self.cset.entries[base].path

        if this is not None:
            self.change_parent_tree(id, self.this, this)

        if other is not None:
            self.change_parent_tree(id, self.other, other)
            self.cset.entries[id].new_parent = other
            self.cset.entries[id].new_dir = \
                self.cset.entries[other].new_path

    def change_contents(self, id, base=None, this=None, other=None):
        if base is not None:
            self.change_contents_tree(id, self.base, base)

        if this is not None:
            self.change_contents_tree(id, self.this, this)

        if other is not None:
            self.change_contents_tree(id, self.other, other)

        if base is not None or other is not None:
            old_contents = file(self.base.full_path(id)).read()
            new_contents = file(self.other.full_path(id)).read()
            contents = changeset.ReplaceFileContents(old_contents, 
                                                     new_contents)
            self.cset.entries[id].contents_change = contents

    def change_perms(self, id, base=None, this=None, other=None):
        if base is not None:
            self.change_perms_tree(id, self.base, base)

        if this is not None:
            self.change_perms_tree(id, self.this, this)

        if other is not None:
            self.change_perms_tree(id, self.other, other)

        if base is not None or other is not None:
            old_perms = os.stat(self.base.full_path(id)).st_mode &077
            new_perms = os.stat(self.other.full_path(id)).st_mode &077
            contents = changeset.ChangeUnixPermissions(old_perms, 
                                                       new_perms)
            self.cset.entries[id].metadata_change = contents

    def change_name_tree(self, id, tree, name):
        new_path = tree.child_path(self.cset.entries[id].parent, name)
        tree.change_path(id, new_path)

    def change_parent_tree(self, id, tree, parent):
        new_path = tree.child_path(parent, self.cset.entries[id].name)
        tree.change_path(id, new_path)

    def change_contents_tree(self, id, tree, contents):
        path = tree.full_path(id)
        mode = os.stat(path).st_mode
        file(path, "w").write(contents)
        os.chmod(path, mode)

    def change_perms_tree(self, id, tree, mode):
        os.chmod(tree.full_path(id), mode)

    def merge_changeset(self, merge_factory):
        conflict_handler = changeset.ExceptionConflictHandler(self.this.dir)
        return make_merge_changeset(self.cset, self.this, self.base,
                                    self.other, conflict_handler,
                                    merge_factory)

    def apply_inv_change(self, inventory_change, orig_inventory):
        orig_inventory_by_path = {}
        for file_id, path in orig_inventory.iteritems():
            orig_inventory_by_path[path] = file_id

        def parent_id(file_id):
            try:
                parent_dir = os.path.dirname(orig_inventory[file_id])
            except:
                print file_id
                raise
            if parent_dir == "":
                return None
            return orig_inventory_by_path[parent_dir]
        
        def new_path(file_id):
            if inventory_change.has_key(file_id):
                return inventory_change[file_id]
            else:
                parent = parent_id(file_id)
                if parent is None:
                    return orig_inventory[file_id]
                dirname = new_path(parent)
                return os.path.join(dirname, orig_inventory[file_id])

        new_inventory = {}
        for file_id in orig_inventory.iterkeys():
            path = new_path(file_id)
            if path is None:
                continue
            new_inventory[file_id] = path

        for file_id, path in inventory_change.iteritems():
            if orig_inventory.has_key(file_id):
                continue
            new_inventory[file_id] = path
        return new_inventory

    def apply_changeset(self, cset, conflict_handler=None, reverse=False):
        inventory_change = changeset.apply_changeset(cset,
                                                     self.this.inventory,
                                                     self.this.dir,
                                                     conflict_handler, reverse)
        self.this.inventory =  self.apply_inv_change(inventory_change, 
                                                     self.this.inventory)

    def cleanup(self):
        shutil.rmtree(self.dir)

class MergeTest(unittest.TestCase):
    def test_change_name(self):
        """Test renames"""
        builder = MergeBuilder()
        builder.add_file("1", "0", "name1", "hello1", 0755)
        builder.change_name("1", other="name2")
        builder.add_file("2", "0", "name3", "hello2", 0755)
        builder.change_name("2", base="name4")
        builder.add_file("3", "0", "name5", "hello3", 0755)
        builder.change_name("3", this="name6")
        cset = builder.merge_changeset(ApplyMerge3)
        assert(cset.entries["2"].is_boring())
        assert(cset.entries["1"].name == "name1")
        assert(cset.entries["1"].new_name == "name2")
        assert(cset.entries["3"].is_boring())
        for tree in (builder.this, builder.other, builder.base):
            assert(tree.dir != builder.dir and 
                   tree.dir.startswith(builder.dir))
            for path in tree.inventory.itervalues():
                fullpath = tree.abs_path(path)
                assert(fullpath.startswith(tree.dir))
                assert(not path.startswith(tree.dir))
                assert os.path.exists(fullpath)
        builder.apply_changeset(cset)
        builder.cleanup()
        builder = MergeBuilder()
        builder.add_file("1", "0", "name1", "hello1", 0644)
        builder.change_name("1", other="name2", this="name3")
        self.assertRaises(changeset.RenameConflict, 
                          builder.merge_changeset, ApplyMerge3)
        builder.cleanup()
        
    def test_file_moves(self):
        """Test moves"""
        builder = MergeBuilder()
        builder.add_dir("1", "0", "dir1", 0755)
        builder.add_dir("2", "0", "dir2", 0755)
        builder.add_file("3", "1", "file1", "hello1", 0644)
        builder.add_file("4", "1", "file2", "hello2", 0644)
        builder.add_file("5", "1", "file3", "hello3", 0644)
        builder.change_parent("3", other="2")
        assert(Inventory(builder.other.inventory).get_parent("3") == "2")
        builder.change_parent("4", this="2")
        assert(Inventory(builder.this.inventory).get_parent("4") == "2")
        builder.change_parent("5", base="2")
        assert(Inventory(builder.base.inventory).get_parent("5") == "2")
        cset = builder.merge_changeset(ApplyMerge3)
        for id in ("1", "2", "4", "5"):
            assert(cset.entries[id].is_boring())
        assert(cset.entries["3"].parent == "1")
        assert(cset.entries["3"].new_parent == "2")
        builder.apply_changeset(cset)
        builder.cleanup()

        builder = MergeBuilder()
        builder.add_dir("1", "0", "dir1", 0755)
        builder.add_dir("2", "0", "dir2", 0755)
        builder.add_dir("3", "0", "dir3", 0755)
        builder.add_file("4", "1", "file1", "hello1", 0644)
        builder.change_parent("4", other="2", this="3")
        self.assertRaises(changeset.MoveConflict, 
                          builder.merge_changeset, ApplyMerge3)
        builder.cleanup()

    def test_contents_merge(self):
        """Test merge3 merging"""
        self.do_contents_test(ApplyMerge3)

    def test_contents_merge2(self):
        """Test diff3 merging"""
        self.do_contents_test(changeset.Diff3Merge)

    def test_contents_merge3(self):
        """Test diff3 merging"""
        def backup_merge(file_id, base, other):
            return BackupBeforeChange(ApplyMerge3(file_id, base, other))
        builder = self.contents_test_success(backup_merge)
        def backup_exists(file_id):
            return os.path.exists(builder.this.full_path(file_id)+"~")
        assert backup_exists("1")
        assert backup_exists("2")
        assert not backup_exists("3")
        builder.cleanup()

    def do_contents_test(self, merge_factory):
        """Test merging with specified ContentsChange factory"""
        builder = self.contents_test_success(merge_factory)
        builder.cleanup()
        self.contents_test_conflicts(merge_factory)

    def contents_test_success(self, merge_factory):
        from inspect import isclass
        builder = MergeBuilder()
        builder.add_file("1", "0", "name1", "text1", 0755)
        builder.change_contents("1", other="text4")
        builder.add_file("2", "0", "name3", "text2", 0655)
        builder.change_contents("2", base="text5")
        builder.add_file("3", "0", "name5", "text3", 0744)
        builder.add_file("4", "0", "name6", "text4", 0744)
        builder.remove_file("4", base=True)
        assert not builder.cset.entries["4"].is_boring()
        builder.change_contents("3", this="text6")
        cset = builder.merge_changeset(merge_factory)
        assert(cset.entries["1"].contents_change is not None)
        if isclass(merge_factory):
            assert(isinstance(cset.entries["1"].contents_change,
                          merge_factory))
            assert(isinstance(cset.entries["2"].contents_change,
                          merge_factory))
        assert(cset.entries["3"].is_boring())
        assert(cset.entries["4"].is_boring())
        builder.apply_changeset(cset)
        assert(file(builder.this.full_path("1"), "rb").read() == "text4" )
        assert(file(builder.this.full_path("2"), "rb").read() == "text2" )
        assert(os.stat(builder.this.full_path("1")).st_mode &0777 == 0755)
        assert(os.stat(builder.this.full_path("2")).st_mode &0777 == 0655)
        assert(os.stat(builder.this.full_path("3")).st_mode &0777 == 0744)
        return builder

    def contents_test_conflicts(self, merge_factory):
        builder = MergeBuilder()
        builder.add_file("1", "0", "name1", "text1", 0755)
        builder.change_contents("1", other="text4", this="text3")
        cset = builder.merge_changeset(merge_factory)
        self.assertRaises(changeset.MergeConflict, builder.apply_changeset,
                          cset)
        builder.cleanup()

        builder = MergeBuilder()
        builder.add_file("1", "0", "name1", "text1", 0755)
        builder.change_contents("1", other="text4", base="text3")
        builder.remove_file("1", base=True)
        self.assertRaises(changeset.NewContentsConflict,
                          builder.merge_changeset, merge_factory)
        builder.cleanup()

        builder = MergeBuilder()
        builder.add_file("1", "0", "name1", "text1", 0755)
        builder.change_contents("1", other="text4", base="text3")
        builder.remove_file("1", this=True)
        self.assertRaises(changeset.MissingForMerge, builder.merge_changeset, 
                          merge_factory)
        builder.cleanup()

    def test_perms_merge(self):
        builder = MergeBuilder()
        builder.add_file("1", "0", "name1", "text1", 0755)
        builder.change_perms("1", other=0655)
        builder.add_file("2", "0", "name2", "text2", 0755)
        builder.change_perms("2", base=0655)
        builder.add_file("3", "0", "name3", "text3", 0755)
        builder.change_perms("3", this=0655)
        cset = builder.merge_changeset(ApplyMerge3)
        assert(cset.entries["1"].metadata_change is not None)
        assert(isinstance(cset.entries["1"].metadata_change,
                          PermissionsMerge))
        assert(isinstance(cset.entries["2"].metadata_change,
                          PermissionsMerge))
        assert(cset.entries["3"].is_boring())
        builder.apply_changeset(cset)
        assert(os.stat(builder.this.full_path("1")).st_mode &0777 == 0655)
        assert(os.stat(builder.this.full_path("2")).st_mode &0777 == 0755)
        assert(os.stat(builder.this.full_path("3")).st_mode &0777 == 0655)
        builder.cleanup();
        builder = MergeBuilder()
        builder.add_file("1", "0", "name1", "text1", 0755)
        builder.change_perms("1", other=0655, base=0555)
        cset = builder.merge_changeset(ApplyMerge3)
        self.assertRaises(changeset.MergePermissionConflict, 
                     builder.apply_changeset, cset)
        builder.cleanup()

class FunctionalMergeTest(TestCaseInTempDir):

    def test_trivial_star_merge(self):
        """Test that merges in a star shape Just Work.""" 
        from bzrlib.add import smart_add_branch
        from bzrlib.branch import copy_branch
        from bzrlib.merge import merge
        from bzrlib.merge_core import ApplyMerge3
        # John starts a branch
        self.build_tree(("original/", "original/file1", "original/file2"))
        branch = Branch("original", init=True)
        smart_add_branch(branch, ["original"], verbose=False)
        branch.commit("start branch.", verbose=False)
        # Mary branches it.
        self.build_tree(("mary/",))
        copy_branch(branch, "mary")
        # Now John commits a change
        file = open("original/file1", "wt")
        file.write("John\n")
        file.close()
        branch.commit("change file1")
        # Mary does too
        mary_branch = Branch("mary")
        file = open("mary/file2", "wt")
        file.write("Mary\n")
        file.close()
        mary_branch.commit("change file2")
        # john should be able to merge with no conflicts.
        merge_type = ApplyMerge3
        base = [None, None]
        other = ("mary", -1)
        merge(other, base, check_clean=True, merge_type=merge_type, this_dir="original")
        self.assertEqual("John\n", open("original/file1", "rt").read())
        self.assertEqual("Mary\n", open("original/file2", "rt").read())
