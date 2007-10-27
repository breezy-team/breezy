#    test_builddeb.py -- Blackbox tests for builddeb.
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
import subprocess
import tarfile

from bzrlib.workingtree import WorkingTree

from tests import BuilddebTestCase


class TestImportDsc(BuilddebTestCase):

  upstream_dir = property(lambda self:
      self.package_name + '-' + self.upstream_version)
  upstream_tarball_name = property(lambda self:
      self.package_name + '_' + self.upstream_version + '.orig.tar.gz')
  dsc_name = property(lambda self:
      self.package_name + '_' + str(self.package_version) + '.dsc')

  def make_unpacked_upstream_source(self):
    os.mkdir(self.upstream_dir)
    files = ['README']
    self.build_tree([os.path.join(self.upstream_dir, filename)
                     for filename in files])

  def make_upstream_tarball(self):
    self.make_unpacked_upstream_source()
    tar = tarfile.open(self.upstream_tarball_name, 'w:gz')
    try:
      tar.add(self.upstream_dir)
    finally:
      tar.close()

  def make_real_source_package(self):
    self.make_upstream_tarball()
    debian_dir = os.path.join(self.upstream_dir, 'debian')
    os.mkdir(debian_dir)
    cl = self.make_changelog()
    self.write_changelog(cl, os.path.join(debian_dir, 'changelog'))
    f = open(os.path.join(debian_dir, 'control'), 'wb')
    try:
      f.write('Source: %s\n' % self.package_name)
      f.write('Maintainer: none\n')
      f.write('Standards-Version: 3.7.2\n')
      f.write('\n')
      f.write('Package: %s\n' % self.package_name)
      f.write('Architecture: all\n')
    finally:
      f.close()
    proc = subprocess.Popen('dpkg-source -b %s' % self.upstream_dir,
                            shell=True, stdout=subprocess.PIPE)
    proc.wait()
    self.assertEqual(proc.returncode, 0)
    shutil.rmtree(self.upstream_dir)

  def test_import_dsc(self):
    self.make_real_source_package()
    self.run_bzr('import-dsc --to %s %s' % (self.package_name, self.dsc_name))
    tree = WorkingTree.open(self.package_name)
    tree.lock_read()
    try:
      self.check_inventory_shape(tree.inventory,
          ['README', 'debian/', 'debian/changelog', 'debian/control'])
    finally:
      tree.unlock()
    self.assertEqual(len(tree.branch.revision_history()), 2)

