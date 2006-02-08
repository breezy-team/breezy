import os
import shutil
import stat
import sys

from bzrlib.add import smart_add_tree
from bzrlib.branch import ScratchBranch, Branch
from bzrlib.builtins import merge
from bzrlib.errors import (NotBranchError, NotVersionedError,
                           WorkingTreeNotRevision, BzrCommandError)
from bzrlib.inventory import RootEntry
import bzrlib.inventory as inventory
from bzrlib.osutils import file_kind, rename, sha_file, pathjoin, mkdtemp
from bzrlib.transform import Merge3Merger, WeaveMerger, TreeTransform
from bzrlib.tests import TestCaseWithTransport, TestCase
from bzrlib.workingtree import WorkingTree


class MergeBuilder(object):
    def __init__(self):
        self.dir = mkdtemp(prefix="merge-test")
        def wt(name):
           path = pathjoin(self.dir, name)
           os.mkdir(path)
           b = Branch.initialize(path)
           wt = b.working_tree()
           tt = TreeTransform(wt)
           return wt, tt
        self.base, self.base_tt = wt('base') 
        self.this, self.this_tt = wt('this')
        self.other, self.other_tt = wt('other')

    def get_cset_path(self, parent, name):
        if name is None:
            assert (parent is None)
            return None
        return pathjoin(self.cset.entries[parent].path, name)

    def add_file(self, id, parent, name, contents, mode):
        def new_file(tt):
            parent_id = tt.get_trans_id(parent)
            tt.new_file(name, parent_id, contents, id)
        for tt in (self.this_tt, self.base_tt, self.other_tt):
            new_file(tt)

    def merge(self):
        for tt in (self.this_tt, self.base_tt, self.other_tt):
            tt.apply()
        m3m = Merge3Merger(self.this, self.this, self.base, self.other)
        return m3m.conflicts

    def list_transforms(self):
        return [self.this_tt, self.base_tt, self.other_tt]

    def selected_transforms(self, this, base, other):
        pairs = [(this, self.this_tt), (base, self.base_tt), 
                 (other, self.other_tt)]
        return [(v, tt) for (v, tt) in pairs if v is not None]

    def add_symlink(self, id, parent, name, contents):
        for tt in self.list_transforms():
            parent_id = tt.get_trans_id(parent)
            tt.new_symlink(name, parent_id, contents, id)

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
                        return changeset.TreeFileCreate(tree, id)
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
        for val, tt in ((base, self.base_tt), (this, self.this_tt), 
                        (other, self.other_tt)):
            if val is None:
                continue
            trans_id = tt.get_trans_id(id)
            parent_id = tt.final_parent(trans_id)
            tt.adjust_path(val, parent_id, trans_id)

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
            contents = changeset.ReplaceFileContents(self.base, self.other, id)
            self.cset.entries[id].contents_change = contents

    def change_target(self, id, base=None, this=None, other=None):
        for target, tt in self.selected_transforms(this, base, other):
            trans_id = tt.get_trans_id(id)
            tt.cancel_creation(trans_id)
            tt.create_symlink(target, trans_id)

    def change_perms(self, id, base=None, this=None, other=None):
        for executability, tt in self.selected_transforms(this, base, other):
            trans_id = tt.get_trans_id(id)
            tt.cancel_creation(trans_id)
            tt.create_symlink(target, trans_id)
            sel
        if base is not None:
            self.change_perms_tree(id, self.base, base)

        if this is not None:
            self.change_perms_tree(id, self.this, this)

        if other is not None:
            self.change_perms_tree(id, self.other, other)

        if base is not None or other is not None:
            old_exec = self.base.is_executable(id)
            new_exec = self.other.is_executable(id)
            metadata = changeset.ChangeExecFlag(old_exec, new_exec)
            self.cset.entries[id].metadata_change = metadata

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
        conflict_handler = changeset.ExceptionConflictHandler()
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
                return pathjoin(dirname, os.path.basename(orig_inventory[file_id]))

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

    def apply_changeset(self, cset, conflict_handler=None):
        inventory_change = changeset.apply_changeset(cset,
                                                     self.this.inventory_dict,
                                                     self.this.dir,
                                                     conflict_handler)
        self.this.inventory_dict =  self.apply_inv_change(inventory_change, 
                                                     self.this.inventory_dict)

    def cleanup(self):
        shutil.rmtree(self.dir)


class MergeTest(TestCase):
    def test_change_name(self):
        """Test renames"""
        builder = MergeBuilder()
        builder.add_file("1", "0", "name1", "hello1", 0755)
        builder.change_name("1", other="name2")
        builder.add_file("2", "0", "name3", "hello2", 0755)
        builder.change_name("2", base="name4")
        builder.add_file("3", "0", "name5", "hello3", 0755)
        builder.change_name("3", this="name6")
        builder.merge()
        builder.cleanup()
        builder = MergeBuilder()
        builder.add_file("1", "0", "name1", "hello1", 0644)
        builder.change_name("1", other="name2", this="name3")
        self.assertRaises(changeset.RenameConflict, builder.merge)
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
        self.assert_(Inventory(builder.other.inventory_dict).get_parent("3") == "2")
        builder.change_parent("4", this="2")
        self.assert_(Inventory(builder.this.inventory_dict).get_parent("4") == "2")
        builder.change_parent("5", base="2")
        self.assert_(Inventory(builder.base.inventory_dict).get_parent("5") == "2")
        cset = builder.merge_changeset(ApplyMerge3)
        for id in ("1", "2", "4", "5"):
            self.assert_(cset.entries[id].is_boring())
        self.assert_(cset.entries["3"].parent == "1")
        self.assert_(cset.entries["3"].new_parent == "2")
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
        self.assert_(backup_exists("1"))
        self.assert_(backup_exists("2"))
        self.assert_(not backup_exists("3"))
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
        self.assert_(not builder.cset.entries["4"].is_boring())
        builder.change_contents("3", this="text6")
        cset = builder.merge_changeset(merge_factory)
        self.assert_(cset.entries["1"].contents_change is not None)
        if isclass(merge_factory):
            self.assert_(isinstance(cset.entries["1"].contents_change,
                          merge_factory))
            self.assert_(isinstance(cset.entries["2"].contents_change,
                          merge_factory))
        self.assert_(cset.entries["3"].is_boring())
        self.assert_(cset.entries["4"].is_boring())
        builder.apply_changeset(cset)
        self.assert_(file(builder.this.full_path("1"), "rb").read() == "text4" )
        self.assert_(file(builder.this.full_path("2"), "rb").read() == "text2" )
        if sys.platform != "win32":
            self.assert_(os.stat(builder.this.full_path("1")).st_mode &0777 == 0755)
            self.assert_(os.stat(builder.this.full_path("2")).st_mode &0777 == 0655)
            self.assert_(os.stat(builder.this.full_path("3")).st_mode &0777 == 0744)
        return builder

    def contents_test_conflicts(self, merge_factory):
        builder = MergeBuilder()
        builder.add_file("1", "0", "name1", "text1", 0755)
        builder.change_contents("1", other="text4", this="text3")
        cset = builder.merge_changeset(merge_factory)
        self.assertRaises(changeset.MergeConflict, builder.apply_changeset,
                          cset)
        builder.cleanup()

    def test_symlink_conflicts(self):
        if sys.platform != "win32":
            builder = MergeBuilder()
            builder.add_symlink("2", "TREE_ROOT", "name2", "target1")
            builder.change_target("2", other="target4", base="text3")
            conflicts = builder.merge()
            self.assertEqual(conflicts, [('contents conflict', ("2"))])
            builder.cleanup()

    def test_symlink_merge(self):
        if sys.platform != "win32":
            builder = MergeBuilder()
            builder.add_symlink("1", "TREE_ROOT", "name1", "target1")
            builder.add_symlink("2", "TREE_ROOT", "name2", "target1")
            builder.add_symlink("3", "TREE_ROOT", "name3", "target1")
            builder.change_target("1", this="target2")
            builder.change_target("2", base="target2")
            builder.change_target("3", other="target2")
            builder.merge()
            self.assertEqual(builder.this.get_symlink_target("1"), "target2")
            self.assertEqual(builder.this.get_symlink_target("2"), "target1")
            self.assertEqual(builder.this.get_symlink_target("3"), "target2")
            builder.cleanup()

    def test_perms_merge(self):
        builder = MergeBuilder()
        builder.add_file("1", "0", "name1", "text1", 0755)
        builder.change_perms("1", other=0644)
        builder.add_file("2", "0", "name2", "text2", 0755)
        builder.change_perms("2", base=0644)
        builder.add_file("3", "0", "name3", "text3", 0755)
        builder.change_perms("3", this=0644)
        cset = builder.merge_changeset(ApplyMerge3)
        self.assert_(cset.entries["1"].metadata_change is not None)
        self.assert_(isinstance(cset.entries["1"].metadata_change, ExecFlagMerge))
        self.assert_(isinstance(cset.entries["2"].metadata_change, ExecFlagMerge))
        self.assert_(cset.entries["3"].is_boring())
        builder.apply_changeset(cset)
        if sys.platform != "win32":
            self.assert_(os.lstat(builder.this.full_path("1")).st_mode &0100 == 0000)
            self.assert_(os.lstat(builder.this.full_path("2")).st_mode &0100 == 0100)
            self.assert_(os.lstat(builder.this.full_path("3")).st_mode &0100 == 0000)
        builder.cleanup();

    def test_new_suffix(self):
        for merge_type in ApplyMerge3, Diff3Merge:
            builder = MergeBuilder()
            builder.add_file("1", "0", "name1", "text1", 0755)
            builder.change_contents("1", other="text3")
            builder.add_file("2", "0", "name1.new", "text2", 0777)
            cset = builder.merge_changeset(ApplyMerge3)
            os.lstat(builder.this.full_path("2"))
            builder.apply_changeset(cset)
            os.lstat(builder.this.full_path("2"))
            builder.cleanup()


class FunctionalMergeTest(TestCaseWithTransport):

    def test_trivial_star_merge(self):
        """Test that merges in a star shape Just Work.""" 
        # John starts a branch
        self.build_tree(("original/", "original/file1", "original/file2"))
        tree = WorkingTree.create_standalone('original')
        branch = tree.branch
        smart_add_tree(tree, ["original"])
        tree.commit("start branch.", verbose=False)
        # Mary branches it.
        self.build_tree(("mary/",))
        branch.clone("mary")
        # Now John commits a change
        file = open("original/file1", "wt")
        file.write("John\n")
        file.close()
        tree.commit("change file1")
        # Mary does too
        mary_branch = Branch.open("mary")
        file = open("mary/file2", "wt")
        file.write("Mary\n")
        file.close()
        mary_branch.working_tree().commit("change file2")
        # john should be able to merge with no conflicts.
        merge_type = Merge3Merger
        base = [None, None]
        other = ("mary", -1)
        self.assertRaises(BzrCommandError, merge, other, base, check_clean=True,
                          merge_type=WeaveMerger, this_dir="original",
                          show_base=True)
        merge(other, base, check_clean=True, merge_type=merge_type,
              this_dir="original")
        self.assertEqual("John\n", open("original/file1", "rt").read())
        self.assertEqual("Mary\n", open("original/file2", "rt").read())
 
    def test_conflicts(self):
        os.mkdir('a')
        wta = WorkingTree.create_standalone('a')
        a = wta.branch
        file('a/file', 'wb').write('contents\n')
        wta.add('file')
        wta.commit('base revision', allow_pointless=False)
        b = a.clone('b')
        file('a/file', 'wb').write('other contents\n')
        wta.commit('other revision', allow_pointless=False)
        file('b/file', 'wb').write('this contents contents\n')
        b.working_tree().commit('this revision', allow_pointless=False)
        self.assertEqual(merge(['a', -1], [None, None], this_dir='b'), 1)
        self.assert_(os.path.lexists('b/file.THIS'))
        self.assert_(os.path.lexists('b/file.BASE'))
        self.assert_(os.path.lexists('b/file.OTHER'))
        self.assertRaises(WorkingTreeNotRevision, merge, ['a', -1], 
                          [None, None], this_dir='b', check_clean=False,
                          merge_type=WeaveMerger)
        b.working_tree().revert([])
        os.unlink('b/file.THIS')
        os.unlink('b/file.OTHER')
        os.unlink('b/file.BASE')
        self.assertEqual(merge(['a', -1], [None, None], this_dir='b', 
                               check_clean=False, merge_type=WeaveMerger), 1)
        self.assert_(os.path.lexists('b/file'))
        self.assert_(os.path.lexists('b/file.THIS'))
        self.assert_(not os.path.lexists('b/file.BASE'))
        self.assert_(os.path.lexists('b/file.OTHER'))

    def test_merge_unrelated(self):
        """Sucessfully merges unrelated branches with no common names"""
        wta = self.make_branch_and_tree('a')
        a = wta.branch
        file('a/a_file', 'wb').write('contents\n')
        wta.add('a_file')
        wta.commit('a_revision', allow_pointless=False)
        wtb = self.make_branch_and_tree('b')
        b = wtb.branch
        file('b/b_file', 'wb').write('contents\n')
        wtb.add('b_file')
        wtb.commit('b_revision', allow_pointless=False)
        merge(['b', -1], ['b', 0], this_dir='a')
        self.assert_(os.path.lexists('a/b_file'))
        self.assertEqual(wta.pending_merges(),
                         [b.last_revision()]) 

    def test_merge_unrelated_conflicting(self):
        """Sucessfully merges unrelated branches with common names"""
        wta = self.make_branch_and_tree('a')
        a = wta.branch
        file('a/file', 'wb').write('contents\n')
        wta.add('file')
        wta.commit('a_revision', allow_pointless=False)
        wtb = self.make_branch_and_tree('b')
        b = wtb.branch
        file('b/file', 'wb').write('contents\n')
        wtb.add('file')
        wtb.commit('b_revision', allow_pointless=False)
        merge(['b', -1], ['b', 0], this_dir='a')
        self.assert_(os.path.lexists('a/file'))
        self.assert_(os.path.lexists('a/file.moved'))
        self.assertEqual(wta.pending_merges(), [b.last_revision()])

    def test_merge_deleted_conflicts(self):
        wta = self.make_branch_and_tree('a')
        file('a/file', 'wb').write('contents\n')
        wta.add('file')
        wta.commit('a_revision', allow_pointless=False)
        self.run_bzr('branch', 'a', 'b')
        os.remove('a/file')
        wta.commit('removed file', allow_pointless=False)
        file('b/file', 'wb').write('changed contents\n')
        wtb = WorkingTree('b')
        wtb.commit('changed file', allow_pointless=False)
        merge(['a', -1], ['a', 1], this_dir='b')
        self.failIf(os.path.lexists('b/file'))

    def test_merge_metadata_vs_deletion(self):
        """Conflict deletion vs metadata change"""
        a_wt = self.make_branch_and_tree('a')
        file('a/file', 'wb').write('contents\n')
        a_wt.add('file')
        a_wt.commit('r0')
        self.run_bzr('branch', 'a', 'b')
        b_wt = WorkingTree('b')
        os.chmod('b/file', 0755)
        os.remove('a/file')
        a_wt.commit('removed a')
        self.assertEqual(a_wt.branch.revno(), 2)
        self.assertFalse(os.path.exists('a/file'))
        b_wt.commit('exec a')
        merge(['b', -1], ['b', 0], this_dir='a')
        self.assert_(os.path.exists('a/file'))

    def test_merge_swapping_renames(self):
        a_wt = self.make_branch_and_tree('a')
        file('a/un','wb').write('UN')
        file('a/deux','wb').write('DEUX')
        a_wt.add('un')
        a_wt.add('deux')
        a_wt.commit('r0')
        self.run_bzr('branch', 'a', 'b')
        b_wt = WorkingTree('b')
        b_wt.rename_one('un','tmp')
        b_wt.rename_one('deux','un')
        b_wt.rename_one('tmp','deux')
        b_wt.commit('r1')
        merge(['b', -1],['b', 1],this_dir='a')
        self.assert_(os.path.exists('a/un'))
        self.assert_(os.path.exists('a/deux'))
        self.assertFalse(os.path.exists('a/tmp'))
        self.assertEqual(file('a/un').read(),'DEUX')
        self.assertEqual(file('a/deux').read(),'UN')

    def test_merge_delete_and_add_same(self):
        a_wt = self.make_branch_and_tree('a')
        file('a/file', 'wb').write('THIS')
        a_wt.add('file')
        a_wt.commit('r0')
        self.run_bzr('branch', 'a', 'b')
        b_wt = WorkingTree('b')
        os.remove('b/file')
        b_wt.commit('r1')
        file('b/file', 'wb').write('THAT')
        b_wt.add('file')
        b_wt.commit('r2')
        merge(['b', -1],['b', 1],this_dir='a')
        self.assert_(os.path.exists('a/file'))
        self.assertEqual(file('a/file').read(),'THAT')

    def test_merge_rename_before_create(self):
        """rename before create
        
        This case requires that you must not do creates
        before move-into-place:

        $ touch foo
        $ bzr add foo
        $ bzr commit
        $ bzr mv foo bar
        $ touch foo
        $ bzr add foo
        $ bzr commit
        """
        a_wt = self.make_branch_and_tree('a')
        file('a/foo', 'wb').write('A/FOO')
        a_wt.add('foo')
        a_wt.commit('added foo')
        self.run_bzr('branch', 'a', 'b')
        b_wt = WorkingTree('b')
        b_wt.rename_one('foo', 'bar')
        file('b/foo', 'wb').write('B/FOO')
        b_wt.add('foo')
        b_wt.commit('moved foo to bar, added new foo')
        merge(['b', -1],['b', 1],this_dir='a')

    def test_merge_create_before_rename(self):
        """create before rename, target parents before children

        This case requires that you must not do move-into-place
        before creates, and that you must not do children after
        parents:

        $ touch foo
        $ bzr add foo
        $ bzr commit
        $ bzr mkdir bar
        $ bzr add bar
        $ bzr mv foo bar/foo
        $ bzr commit
        """
        os.mkdir('a')
        a_wt = self.make_branch_and_tree('a')
        file('a/foo', 'wb').write('A/FOO')
        a_wt.add('foo')
        a_wt.commit('added foo')
        self.run_bzr('branch', 'a', 'b')
        b_wt = WorkingTree('b')
        os.mkdir('b/bar')
        b_wt.add('bar')
        b_wt.rename_one('foo', 'bar/foo')
        b_wt.commit('created bar dir, moved foo into bar')
        merge(['b', -1],['b', 1],this_dir='a')

    def test_merge_rename_to_temp_before_delete(self):
        """rename to temp before delete, source children before parents

        This case requires that you must not do deletes before
        move-out-of-the-way, and that you must not do children
        after parents:
        
        $ mkdir foo
        $ touch foo/bar
        $ bzr add foo/bar
        $ bzr commit
        $ bzr mv foo/bar bar
        $ rmdir foo
        $ bzr commit
        """
        a_wt = self.make_branch_and_tree('a')
        os.mkdir('a/foo')
        file('a/foo/bar', 'wb').write('A/FOO/BAR')
        a_wt.add('foo')
        a_wt.add('foo/bar')
        a_wt.commit('added foo/bar')
        self.run_bzr('branch', 'a', 'b')
        b_wt = WorkingTree('b')
        b_wt.rename_one('foo/bar', 'bar')
        os.rmdir('b/foo')
        b_wt.remove('foo')
        b_wt.commit('moved foo/bar to bar, deleted foo')
        merge(['b', -1],['b', 1],this_dir='a')

    def test_merge_delete_before_rename_to_temp(self):
        """delete before rename to temp

        This case requires that you must not do
        move-out-of-the-way before deletes:
        
        $ touch foo
        $ touch bar
        $ bzr add foo bar
        $ bzr commit
        $ rm foo
        $ bzr rm foo
        $ bzr mv bar foo
        $ bzr commit
        """
        a_wt = self.make_branch_and_tree('a')
        file('a/foo', 'wb').write('A/FOO')
        file('a/bar', 'wb').write('A/BAR')
        a_wt.add('foo')
        a_wt.add('bar')
        a_wt.commit('added foo and bar')
        self.run_bzr('branch', 'a', 'b')
        b_wt = WorkingTree('b')
        os.unlink('b/foo')
        b_wt.remove('foo')
        b_wt.rename_one('bar', 'foo')
        b_wt.commit('deleted foo, renamed bar to foo')
        merge(['b', -1],['b', 1],this_dir='a')

