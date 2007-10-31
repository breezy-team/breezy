#    test_repack_tarball_extra.py -- Extra tests for repacking tarballs
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

from repack_tarball import repack_tarball

from bzrlib.errors import BzrCommandError, FileExists
from bzrlib.tests import TestCaseInTempDir


def touch(filename):
  f = open(filename, 'w')
  try:
    f.write(' ')
  finally:
    f.close()


def create_basedir(basedir, files):
  """Create the basedir that the source can be built from"""
  os.mkdir(basedir)
  for filename in [os.path.join(basedir, file) for file in files]:
    if filename.endswith('/'):
      os.mkdir(filename)
    else:
      touch(filename)


def make_new_upstream_tarball(tarball):
  tar = tarfile.open(tarball, 'w:gz')
  try:
    tar.add('package-0.2')
  finally:
    tar.close()
  shutil.rmtree('package-0.2')


def make_new_upstream_tarball_bz2(tarball):
  tar = tarfile.open(tarball, 'w:bz2')
  try:
    tar.add('package-0.2')
  finally:
    tar.close()
  shutil.rmtree('package-0.2')


class TestRepackTarballExtra(TestCaseInTempDir):

  def test_repack_tarball_errors_unkown_format(self):
    old_tarball = 'package-0.2.INVALID'
    f = open(old_tarball, 'w')
    f.close()
    self.failUnlessExists(old_tarball)
    self.assertRaises(BzrCommandError, repack_tarball, old_tarball,
                      'package_0.2.orig.tar.gz')

  def test_conditional_repack_tarball_different(self):
    tarball_name = 'package-0.2.tar.gz'
    create_basedir('package-0.2/', files=['README'])
    make_new_upstream_tarball(tarball_name)
    target_dir = 'target'
    os.mkdir(target_dir)
    create_basedir('package-0.2/', files=['README', 'NEWS'])
    make_new_upstream_tarball(os.path.join(target_dir, tarball_name))
    self.assertRaises(FileExists, repack_tarball, tarball_name,
        tarball_name, target_dir=target_dir)
    self.failUnlessExists(tarball_name)
    self.failUnlessExists(os.path.join(target_dir, tarball_name))

  def test_conditional_repack_tarball_same(self):
    tarball_name = 'package-0.2.tar.gz'
    create_basedir('package-0.2/', files=['README'])
    make_new_upstream_tarball(tarball_name)
    target_dir = 'target'
    os.mkdir(target_dir)
    shutil.copy(tarball_name, target_dir)
    repack_tarball(tarball_name, tarball_name, target_dir=target_dir)
    self.failUnlessExists(tarball_name)
    self.failUnlessExists(os.path.join(target_dir, tarball_name))

  def test_conditional_repack_different_formats(self):
    tarball_name = 'package-0.2.tar.gz'
    bz2_tarball_name = 'package-0.2.tar.bz2'
    create_basedir('package-0.2/', files=['README'])
    make_new_upstream_tarball_bz2(bz2_tarball_name)
    target_dir = 'target'
    os.mkdir(target_dir)
    create_basedir('package-0.2/', files=['README'])
    make_new_upstream_tarball(os.path.join(target_dir, tarball_name))
    self.assertRaises(FileExists, repack_tarball, bz2_tarball_name,
        tarball_name, target_dir=target_dir)
    self.failUnlessExists(bz2_tarball_name)
    self.failUnlessExists(os.path.join(target_dir, tarball_name))

# vim: ts=2 sts=2 sw=2
