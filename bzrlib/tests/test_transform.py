# Copyright (C) 2006 Canonical Ltd
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
import stat
import sys

from bzrlib import (
    errors,
    generate_ids,
    symbol_versioning,
    tests,
    urlutils,
    )
from bzrlib.bzrdir import BzrDir
from bzrlib.conflicts import (DuplicateEntry, DuplicateID, MissingParent,
                              UnversionedParent, ParentLoop, DeletingParent,)
from bzrlib.errors import (DuplicateKey, MalformedTransform, NoSuchFile,
                           ReusingTransform, CantMoveRoot, 
                           PathsNotVersionedError, ExistingLimbo,
                           ImmortalLimbo, LockError)
from bzrlib.osutils import file_kind, has_symlinks, pathjoin
from bzrlib.merge import Merge3Merger
from bzrlib.tests import TestCaseInTempDir, TestSkipped, TestCase
from bzrlib.transform import (TreeTransform, ROOT_PARENT, FinalPaths, 
                              resolve_conflicts, cook_conflicts, 
                              find_interesting, build_tree, get_backup_name,
                              change_entry, _FileMover)


class TestTreeTransform(tests.TestCaseWithTransport):

    def setUp(self):
        super(TestTreeTransform, self).setUp()
        self.wt = self.make_branch_and_tree('.', format='dirstate-with-subtree')
        os.chdir('..')

    def get_transform(self):
        transform = TreeTransform(self.wt)
        #self.addCleanup(transform.finalize)
        return transform, transform.root

    def test_existing_limbo(self):
        limbo_name = urlutils.local_path_from_url(
            self.wt._control_files.controlfilename('limbo'))
        transform, root = self.get_transform()
        os.mkdir(pathjoin(limbo_name, 'hehe'))
        self.assertRaises(ImmortalLimbo, transform.apply)
        self.assertRaises(LockError, self.wt.unlock)
        self.assertRaises(ExistingLimbo, self.get_transform)
        self.assertRaises(LockError, self.wt.unlock)
        os.rmdir(pathjoin(limbo_name, 'hehe'))
        os.rmdir(limbo_name)
        transform, root = self.get_transform()
        transform.apply()

    def test_build(self):
        transform, root = self.get_transform() 
        self.assertIs(transform.get_tree_parent(root), ROOT_PARENT)
        imaginary_id = transform.trans_id_tree_path('imaginary')
        imaginary_id2 = transform.trans_id_tree_path('imaginary/')
        self.assertEqual(imaginary_id, imaginary_id2)
        self.assertEqual(transform.get_tree_parent(imaginary_id), root)
        self.assertEqual(transform.final_kind(root), 'directory')
        self.assertEqual(transform.final_file_id(root), self.wt.get_root_id())
        trans_id = transform.create_path('name', root)
        self.assertIs(transform.final_file_id(trans_id), None)
        self.assertRaises(NoSuchFile, transform.final_kind, trans_id)
        transform.create_file('contents', trans_id)
        transform.set_executability(True, trans_id)
        transform.version_file('my_pretties', trans_id)
        self.assertRaises(DuplicateKey, transform.version_file,
                          'my_pretties', trans_id)
        self.assertEqual(transform.final_file_id(trans_id), 'my_pretties')
        self.assertEqual(transform.final_parent(trans_id), root)
        self.assertIs(transform.final_parent(root), ROOT_PARENT)
        self.assertIs(transform.get_tree_parent(root), ROOT_PARENT)
        oz_id = transform.create_path('oz', root)
        transform.create_directory(oz_id)
        transform.version_file('ozzie', oz_id)
        trans_id2 = transform.create_path('name2', root)
        transform.create_file('contents', trans_id2)
        transform.set_executability(False, trans_id2)
        transform.version_file('my_pretties2', trans_id2)
        modified_paths = transform.apply().modified_paths
        self.assertEqual('contents', self.wt.get_file_byname('name').read())
        self.assertEqual(self.wt.path2id('name'), 'my_pretties')
        self.assertIs(self.wt.is_executable('my_pretties'), True)
        self.assertIs(self.wt.is_executable('my_pretties2'), False)
        self.assertEqual('directory', file_kind(self.wt.abspath('oz')))
        self.assertEqual(len(modified_paths), 3)
        tree_mod_paths = [self.wt.id2abspath(f) for f in 
                          ('ozzie', 'my_pretties', 'my_pretties2')]
        self.assertSubset(tree_mod_paths, modified_paths)
        # is it safe to finalize repeatedly?
        transform.finalize()
        transform.finalize()

    def test_convenience(self):
        transform, root = self.get_transform()
        trans_id = transform.new_file('name', root, 'contents', 
                                      'my_pretties', True)
        oz = transform.new_directory('oz', root, 'oz-id')
        dorothy = transform.new_directory('dorothy', oz, 'dorothy-id')
        toto = transform.new_file('toto', dorothy, 'toto-contents', 
                                  'toto-id', False)

        self.assertEqual(len(transform.find_conflicts()), 0)
        transform.apply()
        self.assertRaises(ReusingTransform, transform.find_conflicts)
        self.assertEqual('contents', file(self.wt.abspath('name')).read())
        self.assertEqual(self.wt.path2id('name'), 'my_pretties')
        self.assertIs(self.wt.is_executable('my_pretties'), True)
        self.assertEqual(self.wt.path2id('oz'), 'oz-id')
        self.assertEqual(self.wt.path2id('oz/dorothy'), 'dorothy-id')
        self.assertEqual(self.wt.path2id('oz/dorothy/toto'), 'toto-id')

        self.assertEqual('toto-contents',
                         self.wt.get_file_byname('oz/dorothy/toto').read())
        self.assertIs(self.wt.is_executable('toto-id'), False)

    def test_tree_reference(self):
        transform, root = self.get_transform()
        tree = transform._tree
        trans_id = transform.new_directory('reference', root, 'subtree-id')
        transform.set_tree_reference('subtree-revision', trans_id)
        transform.apply()
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual('subtree-revision',
                         tree.inventory['subtree-id'].reference_revision)

    def test_conflicts(self):
        transform, root = self.get_transform()
        trans_id = transform.new_file('name', root, 'contents', 
                                      'my_pretties')
        self.assertEqual(len(transform.find_conflicts()), 0)
        trans_id2 = transform.new_file('name', root, 'Crontents', 'toto')
        self.assertEqual(transform.find_conflicts(), 
                         [('duplicate', trans_id, trans_id2, 'name')])
        self.assertRaises(MalformedTransform, transform.apply)
        transform.adjust_path('name', trans_id, trans_id2)
        self.assertEqual(transform.find_conflicts(), 
                         [('non-directory parent', trans_id)])
        tinman_id = transform.trans_id_tree_path('tinman')
        transform.adjust_path('name', tinman_id, trans_id2)
        self.assertEqual(transform.find_conflicts(), 
                         [('unversioned parent', tinman_id), 
                          ('missing parent', tinman_id)])
        lion_id = transform.create_path('lion', root)
        self.assertEqual(transform.find_conflicts(), 
                         [('unversioned parent', tinman_id), 
                          ('missing parent', tinman_id)])
        transform.adjust_path('name', lion_id, trans_id2)
        self.assertEqual(transform.find_conflicts(), 
                         [('unversioned parent', lion_id),
                          ('missing parent', lion_id)])
        transform.version_file("Courage", lion_id)
        self.assertEqual(transform.find_conflicts(), 
                         [('missing parent', lion_id), 
                          ('versioning no contents', lion_id)])
        transform.adjust_path('name2', root, trans_id2)
        self.assertEqual(transform.find_conflicts(), 
                         [('versioning no contents', lion_id)])
        transform.create_file('Contents, okay?', lion_id)
        transform.adjust_path('name2', trans_id2, trans_id2)
        self.assertEqual(transform.find_conflicts(), 
                         [('parent loop', trans_id2), 
                          ('non-directory parent', trans_id2)])
        transform.adjust_path('name2', root, trans_id2)
        oz_id = transform.new_directory('oz', root)
        transform.set_executability(True, oz_id)
        self.assertEqual(transform.find_conflicts(), 
                         [('unversioned executability', oz_id)])
        transform.version_file('oz-id', oz_id)
        self.assertEqual(transform.find_conflicts(), 
                         [('non-file executability', oz_id)])
        transform.set_executability(None, oz_id)
        tip_id = transform.new_file('tip', oz_id, 'ozma', 'tip-id')
        transform.apply()
        self.assertEqual(self.wt.path2id('name'), 'my_pretties')
        self.assertEqual('contents', file(self.wt.abspath('name')).read())
        transform2, root = self.get_transform()
        oz_id = transform2.trans_id_tree_file_id('oz-id')
        newtip = transform2.new_file('tip', oz_id, 'other', 'tip-id')
        result = transform2.find_conflicts()
        fp = FinalPaths(transform2)
        self.assert_('oz/tip' in transform2._tree_path_ids)
        self.assertEqual(fp.get_path(newtip), pathjoin('oz', 'tip'))
        self.assertEqual(len(result), 2)
        self.assertEqual((result[0][0], result[0][1]), 
                         ('duplicate', newtip))
        self.assertEqual((result[1][0], result[1][2]), 
                         ('duplicate id', newtip))
        transform2.finalize()
        transform3 = TreeTransform(self.wt)
        self.addCleanup(transform3.finalize)
        oz_id = transform3.trans_id_tree_file_id('oz-id')
        transform3.delete_contents(oz_id)
        self.assertEqual(transform3.find_conflicts(), 
                         [('missing parent', oz_id)])
        root_id = transform3.root
        tip_id = transform3.trans_id_tree_file_id('tip-id')
        transform3.adjust_path('tip', root_id, tip_id)
        transform3.apply()

    def test_add_del(self):
        start, root = self.get_transform()
        start.new_directory('a', root, 'a')
        start.apply()
        transform, root = self.get_transform()
        transform.delete_versioned(transform.trans_id_tree_file_id('a'))
        transform.new_directory('a', root, 'a')
        transform.apply()

    def test_unversioning(self):
        create_tree, root = self.get_transform()
        parent_id = create_tree.new_directory('parent', root, 'parent-id')
        create_tree.new_file('child', parent_id, 'child', 'child-id')
        create_tree.apply()
        unversion = TreeTransform(self.wt)
        self.addCleanup(unversion.finalize)
        parent = unversion.trans_id_tree_path('parent')
        unversion.unversion_file(parent)
        self.assertEqual(unversion.find_conflicts(), 
                         [('unversioned parent', parent_id)])
        file_id = unversion.trans_id_tree_file_id('child-id')
        unversion.unversion_file(file_id)
        unversion.apply()

    def test_name_invariants(self):
        create_tree, root = self.get_transform()
        # prepare tree
        root = create_tree.root
        create_tree.new_file('name1', root, 'hello1', 'name1')
        create_tree.new_file('name2', root, 'hello2', 'name2')
        ddir = create_tree.new_directory('dying_directory', root, 'ddir')
        create_tree.new_file('dying_file', ddir, 'goodbye1', 'dfile')
        create_tree.new_file('moving_file', ddir, 'later1', 'mfile')
        create_tree.new_file('moving_file2', root, 'later2', 'mfile2')
        create_tree.apply()

        mangle_tree,root = self.get_transform()
        root = mangle_tree.root
        #swap names
        name1 = mangle_tree.trans_id_tree_file_id('name1')
        name2 = mangle_tree.trans_id_tree_file_id('name2')
        mangle_tree.adjust_path('name2', root, name1)
        mangle_tree.adjust_path('name1', root, name2)

        #tests for deleting parent directories 
        ddir = mangle_tree.trans_id_tree_file_id('ddir')
        mangle_tree.delete_contents(ddir)
        dfile = mangle_tree.trans_id_tree_file_id('dfile')
        mangle_tree.delete_versioned(dfile)
        mangle_tree.unversion_file(dfile)
        mfile = mangle_tree.trans_id_tree_file_id('mfile')
        mangle_tree.adjust_path('mfile', root, mfile)

        #tests for adding parent directories
        newdir = mangle_tree.new_directory('new_directory', root, 'newdir')
        mfile2 = mangle_tree.trans_id_tree_file_id('mfile2')
        mangle_tree.adjust_path('mfile2', newdir, mfile2)
        mangle_tree.new_file('newfile', newdir, 'hello3', 'dfile')
        self.assertEqual(mangle_tree.final_file_id(mfile2), 'mfile2')
        self.assertEqual(mangle_tree.final_parent(mfile2), newdir)
        self.assertEqual(mangle_tree.final_file_id(mfile2), 'mfile2')
        mangle_tree.apply()
        self.assertEqual(file(self.wt.abspath('name1')).read(), 'hello2')
        self.assertEqual(file(self.wt.abspath('name2')).read(), 'hello1')
        mfile2_path = self.wt.abspath(pathjoin('new_directory','mfile2'))
        self.assertEqual(mangle_tree.final_parent(mfile2), newdir)
        self.assertEqual(file(mfile2_path).read(), 'later2')
        self.assertEqual(self.wt.id2path('mfile2'), 'new_directory/mfile2')
        self.assertEqual(self.wt.path2id('new_directory/mfile2'), 'mfile2')
        newfile_path = self.wt.abspath(pathjoin('new_directory','newfile'))
        self.assertEqual(file(newfile_path).read(), 'hello3')
        self.assertEqual(self.wt.path2id('dying_directory'), 'ddir')
        self.assertIs(self.wt.path2id('dying_directory/dying_file'), None)
        mfile2_path = self.wt.abspath(pathjoin('new_directory','mfile2'))

    def test_both_rename(self):
        create_tree,root = self.get_transform()
        newdir = create_tree.new_directory('selftest', root, 'selftest-id')
        create_tree.new_file('blackbox.py', newdir, 'hello1', 'blackbox-id')
        create_tree.apply()        
        mangle_tree,root = self.get_transform()
        selftest = mangle_tree.trans_id_tree_file_id('selftest-id')
        blackbox = mangle_tree.trans_id_tree_file_id('blackbox-id')
        mangle_tree.adjust_path('test', root, selftest)
        mangle_tree.adjust_path('test_too_much', root, selftest)
        mangle_tree.set_executability(True, blackbox)
        mangle_tree.apply()

    def test_both_rename2(self):
        create_tree,root = self.get_transform()
        bzrlib = create_tree.new_directory('bzrlib', root, 'bzrlib-id')
        tests = create_tree.new_directory('tests', bzrlib, 'tests-id')
        blackbox = create_tree.new_directory('blackbox', tests, 'blackbox-id')
        create_tree.new_file('test_too_much.py', blackbox, 'hello1', 
                             'test_too_much-id')
        create_tree.apply()        
        mangle_tree,root = self.get_transform()
        bzrlib = mangle_tree.trans_id_tree_file_id('bzrlib-id')
        tests = mangle_tree.trans_id_tree_file_id('tests-id')
        test_too_much = mangle_tree.trans_id_tree_file_id('test_too_much-id')
        mangle_tree.adjust_path('selftest', bzrlib, tests)
        mangle_tree.adjust_path('blackbox.py', tests, test_too_much) 
        mangle_tree.set_executability(True, test_too_much)
        mangle_tree.apply()

    def test_both_rename3(self):
        create_tree,root = self.get_transform()
        tests = create_tree.new_directory('tests', root, 'tests-id')
        create_tree.new_file('test_too_much.py', tests, 'hello1', 
                             'test_too_much-id')
        create_tree.apply()        
        mangle_tree,root = self.get_transform()
        tests = mangle_tree.trans_id_tree_file_id('tests-id')
        test_too_much = mangle_tree.trans_id_tree_file_id('test_too_much-id')
        mangle_tree.adjust_path('selftest', root, tests)
        mangle_tree.adjust_path('blackbox.py', tests, test_too_much) 
        mangle_tree.set_executability(True, test_too_much)
        mangle_tree.apply()

    def test_move_dangling_ie(self):
        create_tree, root = self.get_transform()
        # prepare tree
        root = create_tree.root
        create_tree.new_file('name1', root, 'hello1', 'name1')
        create_tree.apply()
        delete_contents, root = self.get_transform()
        file = delete_contents.trans_id_tree_file_id('name1')
        delete_contents.delete_contents(file)
        delete_contents.apply()
        move_id, root = self.get_transform()
        name1 = move_id.trans_id_tree_file_id('name1')
        newdir = move_id.new_directory('dir', root, 'newdir')
        move_id.adjust_path('name2', newdir, name1)
        move_id.apply()
        
    def test_replace_dangling_ie(self):
        create_tree, root = self.get_transform()
        # prepare tree
        root = create_tree.root
        create_tree.new_file('name1', root, 'hello1', 'name1')
        create_tree.apply()
        delete_contents = TreeTransform(self.wt)
        self.addCleanup(delete_contents.finalize)
        file = delete_contents.trans_id_tree_file_id('name1')
        delete_contents.delete_contents(file)
        delete_contents.apply()
        delete_contents.finalize()
        replace = TreeTransform(self.wt)
        self.addCleanup(replace.finalize)
        name2 = replace.new_file('name2', root, 'hello2', 'name1')
        conflicts = replace.find_conflicts()
        name1 = replace.trans_id_tree_file_id('name1')
        self.assertEqual(conflicts, [('duplicate id', name1, name2)])
        resolve_conflicts(replace)
        replace.apply()

    def test_symlinks(self):
        if not has_symlinks():
            raise TestSkipped('Symlinks are not supported on this platform')
        transform,root = self.get_transform()
        oz_id = transform.new_directory('oz', root, 'oz-id')
        wizard = transform.new_symlink('wizard', oz_id, 'wizard-target', 
                                       'wizard-id')
        wiz_id = transform.create_path('wizard2', oz_id)
        transform.create_symlink('behind_curtain', wiz_id)
        transform.version_file('wiz-id2', wiz_id)            
        transform.set_executability(True, wiz_id)
        self.assertEqual(transform.find_conflicts(), 
                         [('non-file executability', wiz_id)])
        transform.set_executability(None, wiz_id)
        transform.apply()
        self.assertEqual(self.wt.path2id('oz/wizard'), 'wizard-id')
        self.assertEqual(file_kind(self.wt.abspath('oz/wizard')), 'symlink')
        self.assertEqual(os.readlink(self.wt.abspath('oz/wizard2')), 
                         'behind_curtain')
        self.assertEqual(os.readlink(self.wt.abspath('oz/wizard')),
                         'wizard-target')

    def get_conflicted(self):
        create,root = self.get_transform()
        create.new_file('dorothy', root, 'dorothy', 'dorothy-id')
        oz = create.new_directory('oz', root, 'oz-id')
        create.new_directory('emeraldcity', oz, 'emerald-id')
        create.apply()
        conflicts,root = self.get_transform()
        # set up duplicate entry, duplicate id
        new_dorothy = conflicts.new_file('dorothy', root, 'dorothy', 
                                         'dorothy-id')
        old_dorothy = conflicts.trans_id_tree_file_id('dorothy-id')
        oz = conflicts.trans_id_tree_file_id('oz-id')
        # set up DeletedParent parent conflict
        conflicts.delete_versioned(oz)
        emerald = conflicts.trans_id_tree_file_id('emerald-id')
        # set up MissingParent conflict
        munchkincity = conflicts.trans_id_file_id('munchkincity-id')
        conflicts.adjust_path('munchkincity', root, munchkincity)
        conflicts.new_directory('auntem', munchkincity, 'auntem-id')
        # set up parent loop
        conflicts.adjust_path('emeraldcity', emerald, emerald)
        return conflicts, emerald, oz, old_dorothy, new_dorothy

    def test_conflict_resolution(self):
        conflicts, emerald, oz, old_dorothy, new_dorothy =\
            self.get_conflicted()
        resolve_conflicts(conflicts)
        self.assertEqual(conflicts.final_name(old_dorothy), 'dorothy.moved')
        self.assertIs(conflicts.final_file_id(old_dorothy), None)
        self.assertEqual(conflicts.final_name(new_dorothy), 'dorothy')
        self.assertEqual(conflicts.final_file_id(new_dorothy), 'dorothy-id')
        self.assertEqual(conflicts.final_parent(emerald), oz)
        conflicts.apply()

    def test_cook_conflicts(self):
        tt, emerald, oz, old_dorothy, new_dorothy = self.get_conflicted()
        raw_conflicts = resolve_conflicts(tt)
        cooked_conflicts = cook_conflicts(raw_conflicts, tt)
        duplicate = DuplicateEntry('Moved existing file to', 'dorothy.moved', 
                                   'dorothy', None, 'dorothy-id')
        self.assertEqual(cooked_conflicts[0], duplicate)
        duplicate_id = DuplicateID('Unversioned existing file', 
                                   'dorothy.moved', 'dorothy', None,
                                   'dorothy-id')
        self.assertEqual(cooked_conflicts[1], duplicate_id)
        missing_parent = MissingParent('Created directory', 'munchkincity',
                                       'munchkincity-id')
        deleted_parent = DeletingParent('Not deleting', 'oz', 'oz-id')
        self.assertEqual(cooked_conflicts[2], missing_parent)
        unversioned_parent = UnversionedParent('Versioned directory',
                                               'munchkincity',
                                               'munchkincity-id')
        unversioned_parent2 = UnversionedParent('Versioned directory', 'oz',
                                               'oz-id')
        self.assertEqual(cooked_conflicts[3], unversioned_parent)
        parent_loop = ParentLoop('Cancelled move', 'oz/emeraldcity', 
                                 'oz/emeraldcity', 'emerald-id', 'emerald-id')
        self.assertEqual(cooked_conflicts[4], deleted_parent)
        self.assertEqual(cooked_conflicts[5], unversioned_parent2)
        self.assertEqual(cooked_conflicts[6], parent_loop)
        self.assertEqual(len(cooked_conflicts), 7)
        tt.finalize()

    def test_string_conflicts(self):
        tt, emerald, oz, old_dorothy, new_dorothy = self.get_conflicted()
        raw_conflicts = resolve_conflicts(tt)
        cooked_conflicts = cook_conflicts(raw_conflicts, tt)
        tt.finalize()
        conflicts_s = [str(c) for c in cooked_conflicts]
        self.assertEqual(len(cooked_conflicts), len(conflicts_s))
        self.assertEqual(conflicts_s[0], 'Conflict adding file dorothy.  '
                                         'Moved existing file to '
                                         'dorothy.moved.')
        self.assertEqual(conflicts_s[1], 'Conflict adding id to dorothy.  '
                                         'Unversioned existing file '
                                         'dorothy.moved.')
        self.assertEqual(conflicts_s[2], 'Conflict adding files to'
                                         ' munchkincity.  Created directory.')
        self.assertEqual(conflicts_s[3], 'Conflict because munchkincity is not'
                                         ' versioned, but has versioned'
                                         ' children.  Versioned directory.')
        self.assertEqualDiff(conflicts_s[4], "Conflict: can't delete oz because it"
                                         " is not empty.  Not deleting.")
        self.assertEqual(conflicts_s[5], 'Conflict because oz is not'
                                         ' versioned, but has versioned'
                                         ' children.  Versioned directory.')
        self.assertEqual(conflicts_s[6], 'Conflict moving oz/emeraldcity into'
                                         ' oz/emeraldcity.  Cancelled move.')

    def test_moving_versioned_directories(self):
        create, root = self.get_transform()
        kansas = create.new_directory('kansas', root, 'kansas-id')
        create.new_directory('house', kansas, 'house-id')
        create.new_directory('oz', root, 'oz-id')
        create.apply()
        cyclone, root = self.get_transform()
        oz = cyclone.trans_id_tree_file_id('oz-id')
        house = cyclone.trans_id_tree_file_id('house-id')
        cyclone.adjust_path('house', oz, house)
        cyclone.apply()

    def test_moving_root(self):
        create, root = self.get_transform()
        fun = create.new_directory('fun', root, 'fun-id')
        create.new_directory('sun', root, 'sun-id')
        create.new_directory('moon', root, 'moon')
        create.apply()
        transform, root = self.get_transform()
        transform.adjust_root_path('oldroot', fun)
        new_root=transform.trans_id_tree_path('')
        transform.version_file('new-root', new_root)
        transform.apply()

    def test_renames(self):
        create, root = self.get_transform()
        old = create.new_directory('old-parent', root, 'old-id')
        intermediate = create.new_directory('intermediate', old, 'im-id')
        myfile = create.new_file('myfile', intermediate, 'myfile-text',
                                 'myfile-id')
        create.apply()
        rename, root = self.get_transform()
        old = rename.trans_id_file_id('old-id')
        rename.adjust_path('new', root, old)
        myfile = rename.trans_id_file_id('myfile-id')
        rename.set_executability(True, myfile)
        rename.apply()

    def test_find_interesting(self):
        create, root = self.get_transform()
        wt = create._tree
        create.new_file('vfile', root, 'myfile-text', 'myfile-id')
        create.new_file('uvfile', root, 'othertext')
        create.apply()
        result = self.applyDeprecated(symbol_versioning.zero_fifteen,
            find_interesting, wt, wt, ['vfile'])
        self.assertEqual(result, set(['myfile-id']))

    def test_set_executability_order(self):
        """Ensure that executability behaves the same, no matter what order.
        
        - create file and set executability simultaneously
        - create file and set executability afterward
        - unsetting the executability of a file whose executability has not been
        declared should throw an exception (this may happen when a
        merge attempts to create a file with a duplicate ID)
        """
        transform, root = self.get_transform()
        wt = transform._tree
        transform.new_file('set_on_creation', root, 'Set on creation', 'soc',
                           True)
        sac = transform.new_file('set_after_creation', root,
                                 'Set after creation', 'sac')
        transform.set_executability(True, sac)
        uws = transform.new_file('unset_without_set', root, 'Unset badly',
                                 'uws')
        self.assertRaises(KeyError, transform.set_executability, None, uws)
        transform.apply()
        self.assertTrue(wt.is_executable('soc'))
        self.assertTrue(wt.is_executable('sac'))

    def test_preserve_mode(self):
        """File mode is preserved when replacing content"""
        if sys.platform == 'win32':
            raise TestSkipped('chmod has no effect on win32')
        transform, root = self.get_transform()
        transform.new_file('file1', root, 'contents', 'file1-id', True)
        transform.apply()
        self.assertTrue(self.wt.is_executable('file1-id'))
        transform, root = self.get_transform()
        file1_id = transform.trans_id_tree_file_id('file1-id')
        transform.delete_contents(file1_id)
        transform.create_file('contents2', file1_id)
        transform.apply()
        self.assertTrue(self.wt.is_executable('file1-id'))

    def test__set_mode_stats_correctly(self):
        """_set_mode stats to determine file mode."""
        if sys.platform == 'win32':
            raise TestSkipped('chmod has no effect on win32')

        stat_paths = []
        real_stat = os.stat
        def instrumented_stat(path):
            stat_paths.append(path)
            return real_stat(path)

        transform, root = self.get_transform()

        bar1_id = transform.new_file('bar', root, 'bar contents 1\n',
                                     file_id='bar-id-1', executable=False)
        transform.apply()

        transform, root = self.get_transform()
        bar1_id = transform.trans_id_tree_path('bar')
        bar2_id = transform.trans_id_tree_path('bar2')
        try:
            os.stat = instrumented_stat
            transform.create_file('bar2 contents\n', bar2_id, mode_id=bar1_id)
        finally:
            os.stat = real_stat
            transform.finalize()

        bar1_abspath = self.wt.abspath('bar')
        self.assertEqual([bar1_abspath], stat_paths)

    def test_iter_changes(self):
        self.wt.set_root_id('eert_toor')
        transform, root = self.get_transform()
        transform.new_file('old', root, 'blah', 'id-1', True)
        transform.apply()
        transform, root = self.get_transform()
        try:
            self.assertEqual([], list(transform._iter_changes()))
            old = transform.trans_id_tree_file_id('id-1')
            transform.unversion_file(old)
            self.assertEqual([('id-1', ('old', None), False, (True, False),
                ('eert_toor', 'eert_toor'), ('old', 'old'), ('file', 'file'),
                (True, True))], list(transform._iter_changes()))
            transform.new_directory('new', root, 'id-1')
            self.assertEqual([('id-1', ('old', 'new'), True, (True, True),
                ('eert_toor', 'eert_toor'), ('old', 'new'),
                ('file', 'directory'),
                (True, False))], list(transform._iter_changes()))
        finally:
            transform.finalize()

    def test_iter_changes_new(self):
        self.wt.set_root_id('eert_toor')
        transform, root = self.get_transform()
        transform.new_file('old', root, 'blah')
        transform.apply()
        transform, root = self.get_transform()
        try:
            old = transform.trans_id_tree_path('old')
            transform.version_file('id-1', old)
            self.assertEqual([('id-1', (None, 'old'), False, (False, True),
                ('eert_toor', 'eert_toor'), ('old', 'old'), ('file', 'file'),
                (False, False))], list(transform._iter_changes()))
        finally:
            transform.finalize()

    def test_iter_changes_modifications(self):
        self.wt.set_root_id('eert_toor')
        transform, root = self.get_transform()
        transform.new_file('old', root, 'blah', 'id-1')
        transform.new_file('new', root, 'blah')
        transform.new_directory('subdir', root, 'subdir-id')
        transform.apply()
        transform, root = self.get_transform()
        try:
            old = transform.trans_id_tree_path('old')
            subdir = transform.trans_id_tree_file_id('subdir-id')
            new = transform.trans_id_tree_path('new')
            self.assertEqual([], list(transform._iter_changes()))

            #content deletion
            transform.delete_contents(old)
            self.assertEqual([('id-1', ('old', 'old'), True, (True, True),
                ('eert_toor', 'eert_toor'), ('old', 'old'), ('file', None),
                (False, False))], list(transform._iter_changes()))

            #content change
            transform.create_file('blah', old)
            self.assertEqual([('id-1', ('old', 'old'), True, (True, True),
                ('eert_toor', 'eert_toor'), ('old', 'old'), ('file', 'file'),
                (False, False))], list(transform._iter_changes()))
            transform.cancel_deletion(old)
            self.assertEqual([('id-1', ('old', 'old'), True, (True, True),
                ('eert_toor', 'eert_toor'), ('old', 'old'), ('file', 'file'),
                (False, False))], list(transform._iter_changes()))
            transform.cancel_creation(old)

            # move file_id to a different file
            self.assertEqual([], list(transform._iter_changes()))
            transform.unversion_file(old)
            transform.version_file('id-1', new)
            transform.adjust_path('old', root, new)
            self.assertEqual([('id-1', ('old', 'old'), True, (True, True),
                ('eert_toor', 'eert_toor'), ('old', 'old'), ('file', 'file'),
                (False, False))], list(transform._iter_changes()))
            transform.cancel_versioning(new)
            transform._removed_id = set()

            #execute bit
            self.assertEqual([], list(transform._iter_changes()))
            transform.set_executability(True, old)
            self.assertEqual([('id-1', ('old', 'old'), False, (True, True),
                ('eert_toor', 'eert_toor'), ('old', 'old'), ('file', 'file'),
                (False, True))], list(transform._iter_changes()))
            transform.set_executability(None, old)

            # filename
            self.assertEqual([], list(transform._iter_changes()))
            transform.adjust_path('new', root, old)
            transform._new_parent = {}
            self.assertEqual([('id-1', ('old', 'new'), False, (True, True),
                ('eert_toor', 'eert_toor'), ('old', 'new'), ('file', 'file'),
                (False, False))], list(transform._iter_changes()))
            transform._new_name = {}

            # parent directory
            self.assertEqual([], list(transform._iter_changes()))
            transform.adjust_path('new', subdir, old)
            transform._new_name = {}
            self.assertEqual([('id-1', ('old', 'subdir/old'), False,
                (True, True), ('eert_toor', 'subdir-id'), ('old', 'old'),
                ('file', 'file'), (False, False))],
                list(transform._iter_changes()))
            transform._new_path = {}

        finally:
            transform.finalize()

    def test_iter_changes_modified_bleed(self):
        self.wt.set_root_id('eert_toor')
        """Modified flag should not bleed from one change to another"""
        # unfortunately, we have no guarantee that file1 (which is modified)
        # will be applied before file2.  And if it's applied after file2, it
        # obviously can't bleed into file2's change output.  But for now, it
        # works.
        transform, root = self.get_transform()
        transform.new_file('file1', root, 'blah', 'id-1')
        transform.new_file('file2', root, 'blah', 'id-2')
        transform.apply()
        transform, root = self.get_transform()
        try:
            transform.delete_contents(transform.trans_id_file_id('id-1'))
            transform.set_executability(True,
            transform.trans_id_file_id('id-2'))
            self.assertEqual([('id-1', (u'file1', u'file1'), True, (True, True),
                ('eert_toor', 'eert_toor'), ('file1', u'file1'),
                ('file', None), (False, False)),
                ('id-2', (u'file2', u'file2'), False, (True, True),
                ('eert_toor', 'eert_toor'), ('file2', u'file2'),
                ('file', 'file'), (False, True))],
                list(transform._iter_changes()))
        finally:
            transform.finalize()

    def test_iter_changes_move_missing(self):
        """Test moving ids with no files around"""
        self.wt.set_root_id('toor_eert')
        # Need two steps because versioning a non-existant file is a conflict.
        transform, root = self.get_transform()
        transform.new_directory('floater', root, 'floater-id')
        transform.apply()
        transform, root = self.get_transform()
        transform.delete_contents(transform.trans_id_tree_path('floater'))
        transform.apply()
        transform, root = self.get_transform()
        floater = transform.trans_id_tree_path('floater')
        try:
            transform.adjust_path('flitter', root, floater)
            self.assertEqual([('floater-id', ('floater', 'flitter'), False,
            (True, True), ('toor_eert', 'toor_eert'), ('floater', 'flitter'),
            (None, None), (False, False))], list(transform._iter_changes()))
        finally:
            transform.finalize()

    def test_iter_changes_pointless(self):
        """Ensure that no-ops are not treated as modifications"""
        self.wt.set_root_id('eert_toor')
        transform, root = self.get_transform()
        transform.new_file('old', root, 'blah', 'id-1')
        transform.new_directory('subdir', root, 'subdir-id')
        transform.apply()
        transform, root = self.get_transform()
        try:
            old = transform.trans_id_tree_path('old')
            subdir = transform.trans_id_tree_file_id('subdir-id')
            self.assertEqual([], list(transform._iter_changes()))
            transform.delete_contents(subdir)
            transform.create_directory(subdir)
            transform.set_executability(False, old)
            transform.unversion_file(old)
            transform.version_file('id-1', old)
            transform.adjust_path('old', root, old)
            self.assertEqual([], list(transform._iter_changes()))
        finally:
            transform.finalize()

    def test_rename_count(self):
        transform, root = self.get_transform()
        transform.new_file('name1', root, 'contents')
        self.assertEqual(transform.rename_count, 0)
        transform.apply()
        self.assertEqual(transform.rename_count, 1)
        transform2, root = self.get_transform()
        transform2.adjust_path('name2', root,
                               transform2.trans_id_tree_path('name1'))
        self.assertEqual(transform2.rename_count, 0)
        transform2.apply()
        self.assertEqual(transform2.rename_count, 2)

    def test_change_parent(self):
        """Ensure that after we change a parent, the results are still right.

        Renames and parent changes on pending transforms can happen as part
        of conflict resolution, and are explicitly permitted by the
        TreeTransform API.

        This test ensures they work correctly with the rename-avoidance
        optimization.
        """
        transform, root = self.get_transform()
        parent1 = transform.new_directory('parent1', root)
        child1 = transform.new_file('child1', parent1, 'contents')
        parent2 = transform.new_directory('parent2', root)
        transform.adjust_path('child1', parent2, child1)
        transform.apply()
        self.failIfExists(self.wt.abspath('parent1/child1'))
        self.failUnlessExists(self.wt.abspath('parent2/child1'))
        # rename limbo/new-1 => parent1, rename limbo/new-3 => parent2
        # no rename for child1 (counting only renames during apply)
        self.failUnlessEqual(2, transform.rename_count)

    def test_cancel_parent(self):
        """Cancelling a parent doesn't cause deletion of a non-empty directory

        This is like the test_change_parent, except that we cancel the parent
        before adjusting the path.  The transform must detect that the
        directory is non-empty, and move children to safe locations.
        """
        transform, root = self.get_transform()
        parent1 = transform.new_directory('parent1', root)
        child1 = transform.new_file('child1', parent1, 'contents')
        child2 = transform.new_file('child2', parent1, 'contents')
        try:
            transform.cancel_creation(parent1)
        except OSError:
            self.fail('Failed to move child1 before deleting parent1')
        transform.cancel_creation(child2)
        transform.create_directory(parent1)
        try:
            transform.cancel_creation(parent1)
        # If the transform incorrectly believes that child2 is still in
        # parent1's limbo directory, it will try to rename it and fail
        # because was already moved by the first cancel_creation.
        except OSError:
            self.fail('Transform still thinks child2 is a child of parent1')
        parent2 = transform.new_directory('parent2', root)
        transform.adjust_path('child1', parent2, child1)
        transform.apply()
        self.failIfExists(self.wt.abspath('parent1'))
        self.failUnlessExists(self.wt.abspath('parent2/child1'))
        # rename limbo/new-3 => parent2, rename limbo/new-2 => child1
        self.failUnlessEqual(2, transform.rename_count)

    def test_adjust_and_cancel(self):
        """Make sure adjust_path keeps track of limbo children properly"""
        transform, root = self.get_transform()
        parent1 = transform.new_directory('parent1', root)
        child1 = transform.new_file('child1', parent1, 'contents')
        parent2 = transform.new_directory('parent2', root)
        transform.adjust_path('child1', parent2, child1)
        transform.cancel_creation(child1)
        try:
            transform.cancel_creation(parent1)
        # if the transform thinks child1 is still in parent1's limbo
        # directory, it will attempt to move it and fail.
        except OSError:
            self.fail('Transform still thinks child1 is a child of parent1')
        transform.finalize()

    def test_noname_contents(self):
        """TreeTransform should permit deferring naming files."""
        transform, root = self.get_transform()
        parent = transform.trans_id_file_id('parent-id')
        try:
            transform.create_directory(parent)
        except KeyError:
            self.fail("Can't handle contents with no name")
        transform.finalize()

    def test_noname_contents_nested(self):
        """TreeTransform should permit deferring naming files."""
        transform, root = self.get_transform()
        parent = transform.trans_id_file_id('parent-id')
        try:
            transform.create_directory(parent)
        except KeyError:
            self.fail("Can't handle contents with no name")
        child = transform.new_directory('child', parent)
        transform.adjust_path('parent', root, parent)
        transform.apply()
        self.failUnlessExists(self.wt.abspath('parent/child'))
        self.assertEqual(1, transform.rename_count)

    def test_reuse_name(self):
        """Avoid reusing the same limbo name for different files"""
        transform, root = self.get_transform()
        parent = transform.new_directory('parent', root)
        child1 = transform.new_directory('child', parent)
        try:
            child2 = transform.new_directory('child', parent)
        except OSError:
            self.fail('Tranform tried to use the same limbo name twice')
        transform.adjust_path('child2', parent, child2)
        transform.apply()
        # limbo/new-1 => parent, limbo/new-3 => parent/child2
        # child2 is put into top-level limbo because child1 has already
        # claimed the direct limbo path when child2 is created.  There is no
        # advantage in renaming files once they're in top-level limbo, except
        # as part of apply.
        self.assertEqual(2, transform.rename_count)

    def test_reuse_when_first_moved(self):
        """Don't avoid direct paths when it is safe to use them"""
        transform, root = self.get_transform()
        parent = transform.new_directory('parent', root)
        child1 = transform.new_directory('child', parent)
        transform.adjust_path('child1', parent, child1)
        child2 = transform.new_directory('child', parent)
        transform.apply()
        # limbo/new-1 => parent
        self.assertEqual(1, transform.rename_count)

    def test_reuse_after_cancel(self):
        """Don't avoid direct paths when it is safe to use them"""
        transform, root = self.get_transform()
        parent2 = transform.new_directory('parent2', root)
        child1 = transform.new_directory('child1', parent2)
        transform.cancel_creation(parent2)
        transform.create_directory(parent2)
        child2 = transform.new_directory('child1', parent2)
        transform.adjust_path('child2', parent2, child1)
        transform.apply()
        # limbo/new-1 => parent2, limbo/new-2 => parent2/child1
        self.assertEqual(2, transform.rename_count)

    def test_finalize_order(self):
        """Finalize must be done in child-to-parent order"""
        transform, root = self.get_transform()
        parent = transform.new_directory('parent', root)
        child = transform.new_directory('child', parent)
        try:
            transform.finalize()
        except OSError:
            self.fail('Tried to remove parent before child1')

    def test_cancel_with_cancelled_child_should_succeed(self):
        transform, root = self.get_transform()
        parent = transform.new_directory('parent', root)
        child = transform.new_directory('child', parent)
        transform.cancel_creation(child)
        transform.cancel_creation(parent)
        transform.finalize()

    def test_change_entry(self):
        txt = 'bzrlib.transform.change_entry was deprecated in version 0.90.'
        self.callDeprecated([txt], change_entry, None, None, None, None, None,
            None, None, None)


class TransformGroup(object):
    def __init__(self, dirname, root_id):
        self.name = dirname
        os.mkdir(dirname)
        self.wt = BzrDir.create_standalone_workingtree(dirname)
        self.wt.set_root_id(root_id)
        self.b = self.wt.branch
        self.tt = TreeTransform(self.wt)
        self.root = self.tt.trans_id_tree_file_id(self.wt.get_root_id())


def conflict_text(tree, merge):
    template = '%s TREE\n%s%s\n%s%s MERGE-SOURCE\n'
    return template % ('<' * 7, tree, '=' * 7, merge, '>' * 7)


class TestTransformMerge(TestCaseInTempDir):
    def test_text_merge(self):
        root_id = generate_ids.gen_root_id()
        base = TransformGroup("base", root_id)
        base.tt.new_file('a', base.root, 'a\nb\nc\nd\be\n', 'a')
        base.tt.new_file('b', base.root, 'b1', 'b')
        base.tt.new_file('c', base.root, 'c', 'c')
        base.tt.new_file('d', base.root, 'd', 'd')
        base.tt.new_file('e', base.root, 'e', 'e')
        base.tt.new_file('f', base.root, 'f', 'f')
        base.tt.new_directory('g', base.root, 'g')
        base.tt.new_directory('h', base.root, 'h')
        base.tt.apply()
        other = TransformGroup("other", root_id)
        other.tt.new_file('a', other.root, 'y\nb\nc\nd\be\n', 'a')
        other.tt.new_file('b', other.root, 'b2', 'b')
        other.tt.new_file('c', other.root, 'c2', 'c')
        other.tt.new_file('d', other.root, 'd', 'd')
        other.tt.new_file('e', other.root, 'e2', 'e')
        other.tt.new_file('f', other.root, 'f', 'f')
        other.tt.new_file('g', other.root, 'g', 'g')
        other.tt.new_file('h', other.root, 'h\ni\nj\nk\n', 'h')
        other.tt.new_file('i', other.root, 'h\ni\nj\nk\n', 'i')
        other.tt.apply()
        this = TransformGroup("this", root_id)
        this.tt.new_file('a', this.root, 'a\nb\nc\nd\bz\n', 'a')
        this.tt.new_file('b', this.root, 'b', 'b')
        this.tt.new_file('c', this.root, 'c', 'c')
        this.tt.new_file('d', this.root, 'd2', 'd')
        this.tt.new_file('e', this.root, 'e2', 'e')
        this.tt.new_file('f', this.root, 'f', 'f')
        this.tt.new_file('g', this.root, 'g', 'g')
        this.tt.new_file('h', this.root, '1\n2\n3\n4\n', 'h')
        this.tt.new_file('i', this.root, '1\n2\n3\n4\n', 'i')
        this.tt.apply()
        Merge3Merger(this.wt, this.wt, base.wt, other.wt)
        # textual merge
        self.assertEqual(this.wt.get_file('a').read(), 'y\nb\nc\nd\bz\n')
        # three-way text conflict
        self.assertEqual(this.wt.get_file('b').read(), 
                         conflict_text('b', 'b2'))
        # OTHER wins
        self.assertEqual(this.wt.get_file('c').read(), 'c2')
        # THIS wins
        self.assertEqual(this.wt.get_file('d').read(), 'd2')
        # Ambigious clean merge
        self.assertEqual(this.wt.get_file('e').read(), 'e2')
        # No change
        self.assertEqual(this.wt.get_file('f').read(), 'f')
        # Correct correct results when THIS == OTHER 
        self.assertEqual(this.wt.get_file('g').read(), 'g')
        # Text conflict when THIS & OTHER are text and BASE is dir
        self.assertEqual(this.wt.get_file('h').read(), 
                         conflict_text('1\n2\n3\n4\n', 'h\ni\nj\nk\n'))
        self.assertEqual(this.wt.get_file_byname('h.THIS').read(),
                         '1\n2\n3\n4\n')
        self.assertEqual(this.wt.get_file_byname('h.OTHER').read(),
                         'h\ni\nj\nk\n')
        self.assertEqual(file_kind(this.wt.abspath('h.BASE')), 'directory')
        self.assertEqual(this.wt.get_file('i').read(), 
                         conflict_text('1\n2\n3\n4\n', 'h\ni\nj\nk\n'))
        self.assertEqual(this.wt.get_file_byname('i.THIS').read(),
                         '1\n2\n3\n4\n')
        self.assertEqual(this.wt.get_file_byname('i.OTHER').read(),
                         'h\ni\nj\nk\n')
        self.assertEqual(os.path.exists(this.wt.abspath('i.BASE')), False)
        modified = ['a', 'b', 'c', 'h', 'i']
        merge_modified = this.wt.merge_modified()
        self.assertSubset(merge_modified, modified)
        self.assertEqual(len(merge_modified), len(modified))
        file(this.wt.id2abspath('a'), 'wb').write('booga')
        modified.pop(0)
        merge_modified = this.wt.merge_modified()
        self.assertSubset(merge_modified, modified)
        self.assertEqual(len(merge_modified), len(modified))
        this.wt.remove('b')
        this.wt.revert([])

    def test_file_merge(self):
        if not has_symlinks():
            raise TestSkipped('Symlinks are not supported on this platform')
        root_id = generate_ids.gen_root_id()
        base = TransformGroup("BASE", root_id)
        this = TransformGroup("THIS", root_id)
        other = TransformGroup("OTHER", root_id)
        for tg in this, base, other:
            tg.tt.new_directory('a', tg.root, 'a')
            tg.tt.new_symlink('b', tg.root, 'b', 'b')
            tg.tt.new_file('c', tg.root, 'c', 'c')
            tg.tt.new_symlink('d', tg.root, tg.name, 'd')
        targets = ((base, 'base-e', 'base-f', None, None), 
                   (this, 'other-e', 'this-f', 'other-g', 'this-h'), 
                   (other, 'other-e', None, 'other-g', 'other-h'))
        for tg, e_target, f_target, g_target, h_target in targets:
            for link, target in (('e', e_target), ('f', f_target), 
                                 ('g', g_target), ('h', h_target)):
                if target is not None:
                    tg.tt.new_symlink(link, tg.root, target, link)

        for tg in this, base, other:
            tg.tt.apply()
        Merge3Merger(this.wt, this.wt, base.wt, other.wt)
        self.assertIs(os.path.isdir(this.wt.abspath('a')), True)
        self.assertIs(os.path.islink(this.wt.abspath('b')), True)
        self.assertIs(os.path.isfile(this.wt.abspath('c')), True)
        for suffix in ('THIS', 'BASE', 'OTHER'):
            self.assertEqual(os.readlink(this.wt.abspath('d.'+suffix)), suffix)
        self.assertIs(os.path.lexists(this.wt.abspath('d')), False)
        self.assertEqual(this.wt.id2path('d'), 'd.OTHER')
        self.assertEqual(this.wt.id2path('f'), 'f.THIS')
        self.assertEqual(os.readlink(this.wt.abspath('e')), 'other-e')
        self.assertIs(os.path.lexists(this.wt.abspath('e.THIS')), False)
        self.assertIs(os.path.lexists(this.wt.abspath('e.OTHER')), False)
        self.assertIs(os.path.lexists(this.wt.abspath('e.BASE')), False)
        self.assertIs(os.path.lexists(this.wt.abspath('g')), True)
        self.assertIs(os.path.lexists(this.wt.abspath('g.BASE')), False)
        self.assertIs(os.path.lexists(this.wt.abspath('h')), False)
        self.assertIs(os.path.lexists(this.wt.abspath('h.BASE')), False)
        self.assertIs(os.path.lexists(this.wt.abspath('h.THIS')), True)
        self.assertIs(os.path.lexists(this.wt.abspath('h.OTHER')), True)

    def test_filename_merge(self):
        root_id = generate_ids.gen_root_id()
        base = TransformGroup("BASE", root_id)
        this = TransformGroup("THIS", root_id)
        other = TransformGroup("OTHER", root_id)
        base_a, this_a, other_a = [t.tt.new_directory('a', t.root, 'a') 
                                   for t in [base, this, other]]
        base_b, this_b, other_b = [t.tt.new_directory('b', t.root, 'b') 
                                   for t in [base, this, other]]
        base.tt.new_directory('c', base_a, 'c')
        this.tt.new_directory('c1', this_a, 'c')
        other.tt.new_directory('c', other_b, 'c')

        base.tt.new_directory('d', base_a, 'd')
        this.tt.new_directory('d1', this_b, 'd')
        other.tt.new_directory('d', other_a, 'd')

        base.tt.new_directory('e', base_a, 'e')
        this.tt.new_directory('e', this_a, 'e')
        other.tt.new_directory('e1', other_b, 'e')

        base.tt.new_directory('f', base_a, 'f')
        this.tt.new_directory('f1', this_b, 'f')
        other.tt.new_directory('f1', other_b, 'f')

        for tg in [this, base, other]:
            tg.tt.apply()
        Merge3Merger(this.wt, this.wt, base.wt, other.wt)
        self.assertEqual(this.wt.id2path('c'), pathjoin('b/c1'))
        self.assertEqual(this.wt.id2path('d'), pathjoin('b/d1'))
        self.assertEqual(this.wt.id2path('e'), pathjoin('b/e1'))
        self.assertEqual(this.wt.id2path('f'), pathjoin('b/f1'))

    def test_filename_merge_conflicts(self):
        root_id = generate_ids.gen_root_id()
        base = TransformGroup("BASE", root_id)
        this = TransformGroup("THIS", root_id)
        other = TransformGroup("OTHER", root_id)
        base_a, this_a, other_a = [t.tt.new_directory('a', t.root, 'a') 
                                   for t in [base, this, other]]
        base_b, this_b, other_b = [t.tt.new_directory('b', t.root, 'b') 
                                   for t in [base, this, other]]

        base.tt.new_file('g', base_a, 'g', 'g')
        other.tt.new_file('g1', other_b, 'g1', 'g')

        base.tt.new_file('h', base_a, 'h', 'h')
        this.tt.new_file('h1', this_b, 'h1', 'h')

        base.tt.new_file('i', base.root, 'i', 'i')
        other.tt.new_directory('i1', this_b, 'i')

        for tg in [this, base, other]:
            tg.tt.apply()
        Merge3Merger(this.wt, this.wt, base.wt, other.wt)

        self.assertEqual(this.wt.id2path('g'), pathjoin('b/g1.OTHER'))
        self.assertIs(os.path.lexists(this.wt.abspath('b/g1.BASE')), True)
        self.assertIs(os.path.lexists(this.wt.abspath('b/g1.THIS')), False)
        self.assertEqual(this.wt.id2path('h'), pathjoin('b/h1.THIS'))
        self.assertIs(os.path.lexists(this.wt.abspath('b/h1.BASE')), True)
        self.assertIs(os.path.lexists(this.wt.abspath('b/h1.OTHER')), False)
        self.assertEqual(this.wt.id2path('i'), pathjoin('b/i1.OTHER'))


class TestBuildTree(tests.TestCaseWithTransport):

    def test_build_tree(self):
        if not has_symlinks():
            raise TestSkipped('Test requires symlink support')
        os.mkdir('a')
        a = BzrDir.create_standalone_workingtree('a')
        os.mkdir('a/foo')
        file('a/foo/bar', 'wb').write('contents')
        os.symlink('a/foo/bar', 'a/foo/baz')
        a.add(['foo', 'foo/bar', 'foo/baz'])
        a.commit('initial commit')
        b = BzrDir.create_standalone_workingtree('b')
        basis = a.basis_tree()
        basis.lock_read()
        self.addCleanup(basis.unlock)
        build_tree(basis, b)
        self.assertIs(os.path.isdir('b/foo'), True)
        self.assertEqual(file('b/foo/bar', 'rb').read(), "contents")
        self.assertEqual(os.readlink('b/foo/baz'), 'a/foo/bar')

    def test_build_with_references(self):
        tree = self.make_branch_and_tree('source',
            format='dirstate-with-subtree')
        subtree = self.make_branch_and_tree('source/subtree',
            format='dirstate-with-subtree')
        tree.add_reference(subtree)
        tree.commit('a revision')
        tree.branch.create_checkout('target')
        self.failUnlessExists('target')
        self.failUnlessExists('target/subtree')

    def test_file_conflict_handling(self):
        """Ensure that when building trees, conflict handling is done"""
        source = self.make_branch_and_tree('source')
        target = self.make_branch_and_tree('target')
        self.build_tree(['source/file', 'target/file'])
        source.add('file', 'new-file')
        source.commit('added file')
        build_tree(source.basis_tree(), target)
        self.assertEqual([DuplicateEntry('Moved existing file to',
                          'file.moved', 'file', None, 'new-file')],
                         target.conflicts())
        target2 = self.make_branch_and_tree('target2')
        target_file = file('target2/file', 'wb')
        try:
            source_file = file('source/file', 'rb')
            try:
                target_file.write(source_file.read())
            finally:
                source_file.close()
        finally:
            target_file.close()
        build_tree(source.basis_tree(), target2)
        self.assertEqual([], target2.conflicts())

    def test_symlink_conflict_handling(self):
        """Ensure that when building trees, conflict handling is done"""
        if not has_symlinks():
            raise TestSkipped('Test requires symlink support')
        source = self.make_branch_and_tree('source')
        os.symlink('foo', 'source/symlink')
        source.add('symlink', 'new-symlink')
        source.commit('added file')
        target = self.make_branch_and_tree('target')
        os.symlink('bar', 'target/symlink')
        build_tree(source.basis_tree(), target)
        self.assertEqual([DuplicateEntry('Moved existing file to',
            'symlink.moved', 'symlink', None, 'new-symlink')],
            target.conflicts())
        target = self.make_branch_and_tree('target2')
        os.symlink('foo', 'target2/symlink')
        build_tree(source.basis_tree(), target)
        self.assertEqual([], target.conflicts())
        
    def test_directory_conflict_handling(self):
        """Ensure that when building trees, conflict handling is done"""
        source = self.make_branch_and_tree('source')
        target = self.make_branch_and_tree('target')
        self.build_tree(['source/dir1/', 'source/dir1/file', 'target/dir1/'])
        source.add(['dir1', 'dir1/file'], ['new-dir1', 'new-file'])
        source.commit('added file')
        build_tree(source.basis_tree(), target)
        self.assertEqual([], target.conflicts())
        self.failUnlessExists('target/dir1/file')

        # Ensure contents are merged
        target = self.make_branch_and_tree('target2')
        self.build_tree(['target2/dir1/', 'target2/dir1/file2'])
        build_tree(source.basis_tree(), target)
        self.assertEqual([], target.conflicts())
        self.failUnlessExists('target2/dir1/file2')
        self.failUnlessExists('target2/dir1/file')

        # Ensure new contents are suppressed for existing branches
        target = self.make_branch_and_tree('target3')
        self.make_branch('target3/dir1')
        self.build_tree(['target3/dir1/file2'])
        build_tree(source.basis_tree(), target)
        self.failIfExists('target3/dir1/file')
        self.failUnlessExists('target3/dir1/file2')
        self.failUnlessExists('target3/dir1.diverted/file')
        self.assertEqual([DuplicateEntry('Diverted to',
            'dir1.diverted', 'dir1', 'new-dir1', None)],
            target.conflicts())

        target = self.make_branch_and_tree('target4')
        self.build_tree(['target4/dir1/'])
        self.make_branch('target4/dir1/file')
        build_tree(source.basis_tree(), target)
        self.failUnlessExists('target4/dir1/file')
        self.assertEqual('directory', file_kind('target4/dir1/file'))
        self.failUnlessExists('target4/dir1/file.diverted')
        self.assertEqual([DuplicateEntry('Diverted to',
            'dir1/file.diverted', 'dir1/file', 'new-file', None)],
            target.conflicts())

    def test_mixed_conflict_handling(self):
        """Ensure that when building trees, conflict handling is done"""
        source = self.make_branch_and_tree('source')
        target = self.make_branch_and_tree('target')
        self.build_tree(['source/name', 'target/name/'])
        source.add('name', 'new-name')
        source.commit('added file')
        build_tree(source.basis_tree(), target)
        self.assertEqual([DuplicateEntry('Moved existing file to',
            'name.moved', 'name', None, 'new-name')], target.conflicts())

    def test_raises_in_populated(self):
        source = self.make_branch_and_tree('source')
        self.build_tree(['source/name'])
        source.add('name')
        source.commit('added name')
        target = self.make_branch_and_tree('target')
        self.build_tree(['target/name'])
        target.add('name')
        self.assertRaises(errors.WorkingTreeAlreadyPopulated, 
            build_tree, source.basis_tree(), target)

    def test_build_tree_rename_count(self):
        source = self.make_branch_and_tree('source')
        self.build_tree(['source/file1', 'source/dir1/'])
        source.add(['file1', 'dir1'])
        source.commit('add1')
        target1 = self.make_branch_and_tree('target1')
        transform_result = build_tree(source.basis_tree(), target1)
        self.assertEqual(2, transform_result.rename_count)

        self.build_tree(['source/dir1/file2'])
        source.add(['dir1/file2'])
        source.commit('add3')
        target2 = self.make_branch_and_tree('target2')
        transform_result = build_tree(source.basis_tree(), target2)
        # children of non-root directories should not be renamed
        self.assertEqual(2, transform_result.rename_count)


class MockTransform(object):

    def has_named_child(self, by_parent, parent_id, name):
        for child_id in by_parent[parent_id]:
            if child_id == '0':
                if name == "name~":
                    return True
            elif name == "name.~%s~" % child_id:
                return True
        return False


class MockEntry(object):
    def __init__(self):
        object.__init__(self)
        self.name = "name"

class TestGetBackupName(TestCase):
    def test_get_backup_name(self):
        tt = MockTransform()
        name = get_backup_name(MockEntry(), {'a':[]}, 'a', tt)
        self.assertEqual(name, 'name.~1~')
        name = get_backup_name(MockEntry(), {'a':['1']}, 'a', tt)
        self.assertEqual(name, 'name.~2~')
        name = get_backup_name(MockEntry(), {'a':['2']}, 'a', tt)
        self.assertEqual(name, 'name.~1~')
        name = get_backup_name(MockEntry(), {'a':['2'], 'b':[]}, 'b', tt)
        self.assertEqual(name, 'name.~1~')
        name = get_backup_name(MockEntry(), {'a':['1', '2', '3']}, 'a', tt)
        self.assertEqual(name, 'name.~4~')


class TestFileMover(tests.TestCaseWithTransport):

    def test_file_mover(self):
        self.build_tree(['a/', 'a/b', 'c/', 'c/d'])
        mover = _FileMover()
        mover.rename('a', 'q')
        self.failUnlessExists('q')
        self.failIfExists('a')

    def test_file_mover_rollback(self):
        self.build_tree(['a/', 'a/b', 'c/', 'c/d/', 'c/e/'])
        mover = _FileMover()
        mover.rename('c/d', 'c/f')
        mover.rename('c/e', 'c/d')
        try:
            mover.rename('a', 'c')
        except OSError, e:
            mover.rollback()
        self.failUnlessExists('a')
        self.failUnlessExists('c/d')
