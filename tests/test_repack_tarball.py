#    test_repack_tarball.py -- Testsuite for repacking of tarballs
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
import tarfile

from bzrlib.errors import (NoSuchFile,
                           FileExists,
                           NotADirectory,
                           )
from bzrlib.tests import TestCaseInTempDir

from repack_tarball import repack_tarball


def touch(filename):
  f = open(filename, 'w')
  try:
    f.write(' ')
  finally:
    f.close()


class TestRepackTarball(TestCaseInTempDir):

  basedir = 'package-0.2/'
  files = ['README']
  bare_tarball_name = 'package-0.2.tar'
  tgz_tarball_name = 'package-0.2.tgz'
  tar_gz_tarball_name = 'package-0.2.tar.gz'
  tar_bz2_tarball_name = 'package-0.2.tar.bz2'
  new_tarball = 'package_0.2.orig.tar.gz'

  def create_basedir(self):
    """Create the basedir that the source can be built from"""
    os.mkdir(self.basedir)
    for filename in [os.path.join(self.basedir, file) for file in self.files]:
      if filename.endswith('/'):
        os.mkdir(filename)
      else:
        touch(filename)

  def create_old_tarball(self):
    self.create_basedir()
    self.build_tarball()

  def test_create_old_tarball(self):
    self.create_old_tarball()
    self.failUnlessExists(self.old_tarball)

  def test_repack_tarball_non_extant(self):
    self.assertRaises(NoSuchFile, repack_tarball, self.old_tarball,
                      self.new_tarball)
  
  def test_repack_tarball_result_extant(self):
    self.create_old_tarball()
    touch(self.new_tarball)
    self.assertRaises(FileExists, repack_tarball, self.old_tarball,
                      self.new_tarball)

  def test_repack_tarball_creates_new(self):
    self.create_old_tarball()
    repack_tarball(self.old_tarball, self.new_tarball)
    self.failUnlessExists(self.old_tarball)
    self.failUnlessExists(self.new_tarball)

  def test_repack_tarball_contents(self):
    self.create_old_tarball()
    repack_tarball(self.old_tarball, self.new_tarball)
    tar = tarfile.open(self.new_tarball, 'r:gz')
    try:
      members = tar.getnames()
    finally:
      tar.close()
    self.assertEqual(members,
                     [self.basedir] +
                     [os.path.join(self.basedir, file) for file in self.files])

  def test_repack_tarball_with_target_dir(self):
    self.create_old_tarball()
    target_dir = 'tarballs'
    repack_tarball(self.old_tarball, self.new_tarball, target_dir=target_dir)
    self.failUnlessExists(target_dir)
    self.failUnlessExists(os.path.join(target_dir, self.new_tarball))
    self.failUnlessExists(self.old_tarball)

  def test_repack_tarball_with_target_dir_exists(self):
    self.create_old_tarball()
    target_dir = 'tarballs'
    os.mkdir(target_dir)
    repack_tarball(self.old_tarball, self.new_tarball, target_dir=target_dir)
    self.failUnlessExists(target_dir)
    self.failUnlessExists(os.path.join(target_dir, self.new_tarball))
    self.failUnlessExists(self.old_tarball)
    self.failIfExists(self.new_tarball)

  def test_repack_tarball_with_target_dir_not_dir(self):
    self.create_old_tarball()
    target_dir = 'tarballs'
    touch(target_dir)
    self.assertRaises(NotADirectory, repack_tarball, self.old_tarball,
                      self.new_tarball, target_dir=target_dir)
    self.failUnlessExists(self.old_tarball)
    self.failIfExists(self.new_tarball)
    self.failIfExists(os.path.join(target_dir, self.new_tarball))
    self.failUnlessExists(target_dir)

