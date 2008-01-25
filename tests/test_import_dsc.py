#    test_import_dsc.py -- Test importing .dsc files.
#    Copyright (C) 2007 James Westby <jw+debian@jameswestby.net>
#    
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

import os
import shutil
import tarfile

from bzrlib.config import ConfigObj
from bzrlib.conflicts import TextConflict
from bzrlib.errors import FileExists, UncommittedChanges
from bzrlib.tests import TestCaseWithTransport
from bzrlib.workingtree import WorkingTree

from errors import ImportError, OnlyImportSingleDsc
from import_dsc import DscImporter, files_to_ignore

def write_to_file(filename, contents):
  f = open(filename, 'wb')
  try:
    f.write(contents)
  finally:
    f.close()

def append_to_file(filename, contents):
  f = open(filename, 'ab')
  try:
    f.write(contents)
  finally:
    f.close()

class TestDscImporter(TestCaseWithTransport):

  basedir = 'package'
  target = 'target'
  orig_1 = 'package_0.1.orig.tar.gz'
  orig_2 = 'package_0.2.orig.tar.gz'
  orig_3 = 'package_0.3.orig.tar.gz'
  diff_1 = 'package_0.1-1.diff.gz'
  diff_1b = 'package_0.1-2.diff.gz'
  diff_1c = 'package_0.1-3.diff.gz'
  diff_2 = 'package_0.2-1.diff.gz'
  diff_3 = 'package_0.3-1.diff.gz'
  dsc_1 = 'package_0.1-1.dsc'
  dsc_1b = 'package_0.1-2.dsc'
  dsc_1c = 'package_0.1-3.dsc'
  dsc_2 = 'package_0.2-1.dsc'
  dsc_3 = 'package_0.3-1.dsc'
  native_1 = 'package_0.1.tar.gz'
  native_2 = 'package_0.2.tar.gz'
  native_dsc_1 = 'package_0.1.dsc'
  native_dsc_2 = 'package_0.2.dsc'

  config_files = ['.bzr-builddeb/', '.bzr-builddeb/default.conf']

  def assertRulesExecutable(self, tree):
    """Checks that the debian/rules in the tree is executable"""
    tree.lock_read()
    try:
      self.assertTrue(tree.is_executable(tree.path2id('debian/rules')))
    finally:
      tree.unlock()

  def make_base_package(self):
    os.mkdir(self.basedir)
    write_to_file(os.path.join(self.basedir, 'README'), 'hello\n')
    write_to_file(os.path.join(self.basedir, 'CHANGELOG'), 'version 1\n')
    write_to_file(os.path.join(self.basedir, 'Makefile'), 'bad command\n')
    for filename in files_to_ignore:
      write_to_file(os.path.join(self.basedir, filename),
          "you ain't seen me, right?")

  def extend_base_package(self):
    write_to_file(os.path.join(self.basedir, 'NEWS'), 'new release\n')
    write_to_file(os.path.join(self.basedir, 'Makefile'), 'good command\n')
    write_to_file(os.path.join(self.basedir, 'from_debian'), 'from debian\n')
    for filename in files_to_ignore:
      os.unlink(os.path.join(self.basedir, filename))

  def extend_base_package2(self):
    write_to_file(os.path.join(self.basedir, 'NEW_IN_3'), 'new release\n')

  def make_orig_1(self):
    self.make_base_package()
    tar = tarfile.open(self.orig_1, 'w:gz')
    try:
      tar.add(self.basedir)
    finally:
      tar.close()

  def make_orig_2(self):
    self.extend_base_package()
    tar = tarfile.open(self.orig_2, 'w:gz')
    try:
      tar.add(self.basedir)
    finally:
      tar.close()

  def make_orig_3(self):
    self.extend_base_package2()
    tar = tarfile.open(self.orig_3, 'w:gz')
    try:
      tar.add(self.basedir)
    finally:
      tar.close()

  def make_diff_1(self):
    diffdir = 'package-0.1'
    shutil.copytree(self.basedir, diffdir)
    os.mkdir(os.path.join(diffdir, 'debian'))
    write_to_file(os.path.join(diffdir, 'debian', 'changelog'),
                  'version 1-1\n')
    write_to_file(os.path.join(diffdir, 'debian', 'install'), 'install\n')
    write_to_file(os.path.join(diffdir, 'Makefile'), 'good command\n')
    write_to_file(os.path.join(diffdir, 'debian', 'rules'), '\n')
    os.system('diff -Nru %s %s | gzip -9 - > %s' % (self.basedir, diffdir,
                                                   self.diff_1))

  def make_diff_1b(self):
    diffdir = 'package-0.1'
    append_to_file(os.path.join(diffdir, 'debian', 'changelog'),
                   'version 1-2\n')
    write_to_file(os.path.join(diffdir, 'debian', 'control'), 'package\n')
    os.unlink(os.path.join(diffdir, 'debian', 'install'))
    os.system('diff -Nru %s %s | gzip -9 - > %s' % (self.basedir, diffdir,
                                                   self.diff_1b))

  def make_diff_1c(self):
    diffdir = 'package-0.1'
    append_to_file(os.path.join(diffdir, 'debian', 'changelog'),
                   'version 1-3\n')
    write_to_file(os.path.join(diffdir, 'debian', 'install'), 'install\n')
    write_to_file(os.path.join(diffdir, 'from_debian'), 'from debian\n')
    os.system('diff -Nru %s %s | gzip -9 - > %s' % (self.basedir, diffdir,
                                                   self.diff_1c))

  def make_diff_2(self):
    diffdir = 'package-0.2'
    shutil.copytree(self.basedir, diffdir)
    os.mkdir(os.path.join(diffdir, 'debian'))
    write_to_file(os.path.join(diffdir, 'debian', 'changelog'),
                  'version 1-1\nversion 1-2\nversion 1-3\nversion 2-1\n')
    write_to_file(os.path.join(diffdir, 'debian', 'install'), 'install\n')
    write_to_file(os.path.join(diffdir, 'debian', 'rules'), '\n')
    for filename in files_to_ignore:
      write_to_file(os.path.join(diffdir, filename),
          "i'm like some annoying puppy")
    os.system('diff -Nru %s %s | gzip -9 - > %s' % (self.basedir, diffdir,
                                                   self.diff_2))

  def make_diff_3(self):
    diffdir = 'package-0.3'
    shutil.copytree(self.basedir, diffdir)
    os.mkdir(os.path.join(diffdir, '.bzr'))
    write_to_file(os.path.join(diffdir, '.bzr', 'branch-format'),
        'broken format')
    os.mkdir(os.path.join(diffdir, 'debian'))
    write_to_file(os.path.join(diffdir, 'debian', 'changelog'),
          'version 1-1\nversion 1-2\nversion 1-3\nversion 2-1\nversion 3-1\n')
    write_to_file(os.path.join(diffdir, 'debian', 'install'), 'install\n')
    os.system('diff -Nru %s %s | gzip -9 - > %s' % (self.basedir, diffdir,
                                                   self.diff_3))

  def make_dsc(self, filename, version, file1, extra_files=[],
               package='package'):
    write_to_file(filename, """Format: 1.0
Source: %s
Version: %s
Binary: package
Maintainer: maintainer <maint@maint.org>
Architecture: any
Standards-Version: 3.7.2
Build-Depends: debhelper (>= 5.0.0)
Files:
 8636a3e8ae81664bac70158503aaf53a 1328218 %s
""" % (package, version, os.path.basename(file1)))
    i = 1
    for extra_file in extra_files:
      append_to_file(filename,
                     " 1acd97ad70445afd5f2a64858296f21%d 20709 %s\n" % \
                     (i, os.path.basename(extra_file)))
      i += 1

  def make_dsc_1(self):
    self.make_orig_1()
    self.make_diff_1()
    self.make_dsc(self.dsc_1, '0.1-1', self.orig_1, [self.diff_1])

  def make_dsc_1b(self):
    self.make_diff_1b()
    self.make_dsc(self.dsc_1b, '0.1-2', self.diff_1b)

  def make_dsc_1b_repeated_orig(self):
    self.make_diff_1b()
    self.make_dsc(self.dsc_1b, '0.1-2', self.orig_1, [self.diff_1b])

  def make_dsc_1c(self):
    self.make_diff_1c()
    self.make_dsc(self.dsc_1c, '0.1-3', self.diff_1c)

  def make_dsc_2(self):
    self.make_orig_2()
    self.make_diff_2()
    self.make_dsc(self.dsc_2, '0.2-1', self.orig_2, [self.diff_2])

  def make_dsc_3(self):
    self.make_orig_3()
    self.make_diff_3()
    self.make_dsc(self.dsc_3, '0.3-1', self.orig_3, [self.diff_3])

  def import_dsc_1(self):
    self.make_dsc_1()
    DscImporter([self.dsc_1]).import_dsc(self.target)

  def import_dsc_1b(self):
    self.make_dsc_1()
    self.make_dsc_1b()
    DscImporter([self.dsc_1, self.dsc_1b]).import_dsc(self.target)

  def import_dsc_1b_repeated_diff(self):
    self.make_dsc_1()
    self.make_dsc_1b()
    DscImporter([self.dsc_1, self.dsc_1b, self.dsc_1b]).import_dsc(self.target)

  def import_dsc_1c(self):
    self.make_dsc_1()
    self.make_dsc_1b()
    self.make_dsc_1c()
    DscImporter([self.dsc_1, self.dsc_1c, self.dsc_1b]).import_dsc(self.target)

  def import_dsc_2(self):
    self.make_dsc_1()
    self.make_dsc_1b()
    self.make_dsc_1c()
    self.make_dsc_2()
    importer = DscImporter([self.dsc_1, self.dsc_1b, self.dsc_1c, self.dsc_2])
    importer.import_dsc(self.target)

  def import_dsc_2_repeated_orig(self):
    self.make_dsc_1()
    self.make_dsc_1b_repeated_orig()
    self.make_dsc_1c()
    self.make_dsc_2()
    importer = DscImporter([self.dsc_1, self.dsc_1b, self.dsc_1c, self.dsc_2])
    importer.import_dsc(self.target)

  def test_import_dsc_target_extant(self):
    os.mkdir(self.target)
    write_to_file('package_0.1.dsc', '')
    importer = DscImporter([self.dsc_1])
    self.assertRaises(FileExists, importer.import_dsc, self.target)

  def test_import_one_dsc_tree(self):
    self.import_dsc_1()
    self.failUnlessExists(self.target)
    tree = WorkingTree.open(self.target)
    tree.lock_read()
    expected_inv = ['README', 'CHANGELOG', 'Makefile', 'debian/',
                    'debian/changelog', 'debian/install', 'debian/rules']
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    for path in expected_inv:
      self.failUnlessExists(os.path.join(self.target, path))
    self.assertContentsAre(os.path.join(self.target, 'Makefile'),
                           'good command\n')
    self.assertContentsAre(os.path.join(self.target, 'debian', 'changelog'),
                           'version 1-1\n')
    self.assertEqual(tree.changes_from(tree.basis_tree()).has_changed(),
                     False)
    self.assertRulesExecutable(tree)

  def test_import_one_dsc_history(self):
    self.import_dsc_1()
    tree = WorkingTree.open(self.target)
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 2)
    self.check_revision_message(tree, rh[0],
                          'import upstream from %s' % self.orig_1)
    self.check_revision_message(tree, rh[1],
                          'merge packaging changes from %s' % self.diff_1)
    changes = tree.changes_from(tree.branch.repository.revision_tree(rh[0]))
    expected_added = ['debian/', 'debian/changelog', 'debian/install',
                      'debian/rules']
    expected_modified = ['Makefile']
    self.check_changes(changes, added=expected_added,
                       modified=expected_modified)
    tag = tree.branch.tags.lookup_tag('upstream-0.1')
    self.assertEqual(tag, rh[0])

  def test_import_two_dsc_one_upstream_tree(self):
    self.import_dsc_1b()
    self.failUnlessExists(self.target)
    tree = WorkingTree.open(self.target)
    tree.lock_read()
    expected_inv = ['README', 'CHANGELOG', 'Makefile', 'debian/',
                    'debian/changelog', 'debian/control', 'debian/rules']
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    for path in expected_inv:
      self.failUnlessExists(os.path.join(self.target, path))
    self.assertContentsAre(os.path.join(self.target, 'Makefile'),
                           'good command\n')
    self.assertContentsAre(os.path.join(self.target, 'debian', 'changelog'),
                           'version 1-1\nversion 1-2\n')
    self.assertEqual(tree.changes_from(tree.basis_tree()).has_changed(),
                     False)
    self.assertRulesExecutable(tree)

  def test_import_two_dsc_one_upstream_history(self):
    self.import_dsc_1b()
    tree = WorkingTree.open(self.target)
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 3)
    self.check_revision_message(tree, rh[0],
                          'import upstream from %s' % self.orig_1)
    self.check_revision_message(tree, rh[1],
                          'merge packaging changes from %s' % self.diff_1)
    self.check_revision_message(tree, rh[2],
                          'merge packaging changes from %s' % self.diff_1b)
    prev_tree = tree.branch.repository.revision_tree(rh[1])
    changes = tree.changes_from(prev_tree)
    expected_added = ['debian/control']
    expected_removed = ['debian/install']
    expected_modified = ['debian/changelog']
    self.check_changes(changes, added=expected_added,
                       removed=expected_removed, modified=expected_modified)
    self.assertRulesExecutable(prev_tree)

  def test_import_two_dsc_one_upstream_history_repeated_diff(self):
    self.import_dsc_1b_repeated_diff()
    tree = WorkingTree.open(self.target)
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 3)
    self.check_revision_message(tree, rh[0],
                          'import upstream from %s' % self.orig_1)
    self.check_revision_message(tree, rh[1],
                          'merge packaging changes from %s' % self.diff_1)
    self.check_revision_message(tree, rh[2],
                          'merge packaging changes from %s' % self.diff_1b)
    prev_tree = tree.branch.repository.revision_tree(rh[1])
    changes = tree.changes_from(prev_tree)
    expected_added = ['debian/control']
    expected_removed = ['debian/install']
    expected_modified = ['debian/changelog']
    self.check_changes(changes, added=expected_added,
                       removed=expected_removed, modified=expected_modified)
    self.assertRulesExecutable(prev_tree)

  def test_import_three_dsc_one_upstream_tree(self):
    self.import_dsc_1c()
    self.failUnlessExists(self.target)
    tree = WorkingTree.open(self.target)
    tree.lock_read()
    expected_inv = ['README', 'CHANGELOG', 'Makefile', 'from_debian',
                    'debian/', 'debian/changelog', 'debian/control',
                    'debian/install', 'debian/rules']
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    for path in expected_inv:
      self.failUnlessExists(os.path.join(self.target, path))
    self.assertContentsAre(os.path.join(self.target, 'Makefile'),
                           'good command\n')
    self.assertContentsAre(os.path.join(self.target, 'debian', 'changelog'),
                           'version 1-1\nversion 1-2\nversion 1-3\n')
    self.assertEqual(tree.changes_from(tree.basis_tree()).has_changed(),
                     False)
    self.assertRulesExecutable(tree)

  def test_import_three_dsc_one_upstream_history(self):
    self.import_dsc_1c()
    tree = WorkingTree.open(self.target)
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 4)
    self.check_revision_message(tree, rh[0],
                          'import upstream from %s' % self.orig_1)
    self.check_revision_message(tree, rh[1],
                          'merge packaging changes from %s' % self.diff_1)
    self.check_revision_message(tree, rh[2],
                          'merge packaging changes from %s' % self.diff_1b)
    self.check_revision_message(tree, rh[3],
                          'merge packaging changes from %s' % self.diff_1c)
    prev_tree = tree.branch.repository.revision_tree(rh[2])
    changes = tree.changes_from(prev_tree)
    expected_added = ['debian/install', 'from_debian']
    expected_modified = ['debian/changelog']
    self.check_changes(changes, added=expected_added,
                       modified=expected_modified)
    self.assertRulesExecutable(prev_tree)

  def test_import_three_dsc_two_upstream_tree(self):
    self.import_dsc_2()
    self.failUnlessExists(self.target)
    tree = WorkingTree.open(self.target)
    tree.lock_read()
    expected_inv = ['README', 'CHANGELOG', 'Makefile', 'NEWS', 'from_debian',
                    'debian/', 'debian/changelog', 'debian/install',
                    'debian/rules']
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    for path in expected_inv:
      self.failUnlessExists(os.path.join(self.target, path))
    self.assertContentsAre(os.path.join(self.target, 'Makefile'),
                           'good command\n')
    self.assertContentsAre(os.path.join(self.target, 'debian', 'changelog'),
                     'version 1-1\nversion 1-2\nversion 1-3\nversion 2-1\n')
    self.assertEqual(tree.changes_from(tree.basis_tree()).has_changed(),
                     False)
    self.assertRulesExecutable(tree)

  def assertContentsAre(self, filename, expected_contents):
    f = open(filename)
    try:
      contents = f.read()
    finally:
      f.close()
    self.assertEqual(contents, expected_contents,
                     "Contents of %s are not as expected" % filename)

  def test_import_four_dsc_two_upstream_history(self):
    self.import_dsc_2()
    tree = WorkingTree.open(self.target)
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 3)
    self.check_revision_message(tree, rh[0],
                          'import upstream from %s' % self.orig_1)
    self.check_revision_message(tree, rh[1],
                          'import upstream from %s' % self.orig_2)
    self.check_revision_message(tree, rh[2],
                         'merge packaging changes from %s' % self.diff_2)
    parents = tree.branch.repository.revision_tree(rh[1]).get_parent_ids()
    self.assertEqual(parents, [rh[0]], rh)
    parents = tree.branch.repository.revision_tree(rh[2]).get_parent_ids()
    self.assertEqual(len(parents), 2)
    self.assertEqual(parents[0], rh[1], rh)
    self.check_revision_message(tree, parents[1],
                     'merge packaging changes from %s' % self.diff_1c)
    # Check the diff against upstream.
    changes = tree.changes_from(tree.branch.repository.revision_tree(rh[1]))
    expected_added = ['debian/', 'debian/changelog', 'debian/install',
                      'debian/rules']
    self.check_changes(changes, added=expected_added)
    # Check the diff against last packaging version
    last_package_tree = tree.branch.repository.revision_tree(parents[1])
    changes = tree.changes_from(last_package_tree)
    expected_added = ['NEWS']
    expected_removed = ['debian/control']
    expected_modified = ['debian/changelog']
    self.check_changes(changes, added=expected_added,
                       removed=expected_removed, modified=expected_modified)
    self.assertRulesExecutable(tree)
    self.assertRulesExecutable(last_package_tree)

  def test_import_dsc_restrictions_on_dscs(self):
    """Test that errors are raised for confusing sets of .dsc files."""
    self.make_dsc(self.dsc_1, '0.1-1', self.diff_1)
    importer = DscImporter([self.dsc_1])
    self.assertRaises(ImportError, importer.import_dsc, self.target)
    self.make_dsc(self.dsc_1, '0.1-1', self.orig_1)
    importer = DscImporter([self.dsc_1])
    self.assertRaises(ImportError, importer.import_dsc, self.target)
    self.make_dsc(self.dsc_1, '0.1-1', self.orig_1, [self.diff_1, self.diff_1])
    importer = DscImporter([self.dsc_1])
    self.assertRaises(ImportError, importer.import_dsc, self.target)
    self.make_dsc(self.dsc_1, '0.1-1', self.orig_1, [self.orig_1, self.diff_1])
    importer = DscImporter([self.dsc_1])
    self.assertRaises(ImportError, importer.import_dsc, self.target)
    self.make_dsc(self.dsc_1, '0.1-1', self.orig_1, [self.diff_1])
    self.make_dsc(self.dsc_1b, '0.1-2', self.diff_1b, package='otherpackage')
    importer = DscImporter([self.dsc_1, self.dsc_1b])
    self.assertRaises(ImportError, importer.import_dsc, self.target)
    self.make_dsc(self.dsc_1, '0.1', self.diff_1b, [self.orig_1,
                                                    self.native_1])
    importer = DscImporter([self.dsc_1])
    self.assertRaises(ImportError, importer.import_dsc, self.target)
    self.make_dsc(self.dsc_1, '0.1', self.native_1, [self.native_1])
    importer = DscImporter([self.dsc_1])
    self.assertRaises(ImportError, importer.import_dsc, self.target)

  def test_import_four_dsc_two_upstream_history_repeated_orig(self):
    self.import_dsc_2_repeated_orig()
    tree = WorkingTree.open(self.target)
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 3)
    self.check_revision_message(tree, rh[0], 'import upstream from %s' % \
                                self.orig_1)
    self.check_revision_message(tree, rh[1], 'import upstream from %s' % \
                                self.orig_2)
    self.check_revision_message(tree, rh[2],
                         'merge packaging changes from %s' % self.diff_2)
    parents = tree.branch.repository.revision_tree(rh[1]).get_parent_ids()
    self.assertEqual(parents, [rh[0]], rh)
    parents = tree.branch.repository.revision_tree(rh[2]).get_parent_ids()
    self.assertEqual(len(parents), 2)
    self.assertEqual(parents[0], rh[1], rh)
    self.assertEqual(tree.branch.repository.get_revision(parents[1]).message,
                     'merge packaging changes from %s' % self.diff_1c)
    # Check the diff against upstream.
    changes = tree.changes_from(tree.branch.repository.revision_tree(rh[1]))
    expected_added = ['debian/', 'debian/changelog', 'debian/install',
                      'debian/rules']
    self.check_changes(changes, added=expected_added)
    # Check the diff against last packaging version
    last_package_tree = tree.branch.repository.revision_tree(parents[1])
    changes = tree.changes_from(last_package_tree)
    expected_added = ['NEWS']
    expected_removed = ['debian/control']
    expected_modified = ['debian/changelog']
    self.check_changes(changes, added=expected_added,
                       removed=expected_removed, modified=expected_modified)
    self.assertRulesExecutable(tree)
    self.assertRulesExecutable(last_package_tree)

  def test_import_dsc_different_dir(self):
    source = 'source'
    os.mkdir(source)
    self.diff_1 = os.path.join(source, self.diff_1)
    self.orig_1 = os.path.join(source, self.orig_1)
    self.dsc_1 = os.path.join(source, self.dsc_1)
    self.import_dsc_1()
    self.failUnlessExists(self.target)
    tree = WorkingTree.open(self.target)
    tree.lock_read()
    expected_inv = ['README', 'CHANGELOG', 'Makefile', 'debian/',
                    'debian/changelog', 'debian/install', 'debian/rules']
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    for path in expected_inv:
      self.failUnlessExists(os.path.join(self.target, path))
    self.assertRulesExecutable(tree)

  def _add_debian_to_native(self):
    os.mkdir(os.path.join(self.basedir, 'debian'))
    write_to_file(os.path.join(self.basedir, 'debian', 'changelog'),
                  'version 1\n')
    write_to_file(os.path.join(self.basedir, 'debian', 'rules'), '\n')

  def _make_native(self, tarball_name, dsc_name):
    tar = tarfile.open(tarball_name, 'w:gz')
    try:
      tar.add(self.basedir)
    finally:
      tar.close()
    self.make_dsc(dsc_name, '0.1', tarball_name)


  def make_native_dsc_1(self):
    self.make_base_package()
    self._add_debian_to_native()
    self._make_native(self.native_1, self.native_dsc_1)

  def make_native_dsc_2(self):
    self.extend_base_package()
    append_to_file(os.path.join(self.basedir, 'debian', 'changelog'),
                   'version 2\n')
    write_to_file(os.path.join(self.basedir, 'debian', 'rules'), '\n')
    tar = tarfile.open(self.native_2, 'w:gz')
    try:
      tar.add(self.basedir)
    finally:
      tar.close()
    self.make_dsc(self.native_dsc_2, '0.2', self.native_2)

  def make_native_dsc_2_after_non_native(self):
    self.extend_base_package()
    os.mkdir(os.path.join(self.basedir, 'debian'))
    write_to_file(os.path.join(self.basedir, 'debian', 'changelog'),
                  'version 1\nversion 2\n')
    write_to_file(os.path.join(self.basedir, 'debian', 'rules'), '\n')
    tar = tarfile.open(self.native_2, 'w:gz')
    try:
      tar.add(self.basedir)
    finally:
      tar.close()
    self.make_dsc(self.native_dsc_2, '0.2', self.native_2)

  def test_import_dsc_native_single(self):
    self.make_native_dsc_1()
    importer = DscImporter([self.native_dsc_1])
    importer.import_dsc(self.target)
    tree = WorkingTree.open(self.target)
    expected_inv = ['CHANGELOG', 'README', 'Makefile', 'debian/',
                    'debian/changelog', 'debian/rules'] + self.config_files
    tree.lock_read()
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 1)
    self.check_revision_message(tree, rh[0], "import package from %s" % \
                     os.path.basename(self.native_1))
    self.assertEqual(len(tree.get_parent_ids()), 1)
    self.check_is_native_in_config(tree)
    self.assertRulesExecutable(tree)

  def test_import_dsc_native_double(self):
    self.make_native_dsc_1()
    self.make_native_dsc_2()
    importer = DscImporter([self.native_dsc_1, self.native_dsc_2])
    importer.import_dsc(self.target)
    tree = WorkingTree.open(self.target)
    expected_inv = ['CHANGELOG', 'README', 'Makefile', 'NEWS', 'from_debian',
                    'debian/', 'debian/changelog', 'debian/rules'] \
                   + self.config_files
    tree.lock_read()
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 2)
    self.check_revision_message(tree, rh[0], "import package from %s" % \
                     os.path.basename(self.native_1))
    self.check_revision_message(tree, rh[1], "import package from %s" % \
                     os.path.basename(self.native_2))
    self.assertEqual(len(tree.get_parent_ids()), 1)
    parents = tree.branch.repository.revision_tree(rh[1]).get_parent_ids()
    self.assertEqual(len(parents), 1)
    self.check_is_native_in_config(tree)
    old_tree = tree.branch.repository.revision_tree(rh[0])
    self.check_is_native_in_config(old_tree)
    changes = tree.changes_from(old_tree)
    expected_added = ['NEWS', 'from_debian']
    expected_modified = ['Makefile', 'debian/changelog']
    self.check_changes(changes, added=expected_added,
                       modified=expected_modified)
    self.assertRulesExecutable(tree)
    self.assertRulesExecutable(old_tree)

  def check_revision_message(self, tree, revision, expected_message):
    rev = tree.branch.repository.get_revision(revision)
    self.assertEqual(rev.message, expected_message)

  def test_non_native_to_native(self):
    self.make_dsc_1()
    self.make_native_dsc_2_after_non_native()
    importer = DscImporter([self.dsc_1, self.native_dsc_2])
    importer.import_dsc(self.target)
    tree = WorkingTree.open(self.target)
    expected_inv = ['CHANGELOG', 'README', 'Makefile', 'NEWS', 'from_debian',
                    'debian/', 'debian/changelog', 'debian/rules'] \
                   + self.config_files
    tree.lock_read()
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    self.assertEqual(tree.changes_from(tree.basis_tree()).has_changed(), False)
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 2)
    self.check_revision_message(tree, rh[0], "import upstream from %s" % \
                     os.path.basename(self.orig_1))
    self.check_revision_message(tree, rh[1], "import package from %s" % \
                     os.path.basename(self.native_2))
    self.assertEqual(len(tree.get_parent_ids()), 1)
    parents = tree.branch.repository.revision_tree(rh[1]).get_parent_ids()
    self.assertEqual(len(parents), 2)
    self.check_revision_message(tree, parents[1],
                     "merge packaging changes from %s" % \
                     os.path.basename(self.diff_1))
    up_tree = tree.branch.repository.revision_tree(rh[0])
    changes = tree.changes_from(up_tree)
    expected_added = ['NEWS', 'debian/', 'debian/changelog', 'debian/rules',
                      'from_debian']
    expected_added += self.config_files
    self.check_changes(changes, added=expected_added, modified=['Makefile'])
    package_tree = tree.branch.repository.revision_tree(parents[1])
    changes = tree.changes_from(package_tree)
    expected_added = ['NEWS', 'from_debian'] + self.config_files
    expected_modified = ['debian/changelog']
    expected_removed = ['debian/install']
    self.check_changes(changes, added=expected_added,
                       modified=expected_modified, removed=expected_removed)
    self.check_is_not_native_in_config(up_tree)
    self.check_is_not_native_in_config(package_tree)
    self.check_is_native_in_config(tree)
    self.assertRulesExecutable(tree)
    self.assertRulesExecutable(package_tree)

  def check_changes(self, changes, added=[], removed=[], modified=[],
                    renamed=[]):
    exp_added = set(added)
    exp_removed = set(removed)
    exp_modified = set(modified)
    exp_renamed = set(renamed)

    def make_set(list):
      output = set()
      for item in list:
        if item[2] == 'directory':
          output.add(item[0] + '/')
        else:
          output.add(item[0])
      return output

    real_added = make_set(changes.added)
    real_removed = make_set(changes.removed)
    real_modified = make_set(changes.modified)
    real_renamed = make_set(changes.renamed)
    missing_added = exp_added.difference(real_added)
    missing_removed = exp_removed.difference(real_removed)
    missing_modified = exp_modified.difference(real_modified)
    missing_renamed = exp_renamed.difference(real_renamed)
    extra_added = real_added.difference(exp_added)
    extra_removed = real_removed.difference(exp_removed)
    extra_modified = real_modified.difference(exp_modified)
    extra_renamed = real_renamed.difference(exp_renamed)
    if len(missing_added) > 0:
      self.fail("Some expected paths not found added in the changes: %s" % \
                 str(missing_added))
    if len(missing_removed) > 0:
      self.fail("Some expected paths not found removed in the changes: %s" % \
                 str(missing_removed))
    if len(missing_modified) > 0:
      self.fail("Some expected paths not found modified in the changes: %s" % \
                 str(missing_modified))
    if len(missing_renamed) > 0:
      self.fail("Some expected paths not found renamed in the changes: %s" % \
                 str(missing_renamed))
    if len(extra_added) > 0:
      self.fail("Some extra paths found added in the changes: %s" % \
                 str(extra_added))
    if len(extra_removed) > 0:
      self.fail("Some extra paths found removed in the changes: %s" % \
                 str(extra_removed))
    if len(extra_modified) > 0:
      self.fail("Some extra paths found modified in the changes: %s" % \
                 str(extra_modified))
    if len(extra_renamed) > 0:
      self.fail("Some extra paths found renamed in the changes: %s" % \
                 str(extra_renamed))

  def test_native_to_non_native(self):
    self.make_native_dsc_1()
    shutil.rmtree(os.path.join(self.basedir, 'debian'))
    self.make_dsc_2()
    importer = DscImporter([self.native_dsc_1, self.dsc_2])
    importer.import_dsc(self.target)
    tree = WorkingTree.open(self.target)
    expected_inv = ['CHANGELOG', 'README', 'Makefile', 'NEWS', 'from_debian',
                    'debian/', 'debian/changelog', 'debian/install',
                    'debian/rules']
    tree.lock_read()
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    self.assertEqual(tree.changes_from(tree.basis_tree()).has_changed(), False)
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 3)
    self.check_revision_message(tree, rh[0],
                     "import package from %s" % \
                     os.path.basename(self.native_1))
    self.check_revision_message(tree, rh[1],
                     "import upstream from %s" % \
                     os.path.basename(self.orig_2))
    self.check_revision_message(tree, rh[2],
                     "merge packaging changes from %s" % \
                     os.path.basename(self.diff_2))
    self.assertEqual(len(tree.get_parent_ids()), 1)
    parents = tree.branch.repository.revision_tree(rh[1]).get_parent_ids()
    self.assertEqual(len(parents), 1)
    parents = tree.branch.repository.revision_tree(rh[2]).get_parent_ids()
    self.assertEqual(len(parents), 1)
    up_tree = tree.branch.repository.revision_tree(rh[1])
    changes = tree.changes_from(up_tree)
    expected_added = ['debian/', 'debian/changelog', 'debian/install',
                      'debian/rules']
    self.check_changes(changes, added=expected_added)
    native_tree = tree.branch.repository.revision_tree(rh[0])
    changes = up_tree.changes_from(native_tree)
    expected_added = ['NEWS', 'from_debian']
    expected_modified = ['Makefile']
    expected_removed = ['debian/', 'debian/changelog', 'debian/rules'] \
                       + self.config_files
    self.check_changes(changes, added=expected_added, removed=expected_removed,
                       modified=expected_modified)
    # FIXME: Should changelog etc. be added/removed or not?
    changes = tree.changes_from(native_tree)
    expected_added = ['NEWS', 'debian/', 'debian/install', 'from_debian',
                      'debian/changelog', 'debian/rules']
    expected_modified = ['Makefile']
    expected_removed = ['debian/', 'debian/changelog', 'debian/rules'] \
                       + self.config_files
    self.check_changes(changes, added=expected_added,
                       modified=expected_modified, removed=expected_removed)
    self.check_is_native_in_config(native_tree)
    self.check_is_not_native_in_config(up_tree)
    self.check_is_not_native_in_config(tree)
    self.assertRulesExecutable(tree)
    self.assertRulesExecutable(native_tree)

  def _get_tree_default_config(self, tree, fail_on_none=True):
    config_file_id = tree.path2id('.bzr-builddeb/default.conf')
    if config_file_id is None:
      if fail_on_none:
        self.fail("The tree has no config file")
      else:
        return None
    config_file = tree.get_file_text(config_file_id).split('\n')
    config = ConfigObj(config_file)
    return config

  def check_is_native_in_config(self, tree):
    tree.lock_read()
    try:
      config = self._get_tree_default_config(tree)
      self.assertEqual(bool(config['BUILDDEB']['native']), True)
    finally:
      tree.unlock()

  def check_is_not_native_in_config(self, tree):
    config = self._get_tree_default_config(tree, fail_on_none=False)
    if config is not None:
      self.assertEqual(bool(config['BUILDDEB']['native']), False)

  def test_import_incremental_simple(self):
    # set up the branch using a simple single version non-native import.
    self.import_dsc_1()
    self.make_dsc_1b()
    DscImporter([self.dsc_1b]).incremental_import_dsc(self.target)
    self.failUnlessExists(self.target)
    tree = WorkingTree.open(self.target)
    tree.lock_read()
    expected_inv = ['README', 'CHANGELOG', 'Makefile', 'debian/',
                    'debian/changelog', 'debian/control', 'debian/rules']
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    for path in expected_inv:
      self.failUnlessExists(os.path.join(self.target, path))
    self.assertContentsAre(os.path.join(self.target, 'Makefile'),
                           'good command\n')
    self.assertContentsAre(os.path.join(self.target, 'debian', 'changelog'),
                           'version 1-1\nversion 1-2\n')
    self.assertRulesExecutable(tree)
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 2)
    self.check_revision_message(tree, rh[0],
                          'import upstream from %s' % self.orig_1)
    self.check_revision_message(tree, rh[1],
                          'merge packaging changes from %s' % self.diff_1)
    parents = tree.get_parent_ids()
    self.assertEqual(len(parents), 2)
    self.assertEqual(parents[0], rh[1])
    self.check_revision_message(tree, parents[1],
                          'merge packaging changes from %s' % self.diff_1b)
    prev_tree = tree.branch.repository.revision_tree(parents[1])
    current_tree = tree.branch.repository.revision_tree(rh[1])
    changes = prev_tree.changes_from(current_tree)
    expected_added = ['debian/control']
    expected_removed = ['debian/install']
    expected_modified = ['debian/changelog']
    self.check_changes(changes, added=expected_added,
                       removed=expected_removed, modified=expected_modified)
    self.assertRulesExecutable(prev_tree)
    self.assertEqual(len(tree.conflicts()), 0)
    changes = tree.changes_from(tree.basis_tree())
    self.check_changes(changes, added=expected_added,
                       removed=expected_removed, modified=expected_modified)

  def test_import_incremental_multiple_dscs_prohibited(self):
    self.import_dsc_1()
    self.make_dsc_1b()
    self.make_dsc_2()
    importer = DscImporter([self.dsc_1b, self.dsc_2])
    self.assertRaises(OnlyImportSingleDsc, importer.incremental_import_dsc,
      self.target)

  def test_import_incremental_working_tree_changes(self):
    self.import_dsc_1()
    self.make_dsc_1b()
    self.build_tree([os.path.join(self.target, 'a')])
    tree = WorkingTree.open(self.target)
    tree.add(['a'])
    importer = DscImporter([self.dsc_1b])
    self.assertRaises(UncommittedChanges, importer.incremental_import_dsc,
            self.target)

  def test_incremental_with_upstream(self):
    self.import_dsc_1()
    self.make_dsc_2()
    DscImporter([self.dsc_2]).incremental_import_dsc(self.target)
    self.failUnlessExists(self.target)
    tree = WorkingTree.open(self.target)
    tree.lock_read()
    expected_inv = ['README', 'CHANGELOG', 'Makefile', 'NEWS', 'from_debian',
                    'debian/', 'debian/changelog', 'debian/install',
                    'debian/rules']
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    for path in expected_inv:
      self.failUnlessExists(os.path.join(self.target, path))
    self.assertContentsAre(os.path.join(self.target, 'Makefile'),
                           'good command\n')
    self.assertContentsAre(os.path.join(self.target, 'debian', 'changelog'),
        '<<<<<<< TREE\nversion 1-1\n=======\nversion 1-1\nversion 1-2\n'
        'version 1-3\nversion 2-1\n>>>>>>> MERGE-SOURCE\n')
    self.assertRulesExecutable(tree)
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 2)
    self.check_revision_message(tree, rh[0],
                          'import upstream from %s' % self.orig_1)
    self.check_revision_message(tree, rh[1],
                          'merge packaging changes from %s' % self.diff_1)
    parents = tree.get_parent_ids()
    self.assertEqual(len(parents), 2)
    self.assertEqual(parents[0], rh[1])
    self.check_revision_message(tree, parents[1],
                          'merge packaging changes from %s' % self.diff_2)
    prev_tree = tree.branch.repository.revision_tree(parents[1])
    current_tree = tree.branch.repository.revision_tree(parents[0])
    changes = prev_tree.changes_from(current_tree)
    expected_added = ['from_debian', 'NEWS']
    expected_modified = ['debian/changelog']
    self.check_changes(changes, added=expected_added,
                       removed=[], modified=expected_modified)
    self.assertRulesExecutable(prev_tree)
    self.assertEqual(len(tree.conflicts()), 1)
    self.assertTrue(isinstance(tree.conflicts()[0], TextConflict))
    self.assertEqual(tree.conflicts()[0].path, 'debian/changelog')
    changes = tree.changes_from(tree.basis_tree())
    self.check_changes(changes, added=expected_added,
                       removed=[], modified=expected_modified)
    merged_parents = prev_tree.get_parent_ids()
    self.assertEqual(len(merged_parents), 1)
    self.check_revision_message(tree, merged_parents[0],
                          'import upstream from %s' % self.orig_2)
    new_upstream_tree = tree.branch.repository.revision_tree(merged_parents[0])
    new_upstream_parents = new_upstream_tree.get_parent_ids()
    self.assertEqual(len(new_upstream_parents), 1)
    self.assertEqual(new_upstream_parents[0], rh[0])

  def test_incremental_with_upstream_older_than_all_in_branch(self):
    self.make_dsc_1()
    self.make_dsc_2()
    DscImporter([self.dsc_2]).import_dsc(self.target)
    self.failUnlessExists(self.target)
    DscImporter([self.dsc_1]).incremental_import_dsc(self.target)
    self.failUnlessExists(self.target)
    tree = WorkingTree.open(self.target)
    tree.lock_read()
    expected_inv = ['README', 'CHANGELOG', 'Makefile', 'NEWS', 'from_debian',
                    'debian/', 'debian/changelog',
                    'debian/install', 'debian/rules']
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    for path in expected_inv:
      self.failUnlessExists(os.path.join(self.target, path))
    self.assertContentsAre(os.path.join(self.target, 'Makefile'),
                           'good command\n')
    self.assertContentsAre(os.path.join(self.target, 'debian', 'changelog'),
        '<<<<<<< TREE\nversion 1-1\nversion 1-2\nversion 1-3\nversion 2-1\n'
        '=======\nversion 1-1\n>>>>>>> MERGE-SOURCE\n')
    self.assertRulesExecutable(tree)
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 2)
    self.check_revision_message(tree, rh[0],
                          'import upstream from %s' % self.orig_2)
    self.check_revision_message(tree, rh[1],
                          'merge packaging changes from %s' % self.diff_2)
    parents = tree.get_parent_ids()
    self.assertEqual(len(parents), 2)
    self.assertEqual(parents[0], rh[1])
    self.check_revision_message(tree, parents[1],
                          'merge packaging changes from %s' % self.diff_1)
    prev_tree = tree.branch.repository.revision_tree(parents[1])
    merged_parents = prev_tree.get_parent_ids()
    self.assertEqual(len(merged_parents), 1)
    self.check_revision_message(tree, merged_parents[0],
                          'import upstream from %s' % self.orig_1)

  def test_incremental_with_upstream_older_than_lastest_in_branch(self):
    self.make_dsc_1()
    self.make_dsc_2()
    self.make_dsc_3()
    DscImporter([self.dsc_1, self.dsc_3]).import_dsc(self.target)
    self.failUnlessExists(self.target)
    DscImporter([self.dsc_2,]).incremental_import_dsc(self.target)
    self.failUnlessExists(self.target)
    tree = WorkingTree.open(self.target)
    tree.lock_read()
    expected_inv = ['README', 'CHANGELOG', 'Makefile', 'NEWS', 'from_debian',
                    'NEW_IN_3', 'debian/', 'debian/changelog',
                    'debian/install', 'debian/rules']
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    for path in expected_inv:
      self.failUnlessExists(os.path.join(self.target, path))
    self.assertContentsAre(os.path.join(self.target, 'Makefile'),
                           'good command\n')
    self.assertContentsAre(os.path.join(self.target, 'debian', 'changelog'),
        '<<<<<<< TREE\nversion 1-1\nversion 1-2\nversion 1-3\nversion 2-1\n'
        'version 3-1\n=======\nversion 1-1\nversion 1-2\nversion 1-3\n'
        'version 2-1\n>>>>>>> MERGE-SOURCE\n')
    self.assertRulesExecutable(tree)
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 3)
    self.check_revision_message(tree, rh[0],
                          'import upstream from %s' % self.orig_1)
    self.check_revision_message(tree, rh[1],
                          'import upstream from %s' % self.orig_3)
    self.check_revision_message(tree, rh[2],
                          'merge packaging changes from %s' % self.diff_3)
    parents = tree.get_parent_ids()
    self.assertEqual(len(parents), 2)
    self.assertEqual(parents[0], rh[2])
    self.check_revision_message(tree, parents[1],
                          'merge packaging changes from %s' % self.diff_2)
    prev_tree = tree.branch.repository.revision_tree(parents[1])
    merged_parents = prev_tree.get_parent_ids()
    self.assertEqual(len(merged_parents), 1)
    self.check_revision_message(tree, merged_parents[0],
                          'import upstream from %s' % self.orig_2)
    new_upstream_tree = tree.branch.repository.revision_tree(merged_parents[0])
    new_upstream_parents = new_upstream_tree.get_parent_ids()
    self.assertEqual(len(new_upstream_parents), 1)
    self.assertEqual(new_upstream_parents[0], rh[0])
    self.check_revision_message(tree, merged_parents[0],
                          'import upstream from %s' % self.orig_2)

  def test_import_no_prefix(self):
    write_to_file('README', 'hello\n')
    write_to_file('NEWS', 'bye bye\n')
    tar = tarfile.open(self.native_1, 'w:gz')
    try:
      tar.add('./', recursive=False)
      tar.add('README')
      tar.add('NEWS')
    finally:
      tar.close()
      os.unlink('README')
      os.unlink('NEWS')
    self.make_dsc(self.native_dsc_1, '0.1', self.native_1)
    DscImporter([self.native_dsc_1]).import_dsc(self.target)
    self.failUnlessExists(self.target)

  def test_import_extra_slash(self):
    tar = tarfile.open(self.native_1, 'w:gz')
    try:
      tar.addfile(_TarInfo('root//'))
      tar.addfile(_TarInfo('root//README'))
      tar.addfile(_TarInfo('root//NEWS'))
    finally:
      tar.close()
    self.make_dsc(self.native_dsc_1, '0.1', self.native_1)
    DscImporter([self.native_dsc_1]).import_dsc(self.target)
    self.failUnlessExists(self.target)

class _TarInfo(tarfile.TarInfo):
    """Subclass TarInfo to stop it normalising its path. Sorry Mum."""

    def tobuf(self, posix=False):
        """Return a tar header as a string of 512 byte blocks.
        """
        buf = ""
        type = self.type
        prefix = ""

        if self.name.endswith("/"):
            type = tarfile.DIRTYPE

        name = self.name

        if type == tarfile.DIRTYPE:
            # directories should end with '/'
            name += "/"

        linkname = self.linkname
        if linkname:
            # if linkname is empty we end up with a '.'
            linkname = normpath(linkname)

        if posix:
            if self.size > tarfile.MAXSIZE_MEMBER:
                raise ValueError("file is too large (>= 8 GB)")

            if len(self.linkname) > tarfile.LENGTH_LINK:
                raise ValueError("linkname is too long (>%d)" % (LENGTH_LINK))

            if len(name) > tarfile.LENGTH_NAME:
                prefix = name[:tarfile.LENGTH_PREFIX + 1]
                while prefix and prefix[-1] != "/":
                    prefix = prefix[:-1]

                name = name[len(prefix):]
                prefix = prefix[:-1]

                if not prefix or len(name) > tarfile.LENGTH_NAME:
                    raise ValueError("name is too long")

        else:
            if len(self.linkname) > tarfile.LENGTH_LINK:
                buf += self._create_gnulong(self.linkname,
                                            tarfile.GNUTYPE_LONGLINK)

            if len(name) > tarfile.LENGTH_NAME:
                buf += self._create_gnulong(name, tarfile.GNUTYPE_LONGNAME)

        parts = [
            tarfile.stn(name, 100),
            tarfile.itn(self.mode & 07777, 8, posix),
            tarfile.itn(self.uid, 8, posix),
            tarfile.itn(self.gid, 8, posix),
            tarfile.itn(self.size, 12, posix),
            tarfile.itn(self.mtime, 12, posix),
            "        ", # checksum field
            type,
            tarfile.stn(self.linkname, 100),
            tarfile.stn(tarfile.MAGIC, 6),
            tarfile.stn(tarfile.VERSION, 2),
            tarfile.stn(self.uname, 32),
            tarfile.stn(self.gname, 32),
            tarfile.itn(self.devmajor, 8, posix),
            tarfile.itn(self.devminor, 8, posix),
            tarfile.stn(prefix, 155)
        ]

        buf += "".join(parts).ljust(tarfile.BLOCKSIZE, tarfile.NUL)
        chksum = tarfile.calc_chksums(buf[-tarfile.BLOCKSIZE:])[0]
        buf = buf[:-364] + "%06o\0" % chksum + buf[-357:]
        self.buf = buf
        return buf

# vim: sw=2 sts=2 ts=2 

