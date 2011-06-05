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

from bzrlib.transport import get_transport

from bzrlib.plugins.builddeb.tests import BuilddebTestCase
from bzrlib.plugins.builddeb.tests.test_import_dsc import PristineTarFeature


class TestBaseImportDsc(BuilddebTestCase):

  def _upstream_dir(self, package_name, upstream_version):
    return package_name + '-' + upstream_version
  upstream_dir = property(lambda self:self._upstream_dir(self.package_name,
      self.upstream_version))
  def _upstream_tarball_name(self, package_name, upstream_version):
    return package_name + '_' + upstream_version + '.orig.tar.gz'
  upstream_tarball_name = property(lambda self:
      self._upstream_tarball_name(self.package_name, self.upstream_version))
  dsc_name = property(lambda self:
      self.package_name + '_' + str(self.package_version) + '.dsc')

  def make_unpacked_upstream_source(self, transport=None):
    if transport is None:
      transport = get_transport(self.upstream_dir)
    transport.ensure_base()
    self.build_tree(['README'], transport=transport)

  def get_test_upstream_version(self, upstream_version):
    """Return the upstream_version to be used in a test helper method."""
    if upstream_version is None:
        return self.upstream_version
    else:
        return upstream_version

  def make_upstream_tarball(self, upstream_version=None):
    upstream_version = self.get_test_upstream_version(upstream_version)
    upstream_dir = self._upstream_dir(self.package_name, upstream_version)
    self.make_unpacked_upstream_source(get_transport(upstream_dir))
    tar = tarfile.open(
        self._upstream_tarball_name(self.package_name, upstream_version),
        'w:gz')
    try:
      tar.add(self.upstream_dir)
    finally:
      tar.close()

  def make_debian_dir(self, debian_dir):
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

  def make_real_source_package(self):
    self.make_upstream_tarball()
    debian_dir = os.path.join(self.upstream_dir, 'debian')
    self.make_debian_dir(debian_dir)
    proc = subprocess.Popen('dpkg-source -b %s' % self.upstream_dir,
                            shell=True, stdout=subprocess.PIPE)
    proc.wait()
    self.assertEqual(proc.returncode, 0)
    shutil.rmtree(self.upstream_dir)


class TestImportDsc(TestBaseImportDsc):

  def test_import_dsc(self):
    self.requireFeature(PristineTarFeature)
    self.make_real_source_package()
    tree = self.make_branch_and_tree('.')
    self.run_bzr('import-dsc %s' % self.dsc_name)
    tree.lock_read()
    expected_shape = ['README', 'debian/', 'debian/changelog',
        'debian/control']
    try:
      if getattr(self, "check_tree_shape", None):
        self.check_tree_shape(tree, expected_shape)
      else:
        self.check_inventory_shape(tree.inventory, expected_shape)
    finally:
      tree.unlock()
    self.assertEqual(len(tree.branch.revision_history()), 2)

  def test_import_no_files(self):
    self.make_branch_and_tree('.')
    self.make_real_source_package()
    self.run_bzr_error(['You must give the location of at least one source '
        'package.'], 'import-dsc')


# vim: ts=2 sts=2 sw=2
