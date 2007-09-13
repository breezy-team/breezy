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

from debian_bundle.changelog import (Changelog,
                                     Version,
                                     )

from bzrlib.tests.blackbox import ExternalBase


class TestBuilddeb(ExternalBase):

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

  def test_builddeb_registered(self):
    self.run_bzr("builddeb --help")

  def test_bd_alias(self):
    self.run_bzr("bd --help")

  def test_builddeb_not_package(self):
    self.run_bzr_error(['Could not find changelog'], 'builddeb')

  def build_really_simple_tree(self):
    tree = self.make_unpacked_source()
    self.build_tree([self.commited_file, self.uncommited_file,
                     self.unadded_file])
    tree.add([self.commited_file])
    tree.commit("one")
    tree.add([self.uncommited_file])
    return tree

  def test_builddeb_uses_working_tree(self):
    self.build_really_simple_tree()
    self.run_bzr("builddeb --native --builder true --dont-purge")
    self.assertInBuildDir([self.commited_file, self.uncommited_file])
    self.assertNotInBuildDir([self.unadded_file])

  def test_builddeb_uses_revision_when_told(self):
    self.build_really_simple_tree()
    self.run_bzr("builddeb --native --builder true --dont-purge -r-1")
    self.assertInBuildDir([self.commited_file])
    self.assertNotInBuildDir([self.unadded_file, self.uncommited_file])

  def test_builddeb_error_on_two_revisions(self):
    tree = self.make_unpacked_source()
    self.run_bzr_error(['--revision takes exactly one revision specifier.'],
                       "builddeb --native --builder true -r0..1")

  def test_builddeb_allows_building_revision_0(self):
    self.build_really_simple_tree()
    # This may break if there is something else that needs files in the
    # branch before the changelog is looked for.
    self.run_bzr_error(['Could not find changelog'],
                       "builddeb --native --builder true --dont-purge -r0")
    self.assertNotInBuildDir([self.commited_file, self.unadded_file,
                              self.uncommited_file])

