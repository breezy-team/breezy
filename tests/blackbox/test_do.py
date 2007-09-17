#    test_do.py -- Blackbox tests for bd-do.
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

from debian_bundle.changelog import (Changelog,
                                     Version,
                                     )

from bzrlib.tests.blackbox import ExternalBase


class TestDo(ExternalBase):

  package_name = 'test'
  package_version = Version('0.1')

  commited_file = 'commited_file'
  uncommited_file = 'uncommited_file'
  unadded_file = 'unadded_file'

  def make_changelog(self, version=None):
    if version is None:
      version = self.package_version
    c = Changelog()
    c.new_block()
    c.version = Version(version)
    c.package = self.package_name
    c.distributions = 'unstable'
    c.urgency = 'low'
    c.author = 'James Westby <jw+debian@jameswestby.net>'
    c.date = 'The,  3 Aug 2006 19:16:22 +0100'
    c.add_change('')
    c.add_change('  *  test build')
    c.add_change('')
    return c

  def make_unpacked_source(self):
    """Create an unpacked source tree in a branch. Return the working tree"""
    tree = self.make_branch_and_tree('.')
    cl_file = 'debian/changelog'
    source_files = ['debian/'] + [cl_file]
    self.build_tree(source_files)
    c = self.make_changelog()
    f = open(cl_file, 'wb')
    try:
      c.write_to_open_file(f)
    finally:
      f.close()
    tree.add(source_files)
    return tree

  def make_merge_mode_config(self):
    os.mkdir('.bzr-builddeb/')
    f = open('.bzr-builddeb/default.conf', 'wb')
    try:
      f.write('[BUILDDEB]\nmerge = True\n')
    finally:
      f.close()

  def make_upstream_tarball(self):
    os.mkdir('../tarballs')
    self.build_tree(['test-0.1/', 'test-0.1/a'])
    tar = tarfile.open(os.path.join('../tarballs/', 'test_0.1.orig.tar.gz'),
                       'w:gz')
    try:
      tar.add('test-0.1')
    finally:
      tar.close()

  def build_dir(self):
    return os.path.join('..', 'build-area',
                        self.package_name + '-' +
                        str(self.package_version))

  def assertInBuildDir(self, files):
    build_dir = self.build_dir()
    for filename in files:
      self.failUnlessExists(os.path.join(build_dir, filename))

  def assertNotInBuildDir(self, files):
    build_dir = self.build_dir()
    for filename in files:
      self.failIfExists(os.path.join(build_dir, filename))

  def test_bd_do_registered(self):
    self.run_bzr("bd-do --help")

  def test_bd_do_not_merge(self):
    self.run_bzr_error(['This command only works for merge mode packages.',
                        'See /usr/share/doc/bzr-builddeb/user_manual'
                        '/merge.html for more information.'], 'bd-do true')

  def test_fails_no_changelog(self):
    self.make_merge_mode_config()
    self.run_bzr_error(['Could not find changelog'], 'bd-do true')

  def test_no_copy_on_fail(self):
    self.make_merge_mode_config()
    self.make_unpacked_source()
    self.make_upstream_tarball()
    self.run_bzr_error(['Not updating the working tree as the command '
                        'failed.'], ['bd-do', 'touch debian/do && false'])
    self.failIfExists('debian/do')

  def test_copy_on_success(self):
    self.make_merge_mode_config()
    self.make_unpacked_source()
    self.make_upstream_tarball()
    self.run_bzr(['bd-do', 'touch debian/do'])
    self.failUnlessExists('debian/do')

  def test_removed_files_are_removed_in_branch(self):
    self.make_merge_mode_config()
    self.make_unpacked_source()
    self.make_upstream_tarball()
    self.run_bzr(['bd-do', 'rm debian/changelog'])
    # It might be nice if this was actually gone, but that would involve
    # either a comaparison, or removing all the files, but the latter is
    # dangerous. I guess it's a TODO to implement the comparison.
    self.failUnlessExists('debian/changelog')

  def test_new_directories_created(self):
    self.make_merge_mode_config()
    self.make_unpacked_source()
    self.make_upstream_tarball()
    self.run_bzr(['bd-do', 'mkdir debian/dir'])
    self.failUnlessExists('debian/dir')

  def test_contents_taken_from_export(self):
    self.make_merge_mode_config()
    self.make_unpacked_source()
    self.make_upstream_tarball()
    self.run_bzr(['bd-do', 'echo a > debian/changelog'])
    self.assertFileEqual('a\n', 'debian/changelog')

  def test_export_purged(self):
    self.make_merge_mode_config()
    self.make_unpacked_source()
    self.make_upstream_tarball()
    self.run_bzr(['bd-do', 'echo a > debian/changelog'])
    self.failIfExists(self.build_dir())

  def test_uses_shell(self):
    self.make_merge_mode_config()
    self.make_unpacked_source()
    self.make_upstream_tarball()
    old_shell = os.environ['SHELL']
    os.environ['SHELL'] = "touch debian/shell"
    try:
      self.run_bzr('bd-do')
    finally:
      os.environ['SHELL'] = old_shell
    self.failUnlessExists('debian/shell')

  def test_export_upstream(self):
    self.make_merge_mode_config()
    self.make_unpacked_source()
    f = open('.bzr-builddeb/default.conf', 'ab')
    try:
      f.write('export-upstream = upstream\n')
    finally:
      f.close()
    upstream = self.make_branch_and_tree('upstream')
    self.build_tree(['upstream/a'])
    upstream.add(['a'])
    upstream.commit('one')
    self.run_bzr(['bd-do', 'mkdir debian/dir'])
    self.failUnlessExists('debian/dir')

