#    test_get_tar.py -- Blackbox tests for get-tar.
#    Copyright 2011 Canonical Ltd
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

try:
    from debian.changelog import (Changelog,
                                  Version,
                                  )
except ImportError:
    # Prior to 0.1.15 the debian module was called debian_bundle
    from debian_bundle.changelog import (Changelog,
                                         Version,
                                        )


from bzrlib.plugins.builddeb.tests import BuilddebTestCase


class TestGetTar(BuilddebTestCase):

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
    source_files = ['README', 'debian/'] + [cl_file]
    self.build_tree(source_files)
    c = self.make_changelog()
    self.write_changelog(c, cl_file)
    tree.add(source_files)
    return tree

  def make_source_with_upstream(self):
    """Create a source tree in a branch with an upstream tag."""
    tree = self.make_branch_and_tree('.')
    source_files = ['README']
    self.build_tree(source_files)
    tree.add(source_files)
    tree.commit("one", rev_id='revid1')
    tree.branch.tags.set_tag("upstream-0.1", tree.branch.last_revision())

    cl_file = 'debian/changelog'
    source_files = ['debian/'] + [cl_file]
    self.build_tree(source_files)
    c = self.make_changelog()
    self.write_changelog(c, cl_file)
    tree.add(source_files)
    tree.commit("two", rev_id='revid2')
    return tree

  def test_get_tar_registered(self):
    self.run_bzr("get-tar --help")

  def test_get_tar_error_no_changelog(self):
    self.run_bzr_error(
      ['Could not find changelog at "debian/changelog" or "changelog".'],
      "get-tar")

  def test_get_tar_error_no_tar(self):
    self.make_unpacked_source()
    self.run_bzr_error(
      ['Unable to find the needed upstream tarball for package test, version 0.1.'],
      "get-tar")

  def test_get_tar(self):
    tree = self.make_source_with_upstream()
    self.run_bzr(['get-tar'])
    self.assertPathExists('../test_0.1.orig.tar.gz')
