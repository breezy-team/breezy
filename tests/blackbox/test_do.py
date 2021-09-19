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

from debian.changelog import (Changelog,
                              Version,
                              )
from debian.deb822 import Deb822


from .....tests.blackbox import ExternalBase


TRIVIAL_PATCH = """--- /dev/null	2012-01-02 01:09:10.986490031 +0100
+++ base/afile	2012-01-02 20:03:59.710666215 +0100
@@ -0,0 +1 @@
+a
"""


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
    c.date = 'Thu,  3 Aug 2006 19:16:22 +0100'
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
    with open(cl_file, 'w') as f:
      c.write_to_open_file(f)
    tree.add(source_files)
    source = Deb822()
    source['Source'] = self.package_name
    binary = Deb822()
    binary['Package'] = self.package_name
    binary['Architecture'] = 'all'
    with open('debian/control', 'wb') as f:
      source.dump(f)
      f.write(b'\n')
      binary.dump(f)
    tree.add('debian/control')

    self.build_tree(['debian/test-file'])
    tree.add('debian/test-file')

    return tree

  def make_merge_mode_config(self, tree):
    os.mkdir('.bzr-builddeb/')
    with open('.bzr-builddeb/default.conf', 'wb') as f:
      f.write(b'[BUILDDEB]\nmerge = True\n')
    tree.add(['.bzr-builddeb/', '.bzr-builddeb/default.conf'])

  def make_upstream_tarball(self):
    self.build_tree(['test-0.1/', 'test-0.1/a'])
    tar = tarfile.open(os.path.join('..', 'test_0.1.orig.tar.gz'),
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
      self.assertPathExists(os.path.join(build_dir, filename))

  def assertNotInBuildDir(self, files):
    build_dir = self.build_dir()
    for filename in files:
      self.assertPathDoesNotExist(os.path.join(build_dir, filename))

  def test_bd_do_registered(self):
    self.run_bzr("bd-do --help")

  def test_bd_do_not_merge(self):
    tree = self.make_unpacked_source()
    self.build_tree(['other', 'more-other'])
    tree.add(["other", "more-other"])
    self.run_bzr_error(['This command only works for merge mode packages.',
                        'See /usr/share/doc/bzr-builddeb/user_manual'
                        '/merge.html for more information.'], 'bd-do true')

  def test_fails_no_changelog(self):
    tree = self.make_branch_and_tree('.')
    self.make_merge_mode_config(tree)
    self.run_bzr_error(['Could not find changelog'], 'bd-do true')

  def test_no_copy_on_fail(self):
    tree = self.make_unpacked_source()
    self.make_merge_mode_config(tree)
    self.make_upstream_tarball()
    self.run_bzr_error(['Not updating the working tree as the command '
                        'failed.'], ['bd-do', 'touch debian/do && false'])
    self.assertPathDoesNotExist('debian/do')

  def test_copy_on_success(self):
    tree = self.make_unpacked_source()
    self.make_merge_mode_config(tree)
    self.make_upstream_tarball()
    self.run_bzr(['bd-do', 'touch debian/do'])
    self.assertPathExists('debian/do')

  def test_apply_patches(self):
    tree = self.make_unpacked_source()
    self.build_tree(["debian/patches/", "debian/source/"])
    self.build_tree_contents([
      ("debian/patches/series", "patch1\n"),
      ("debian/source/format", "3.0 (quilt)\n"),
      ("debian/patches/patch1", TRIVIAL_PATCH)])
    tree.smart_add([tree.basedir])
    self.make_merge_mode_config(tree)
    self.make_upstream_tarball()
    self.run_bzr(['bd-do', 'cp afile debian/afile'])
    self.assertPathExists('debian/afile')

  def test_removed_files_are_removed_in_branch(self):
    tree = self.make_unpacked_source()
    self.make_merge_mode_config(tree)
    self.make_upstream_tarball()
    self.run_bzr(['bd-do', 'rm debian/test-file'])
    # It might be nice if this was actually gone, but that would involve
    # either a comaparison, or removing all the files, but the latter is
    # dangerous. I guess it's a TODO to implement the comparison.
    self.assertPathExists('debian/test-file')

  def test_new_directories_created(self):
    tree = self.make_unpacked_source()
    self.make_merge_mode_config(tree)
    self.make_upstream_tarball()
    self.run_bzr(['bd-do', 'mkdir debian/dir'])
    self.assertPathExists('debian/dir')

  def test_contents_taken_from_export(self):
    tree = self.make_unpacked_source()
    self.make_merge_mode_config(tree)
    self.make_upstream_tarball()
    self.run_bzr(['bd-do', 'echo a > debian/test-file'])
    self.assertFileEqual('a\n', 'debian/test-file')

  def test_export_purged(self):
    tree = self.make_unpacked_source()
    self.make_merge_mode_config(tree)
    self.make_upstream_tarball()
    self.run_bzr(['bd-do', 'echo a > debian/test-file'])
    self.assertPathDoesNotExist(self.build_dir())

  def test_uses_shell(self):
    tree = self.make_unpacked_source()
    self.make_merge_mode_config(tree)
    self.make_upstream_tarball()
    old_shell = os.environ.get('SHELL')
    os.environ['SHELL'] = "touch debian/shell"
    try:
      self.run_bzr('bd-do')
    finally:
      if old_shell is not None:
        os.environ['SHELL'] = old_shell
      else:
        del os.environ['SHELL']
    self.assertPathExists('debian/shell')

# vim: ts=2 sts=2 sw=2
