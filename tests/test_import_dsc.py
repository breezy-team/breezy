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

from import_dsc import import_dsc

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

class TestImportDsc(TestCaseWithTransport):

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

  def make_base_package(self):
    os.mkdir(self.basedir)
    write_to_file(os.path.join(self.basedir, 'README'), 'hello\n')
    write_to_file(os.path.join(self.basedir, 'CHANGELOG'), 'version 1\n')
    write_to_file(os.path.join(self.basedir, 'Makefile'), 'bad command\n')

  def extend_base_package(self):
    write_to_file(os.path.join(self.basedir, 'NEWS'), 'new release\n')
    write_to_file(os.path.join(self.basedir, 'Makefile'), 'good command\n')

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

  def make_dsc(self, filename, version, file1, file2=None):
    write_to_file(filename, """Format: 1.0
Source: package
Version: %s
Binary: package
Maintainer: maintainer <maint@maint.org>
Architecture: any
Standards-Version: 3.7.2
Build-Depends: debhelper (>= 5.0.0)
Files:
 8636a3e8ae81664bac70158503aaf53a 1328218 %s
""" % (version, file1))
    if file2 is not None:
      append_to_file(filename,
                     " 1acd97ad70445afd5f2a64858296f21c 20709 %s" % file2)

  def make_dsc_1(self):
    self.make_orig_1()
    self.make_diff_1()
    self.make_dsc(self.dsc_1, '0.1-1', self.orig_1, self.diff_1)

  def make_dsc_1b(self):
    self.make_diff_1b()
    self.make_dsc(self.dsc_1b, '0.1-2', self.diff_1b)

  def make_dsc_1c(self):
    self.make_diff_1c()
    self.make_dsc(self.dsc_1c, '0.1-3', self.diff_1c)

  def make_dsc_2(self):
    self.make_orig_2()
    self.make_diff_2()
    self.make_dsc(self.dsc_2, '0.2-1', self.orig_2, self.diff_2)

  def import_dsc_1(self):
    self.make_dsc_1()
    import_dsc(self.target, [self.dsc_1])

  def import_dsc_1b(self):
    self.make_dsc_1()
    self.make_dsc_1b()
    import_dsc(self.target, [self.dsc_1, self.dsc_1b])

  def import_dsc_1c(self):
    self.make_dsc_1()
    self.make_dsc_1b()
    self.make_dsc_1c()
    import_dsc(self.target, [self.dsc_1, self.dsc_1c, self.dsc_1b])

  def import_dsc_2(self):
    self.make_dsc_1()
    self.make_dsc_1b()
    self.make_dsc_1c()
    self.make_dsc_2()
    import_dsc(self.target,
               [self.dsc_1, self.dsc_1b, self.dsc_1c, self.dsc_2])

  def test_import_dsc_target_extant(self):
    os.mkdir(self.target)
    write_to_file('package_0.1.dsc', '')
    self.assertRaises(FileExists, import_dsc, self.target, ['package_0.1.dsc'])

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

  def test_import_three_dsc_one_upstream_tree(self):
    self.import_dsc_1c()
    self.failUnlessExists(self.target)
    tree = WorkingTree.open(self.target)
    tree.lock_read()
    expected_inv = ['README', 'CHANGELOG', 'Makefile', 'debian/',
                    'debian/changelog', 'debian/control', 'debian/install']
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
    self.assertEqual(len(added), 1, str(added))
    self.assertEqual(added[0][0], 'debian/install')
    self.assertEqual(added[0][2], 'file')
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
    expected_inv = ['README', 'CHANGELOG', 'Makefile', 'NEWS', 'debian/',
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
    self.assertEqual(len(changes.added), 1)
    self.assertEqual(changes.added[0][0], 'NEWS')
    self.assertEqual(changes.added[0][2], 'file')
    self.assertEqual(len(changes.removed), 1)
    self.assertEqual(changes.removed[0][0], 'debian/control')
    self.assertEqual(changes.removed[0][2], 'file')
    self.assertEqual(len(changes.modified), 1)
    self.assertEqual(changes.modified[0][0], 'debian/changelog')
    self.assertEqual(changes.modified[0][2], 'file')

