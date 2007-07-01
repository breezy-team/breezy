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

from bzrlib.errors import FileExists
from bzrlib.tests import TestCaseWithTransport
from bzrlib.workingtree import WorkingTree

from errors import ImportError
from import_dsc import DscImporter

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
  diff_1 = 'package_0.1-1.diff.gz'
  diff_1b = 'package_0.1-2.diff.gz'
  diff_1c = 'package_0.1-3.diff.gz'
  diff_2 = 'package_0.2-1.diff.gz'
  dsc_1 = 'package_0.1-1.dsc'
  dsc_1b = 'package_0.1-2.dsc'
  dsc_1c = 'package_0.1-3.dsc'
  dsc_2 = 'package_0.2-1.dsc'
  native_1 = 'package_0.1.tar.gz'
  native_2 = 'package_0.2.tar.gz'
  native_dsc_1 = 'package_0.1.dsc'
  native_dsc_2 = 'package_0.2.dsc'

  def make_base_package(self):
    os.mkdir(self.basedir)
    write_to_file(os.path.join(self.basedir, 'README'), 'hello\n')
    write_to_file(os.path.join(self.basedir, 'CHANGELOG'), 'version 1\n')
    write_to_file(os.path.join(self.basedir, 'Makefile'), 'bad command\n')

  def extend_base_package(self):
    write_to_file(os.path.join(self.basedir, 'NEWS'), 'new release\n')
    write_to_file(os.path.join(self.basedir, 'Makefile'), 'good command\n')
    write_to_file(os.path.join(self.basedir, 'from_debian'), 'from debian\n')

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

  def make_diff_1(self):
    diffdir = 'package-0.1'
    shutil.copytree(self.basedir, diffdir)
    os.mkdir(os.path.join(diffdir, 'debian'))
    write_to_file(os.path.join(diffdir, 'debian', 'changelog'),
                  'version 1-1\n')
    write_to_file(os.path.join(diffdir, 'debian', 'install'), 'install\n')
    write_to_file(os.path.join(diffdir, 'Makefile'), 'good command\n')
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
    os.system('diff -Nru %s %s | gzip -9 - > %s' % (self.basedir, diffdir,
                                                   self.diff_2))

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
                    'debian/changelog', 'debian/install']
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    for path in expected_inv:
      self.failUnlessExists(os.path.join(self.target, path))
    f = open(os.path.join(self.target, 'Makefile'))
    try:
      contents = f.read()
    finally:
      f.close()
    self.assertEqual(contents, 'good command\n')
    f = open(os.path.join(self.target, 'debian', 'changelog'))
    try:
      contents = f.read()
    finally:
      f.close()
    self.assertEqual(contents, 'version 1-1\n')
    self.assertEqual(tree.changes_from(tree.basis_tree()).has_changed(),
                     False)

  def test_import_one_dsc_history(self):
    self.import_dsc_1()
    tree = WorkingTree.open(self.target)
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 2)
    msg = tree.branch.repository.get_revision(rh[0]).message
    self.assertEqual(msg, 'import upstream from %s' % self.orig_1)
    msg = tree.branch.repository.get_revision(rh[1]).message
    self.assertEqual(msg, 'merge packaging changes from %s' % self.diff_1)
    changes = tree.changes_from(tree.branch.repository.revision_tree(rh[0]))
    added = changes.added
    self.assertEqual(len(added), 3)
    self.assertEqual(added[0][0], 'debian')
    self.assertEqual(added[0][2], 'directory')
    self.assertEqual(added[1][0], 'debian/changelog')
    self.assertEqual(added[1][2], 'file')
    self.assertEqual(added[2][0], 'debian/install')
    self.assertEqual(added[2][2], 'file')
    self.assertEqual(len(changes.removed), 0)
    self.assertEqual(len(changes.renamed), 0)
    modified = changes.modified
    self.assertEqual(len(modified), 1)
    self.assertEqual(modified[0][0], 'Makefile')
    self.assertEqual(modified[0][2], 'file')
    self.assertEqual(modified[0][3], True)
    self.assertEqual(modified[0][4], False)
    tag = tree.branch.tags.lookup_tag('upstream-0.1')
    self.assertEqual(tag, rh[0])

  def test_import_two_dsc_one_upstream_tree(self):
    self.import_dsc_1b()
    self.failUnlessExists(self.target)
    tree = WorkingTree.open(self.target)
    tree.lock_read()
    expected_inv = ['README', 'CHANGELOG', 'Makefile', 'debian/',
                    'debian/changelog', 'debian/control']
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    for path in expected_inv:
      self.failUnlessExists(os.path.join(self.target, path))
    f = open(os.path.join(self.target, 'Makefile'))
    try:
      contents = f.read()
    finally:
      f.close()
    self.assertEqual(contents, 'good command\n')
    f = open(os.path.join(self.target, 'debian', 'changelog'))
    try:
      contents = f.read()
    finally:
      f.close()
    self.assertEqual(contents, 'version 1-1\nversion 1-2\n')
    self.assertEqual(tree.changes_from(tree.basis_tree()).has_changed(),
                     False)

  def test_import_two_dsc_one_upstream_history(self):
    self.import_dsc_1b()
    tree = WorkingTree.open(self.target)
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 3)
    msg = tree.branch.repository.get_revision(rh[0]).message
    self.assertEqual(msg, 'import upstream from %s' % self.orig_1)
    msg = tree.branch.repository.get_revision(rh[1]).message
    self.assertEqual(msg, 'merge packaging changes from %s' % self.diff_1)
    msg = tree.branch.repository.get_revision(rh[2]).message
    self.assertEqual(msg, 'merge packaging changes from %s' % self.diff_1b)
    changes = tree.changes_from(tree.branch.repository.revision_tree(rh[1]))
    added = changes.added
    self.assertEqual(len(added), 1, str(added))
    self.assertEqual(added[0][0], 'debian/control')
    self.assertEqual(added[0][2], 'file')
    self.assertEqual(len(changes.removed), 1)
    self.assertEqual(changes.removed[0][0], 'debian/install')
    self.assertEqual(changes.removed[0][2], 'file')
    self.assertEqual(len(changes.renamed), 0)
    modified = changes.modified
    self.assertEqual(len(modified), 1)
    self.assertEqual(modified[0][0], 'debian/changelog')
    self.assertEqual(modified[0][2], 'file')
    self.assertEqual(modified[0][3], True)
    self.assertEqual(modified[0][4], False)

  def test_import_two_dsc_one_upstream_history_repeated_diff(self):
    self.import_dsc_1b_repeated_diff()
    tree = WorkingTree.open(self.target)
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 3)
    msg = tree.branch.repository.get_revision(rh[0]).message
    self.assertEqual(msg, 'import upstream from %s' % self.orig_1)
    msg = tree.branch.repository.get_revision(rh[1]).message
    self.assertEqual(msg, 'merge packaging changes from %s' % self.diff_1)
    msg = tree.branch.repository.get_revision(rh[2]).message
    self.assertEqual(msg, 'merge packaging changes from %s' % self.diff_1b)
    changes = tree.changes_from(tree.branch.repository.revision_tree(rh[1]))
    added = changes.added
    self.assertEqual(len(added), 1, str(added))
    self.assertEqual(added[0][0], 'debian/control')
    self.assertEqual(added[0][2], 'file')
    self.assertEqual(len(changes.removed), 1)
    self.assertEqual(changes.removed[0][0], 'debian/install')
    self.assertEqual(changes.removed[0][2], 'file')
    self.assertEqual(len(changes.renamed), 0)
    modified = changes.modified
    self.assertEqual(len(modified), 1)
    self.assertEqual(modified[0][0], 'debian/changelog')
    self.assertEqual(modified[0][2], 'file')
    self.assertEqual(modified[0][3], True)
    self.assertEqual(modified[0][4], False)

  def test_import_three_dsc_one_upstream_tree(self):
    self.import_dsc_1c()
    self.failUnlessExists(self.target)
    tree = WorkingTree.open(self.target)
    tree.lock_read()
    expected_inv = ['README', 'CHANGELOG', 'Makefile', 'from_debian',
                    'debian/', 'debian/changelog', 'debian/control',
                    'debian/install']
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    for path in expected_inv:
      self.failUnlessExists(os.path.join(self.target, path))
    f = open(os.path.join(self.target, 'Makefile'))
    try:
      contents = f.read()
    finally:
      f.close()
    self.assertEqual(contents, 'good command\n')
    f = open(os.path.join(self.target, 'debian', 'changelog'))
    try:
      contents = f.read()
    finally:
      f.close()
    self.assertEqual(contents, 'version 1-1\nversion 1-2\nversion 1-3\n')
    self.assertEqual(tree.changes_from(tree.basis_tree()).has_changed(),
                     False)

  def test_import_three_dsc_one_upstream_history(self):
    self.import_dsc_1c()
    tree = WorkingTree.open(self.target)
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 4)
    msg = tree.branch.repository.get_revision(rh[0]).message
    self.assertEqual(msg, 'import upstream from %s' % self.orig_1)
    msg = tree.branch.repository.get_revision(rh[1]).message
    self.assertEqual(msg, 'merge packaging changes from %s' % self.diff_1)
    msg = tree.branch.repository.get_revision(rh[2]).message
    self.assertEqual(msg, 'merge packaging changes from %s' % self.diff_1b)
    msg = tree.branch.repository.get_revision(rh[3]).message
    self.assertEqual(msg, 'merge packaging changes from %s' % self.diff_1c)
    changes = tree.changes_from(tree.branch.repository.revision_tree(rh[2]))
    added = changes.added
    self.assertEqual(len(added), 2, str(added))
    self.assertEqual(added[0][0], 'debian/install')
    self.assertEqual(added[0][2], 'file')
    self.assertEqual(added[1][0], 'from_debian')
    self.assertEqual(len(changes.removed), 0)
    self.assertEqual(len(changes.renamed), 0)
    modified = changes.modified
    self.assertEqual(len(modified), 1)
    self.assertEqual(modified[0][0], 'debian/changelog')
    self.assertEqual(modified[0][2], 'file')
    self.assertEqual(modified[0][3], True)
    self.assertEqual(modified[0][4], False)

  def test_import_three_dsc_two_upstream_tree(self):
    self.import_dsc_2()
    self.failUnlessExists(self.target)
    tree = WorkingTree.open(self.target)
    tree.lock_read()
    expected_inv = ['README', 'CHANGELOG', 'Makefile', 'NEWS', 'from_debian',
                    'debian/', 'debian/changelog', 'debian/install']
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    for path in expected_inv:
      self.failUnlessExists(os.path.join(self.target, path))
    f = open(os.path.join(self.target, 'Makefile'))
    try:
      contents = f.read()
    finally:
      f.close()
    self.assertEqual(contents, 'good command\n')
    f = open(os.path.join(self.target, 'debian', 'changelog'))
    try:
      contents = f.read()
    finally:
      f.close()
    self.assertEqual(contents,
                     'version 1-1\nversion 1-2\nversion 1-3\nversion 2-1\n')
    self.assertEqual(tree.changes_from(tree.basis_tree()).has_changed(),
                     False)

  def test_import_four_dsc_two_upstream_history(self):
    self.import_dsc_2()
    tree = WorkingTree.open(self.target)
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 3)
    msg = tree.branch.repository.get_revision(rh[0]).message
    self.assertEqual(msg, 'import upstream from %s' % self.orig_1)
    msg = tree.branch.repository.get_revision(rh[1]).message
    self.assertEqual(msg, 'import upstream from %s' % self.orig_2)
    msg = tree.branch.repository.get_revision(rh[2]).message
    self.assertEqual(msg, 'merge packaging changes from %s' % self.diff_2)
    parents = tree.branch.repository.revision_tree(rh[1]).get_parent_ids()
    self.assertEqual(parents, [rh[0]], rh)
    parents = tree.branch.repository.revision_tree(rh[2]).get_parent_ids()
    self.assertEqual(len(parents), 2)
    self.assertEqual(parents[0], rh[1], rh)
    self.assertEqual(tree.branch.repository.get_revision(parents[1]).message,
                     'merge packaging changes from %s' % self.diff_1c)
    # Check the diff against upstream.
    changes = tree.changes_from(tree.branch.repository.revision_tree(rh[1]))
    added = changes.added
    self.assertEqual(len(added), 3, str(added))
    self.assertEqual(added[0][0], 'debian')
    self.assertEqual(added[0][2], 'directory')
    self.assertEqual(added[1][0], 'debian/changelog')
    self.assertEqual(added[1][2], 'file')
    self.assertEqual(added[2][0], 'debian/install')
    self.assertEqual(added[2][2], 'file')
    self.assertEqual(changes.removed, [])
    self.assertEqual(changes.modified, [])
    # Check the diff against last packaging version
    changes = tree.changes_from(
                 tree.branch.repository.revision_tree(parents[1]))
    self.assertEqual(len(changes.added), 1, str(changes.added))
    self.assertEqual(changes.added[0][0], 'NEWS')
    self.assertEqual(changes.added[0][2], 'file')
    self.assertEqual(len(changes.removed), 1)
    self.assertEqual(changes.removed[0][0], 'debian/control')
    self.assertEqual(changes.removed[0][2], 'file')
    self.assertEqual(len(changes.modified), 1)
    self.assertEqual(changes.modified[0][0], 'debian/changelog')
    self.assertEqual(changes.modified[0][2], 'file')

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
    msg = tree.branch.repository.get_revision(rh[0]).message
    self.assertEqual(msg, 'import upstream from %s' % self.orig_1)
    msg = tree.branch.repository.get_revision(rh[1]).message
    self.assertEqual(msg, 'import upstream from %s' % self.orig_2)
    msg = tree.branch.repository.get_revision(rh[2]).message
    self.assertEqual(msg, 'merge packaging changes from %s' % self.diff_2)
    parents = tree.branch.repository.revision_tree(rh[1]).get_parent_ids()
    self.assertEqual(parents, [rh[0]], rh)
    parents = tree.branch.repository.revision_tree(rh[2]).get_parent_ids()
    self.assertEqual(len(parents), 2)
    self.assertEqual(parents[0], rh[1], rh)
    self.assertEqual(tree.branch.repository.get_revision(parents[1]).message,
                     'merge packaging changes from %s' % self.diff_1c)
    # Check the diff against upstream.
    changes = tree.changes_from(tree.branch.repository.revision_tree(rh[1]))
    added = changes.added
    self.assertEqual(len(added), 3, str(added))
    self.assertEqual(added[0][0], 'debian')
    self.assertEqual(added[0][2], 'directory')
    self.assertEqual(added[1][0], 'debian/changelog')
    self.assertEqual(added[1][2], 'file')
    self.assertEqual(added[2][0], 'debian/install')
    self.assertEqual(added[2][2], 'file')
    self.assertEqual(changes.removed, [])
    self.assertEqual(changes.modified, [])
    # Check the diff against last packaging version
    changes = tree.changes_from(
                 tree.branch.repository.revision_tree(parents[1]))
    self.assertEqual(len(changes.added), 1)
    self.assertEqual(changes.added[0][0], 'NEWS')
    self.assertEqual(changes.added[0][2], 'file')
    self.assertEqual(len(changes.removed), 1)
    self.assertEqual(changes.removed[0][0], 'debian/control')
    self.assertEqual(changes.removed[0][2], 'file')
    self.assertEqual(len(changes.modified), 1)
    self.assertEqual(changes.modified[0][0], 'debian/changelog')
    self.assertEqual(changes.modified[0][2], 'file')

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
                    'debian/changelog', 'debian/install']
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    for path in expected_inv:
      self.failUnlessExists(os.path.join(self.target, path))

  def make_native_dsc_1(self):
    self.make_base_package()
    os.mkdir(os.path.join(self.basedir, 'debian'))
    write_to_file(os.path.join(self.basedir, 'debian', 'changelog'),
                  'version 1\n')
    tar = tarfile.open(self.native_1, 'w:gz')
    try:
      tar.add(self.basedir)
    finally:
      tar.close()
    self.make_dsc(self.native_dsc_1, '0.1', self.native_1)

  def make_native_dsc_2(self):
    self.extend_base_package()
    append_to_file(os.path.join(self.basedir, 'debian', 'changelog'),
                   'version 2\n')
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
                    'debian/changelog']
    tree.lock_read()
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 1)
    rev = tree.branch.repository.get_revision(rh[0])
    self.assertEqual(rev.message,
                     "import package from %s" % \
                     os.path.basename(self.native_1))
    self.assertEqual(len(tree.get_parent_ids()), 1)

  def test_import_dsc_native_double(self):
    self.make_native_dsc_1()
    self.make_native_dsc_2()
    importer = DscImporter([self.native_dsc_1, self.native_dsc_2])
    importer.import_dsc(self.target)
    tree = WorkingTree.open(self.target)
    expected_inv = ['CHANGELOG', 'README', 'Makefile', 'NEWS', 'from_debian',
                    'debian/', 'debian/changelog']
    tree.lock_read()
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 2)
    rev = tree.branch.repository.get_revision(rh[0])
    self.assertEqual(rev.message,
                     "import package from %s" % \
                     os.path.basename(self.native_1))
    rev = tree.branch.repository.get_revision(rh[1])
    self.assertEqual(rev.message,
                     "import package from %s" % \
                     os.path.basename(self.native_2))
    self.assertEqual(len(tree.get_parent_ids()), 1)
    parents = tree.branch.repository.revision_tree(rh[1]).get_parent_ids()
    self.assertEqual(len(parents), 1)

  def test_non_native_to_native(self):
    self.make_dsc_1()
    self.make_native_dsc_2_after_non_native()
    importer = DscImporter([self.dsc_1, self.native_dsc_2])
    importer.import_dsc(self.target)
    tree = WorkingTree.open(self.target)
    expected_inv = ['CHANGELOG', 'README', 'Makefile', 'NEWS', 'from_debian',
                    'debian/', 'debian/changelog']
    tree.lock_read()
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    self.assertEqual(tree.changes_from(tree.basis_tree()).has_changed(), False)
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 2)
    rev = tree.branch.repository.get_revision(rh[0])
    self.assertEqual(rev.message,
                     "import upstream from %s" % \
                     os.path.basename(self.orig_1))
    rev = tree.branch.repository.get_revision(rh[1])
    self.assertEqual(rev.message,
                     "import package from %s" % \
                     os.path.basename(self.native_2))
    self.assertEqual(len(tree.get_parent_ids()), 1)
    parents = tree.branch.repository.revision_tree(rh[1]).get_parent_ids()
    self.assertEqual(len(parents), 2)
    rev = tree.branch.repository.get_revision(parents[1])
    self.assertEqual(rev.message,
                     "merge packaging changes from %s" % \
                     os.path.basename(self.diff_1))
    changes = tree.changes_from(tree.branch.repository.revision_tree(rh[0]))
    self.assertEqual(len(changes.added), 4)
    self.assertEqual(changes.added[0][0], 'NEWS')
    self.assertEqual(changes.added[1][0], 'debian')
    self.assertEqual(changes.added[2][0], 'debian/changelog')
    self.assertEqual(changes.added[3][0], 'from_debian')
    self.assertEqual(len(changes.modified), 1)
    self.assertEqual(changes.modified[0][0], 'Makefile')
    self.assertEqual(changes.removed, [])
    changes = tree.changes_from(
                    tree.branch.repository.revision_tree(parents[1]))
    self.assertEqual(len(changes.added), 2)
    self.assertEqual(changes.added[0][0], 'NEWS')
    self.assertEqual(changes.added[1][0], 'from_debian')
    self.assertEqual(len(changes.modified), 1, str(changes.modified))
    self.assertEqual(changes.modified[0][0], 'debian/changelog')
    self.assertEqual(len(changes.removed), 1)
    self.assertEqual(changes.removed[0][0], 'debian/install')

  def test_native_to_non_native(self):
    self.make_native_dsc_1()
    shutil.rmtree(os.path.join(self.basedir, 'debian'))
    self.make_dsc_2()
    importer = DscImporter([self.native_dsc_1, self.dsc_2])
    importer.import_dsc(self.target)
    tree = WorkingTree.open(self.target)
    expected_inv = ['CHANGELOG', 'README', 'Makefile', 'NEWS', 'from_debian',
                    'debian/', 'debian/changelog', 'debian/install']
    tree.lock_read()
    try:
      self.check_inventory_shape(tree.inventory, expected_inv)
    finally:
      tree.unlock()
    self.assertEqual(tree.changes_from(tree.basis_tree()).has_changed(), False)
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 3)
    rev = tree.branch.repository.get_revision(rh[0])
    self.assertEqual(rev.message,
                     "import package from %s" % \
                     os.path.basename(self.native_1))
    rev = tree.branch.repository.get_revision(rh[1])
    self.assertEqual(rev.message,
                     "import upstream from %s" % \
                     os.path.basename(self.orig_2))
    rev = tree.branch.repository.get_revision(rh[2])
    self.assertEqual(rev.message,
                     "merge packaging changes from %s" % \
                     os.path.basename(self.diff_2))
    self.assertEqual(len(tree.get_parent_ids()), 1)
    parents = tree.branch.repository.revision_tree(rh[1]).get_parent_ids()
    self.assertEqual(len(parents), 1)
    parents = tree.branch.repository.revision_tree(rh[2]).get_parent_ids()
    self.assertEqual(len(parents), 1)
    up_tree = tree.branch.repository.revision_tree(rh[1])
    changes = tree.changes_from(up_tree)
    self.assertEqual(len(changes.added), 3)
    self.assertEqual(changes.added[0][0], 'debian')
    self.assertEqual(changes.added[1][0], 'debian/changelog')
    self.assertEqual(changes.added[2][0], 'debian/install')
    self.assertEqual(changes.modified, [])
    self.assertEqual(changes.removed, [])
    changes = up_tree.changes_from(tree.branch.repository.revision_tree(rh[0]))
    self.assertEqual(len(changes.added), 2)
    self.assertEqual(changes.added[0][0], 'NEWS')
    self.assertEqual(changes.added[1][0], 'from_debian')
    self.assertEqual(len(changes.modified), 1, str(changes.modified))
    self.assertEqual(changes.modified[0][0], 'Makefile')
    self.assertEqual(len(changes.removed), 2)
    self.assertEqual(changes.removed[0][0], 'debian')
    self.assertEqual(changes.removed[1][0], 'debian/changelog')
    # FIXME: Should changelog etc. be added/removed or not?
    changes = tree.changes_from(tree.branch.repository.revision_tree(rh[0]))
    self.assertEqual(len(changes.added), 5, str(changes.added))
    self.assertEqual(changes.added[0][0], 'NEWS')
    self.assertEqual(changes.added[1][0], 'debian')
    self.assertEqual(changes.added[2][0], 'debian/changelog')
    self.assertEqual(changes.added[3][0], 'debian/install')
    self.assertEqual(changes.added[4][0], 'from_debian')
    self.assertEqual(len(changes.modified), 1)
    self.assertEqual(changes.modified[0][0], 'Makefile')
    self.assertEqual(len(changes.removed), 2)
    self.assertEqual(changes.removed[0][0], 'debian')
    self.assertEqual(changes.removed[1][0], 'debian/changelog')

