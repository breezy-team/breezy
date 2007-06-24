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

class TestImportDsc(TestCaseWithTransport):

  basedir = 'package'
  target = 'target'
  orig_1 = 'package_0.1.orig.tar.gz'
  diff_1 = 'package_0.1-1.diff.gz'
  dsc_1 = 'package_0.1-1.dsc'

  def make_base_package(self):
    os.mkdir(self.basedir)
    write_to_file(os.path.join(self.basedir, 'README'), 'hello\n')
    write_to_file(os.path.join(self.basedir, 'CHANGELOG'), 'version 1\n')
    write_to_file(os.path.join(self.basedir, 'Makefile'), 'bad command\n')

  def make_orig_1(self):
    self.make_base_package()
    tar = tarfile.open(self.orig_1, 'w:gz')
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
    write_to_file(os.path.join(diffdir, 'Makefile'), 'good command\n')
    os.system('diff -Nru %s %s | gzip -9 - > %s' % (self.basedir, diffdir,
                                                   self.diff_1))
    shutil.rmtree(diffdir)

  def make_dsc_1(self):
    self.make_orig_1()
    self.make_diff_1()
    write_to_file(self.dsc_1, """Format: 1.0
Source: package
Version: 0.1-1
Binary: package
Maintainer: maintainer <maint@maint.org>
Architecture: any
Standards-Version: 3.7.2
Build-Depends: debhelper (>= 5.0.0)
Files:
 8636a3e8ae81664bac70158503aaf53a 1328218 %s
  1acd97ad70445afd5f2a64858296f21c 20709 %s
""" % (self.orig_1, self.diff_1))

  def import_dsc_1(self):
    self.make_dsc_1()
    import_dsc(self.target, [self.dsc_1])

  def test_import_dsc_target_extant(self):
    os.mkdir(self.target)
    write_to_file('package_0.1.dsc', '')
    self.assertRaises(FileExists, import_dsc, self.target, ['package_0.1.dsc'])

  def test_import_one_dsc_tree(self):
    self.import_dsc_1()
    self.failUnlessExists(self.target)
    tree = WorkingTree.open_containing(self.target)[0]
    tree.lock_read()
    expected_inv = ['README', 'CHANGELOG', 'Makefile', 'debian/',
                    'debian/changelog']
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
    tree = WorkingTree.open_containing(self.target)[0]
    rh = tree.branch.revision_history()
    self.assertEqual(len(rh), 2)
    msg = tree.branch.repository.get_revision(rh[0]).message
    self.assertEqual(msg, 'import upstream from %s' % self.orig_1)
    msg = tree.branch.repository.get_revision(rh[1]).message
    self.assertEqual(msg, 'merge packaging changes from %s' % self.diff_1)
    changes = tree.changes_from(tree.branch.repository.revision_tree(rh[0]))
    added = changes.added
    self.assertEqual(len(added), 2)
    self.assertEqual(added[0][0], 'debian')
    self.assertEqual(added[0][2], 'directory')
    self.assertEqual(added[1][0], 'debian/changelog')
    self.assertEqual(added[1][2], 'file')
    self.assertEqual(len(changes.removed), 0)
    self.assertEqual(len(changes.renamed), 0)
    modified = changes.modified
    self.assertEqual(len(modified), 1)
    self.assertEqual(modified[0][0], 'Makefile')
    self.assertEqual(modified[0][2], 'file')
    self.assertEqual(modified[0][3], True)
    self.assertEqual(modified[0][4], False)

