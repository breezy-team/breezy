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

from .. import BuilddebTestCase


class TestBuilddeb(BuilddebTestCase):

  commited_file = 'commited_file'
  uncommited_file = 'uncommited_file'
  unadded_file = 'unadded_file'

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

  def build_dir(self):
    return os.path.join('..', 'build-area',
                        self.package_name + '-' +
                        str(self.upstream_version))

  def assertInBuildDir(self, files):
    build_dir = self.build_dir()
    if not isinstance(files, list):
      files = [files]
    for filename in files:
      self.assertPathExists(os.path.join(build_dir, filename))

  def assertNotInBuildDir(self, files):
    build_dir = self.build_dir()
    if not isinstance(files, list):
      files = [files]
    for filename in files:
      self.assertPathDoesNotExist(os.path.join(build_dir, filename))

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
    tree.commit("one", rev_id=b'revid1')
    tree.add([self.uncommited_file])
    return tree

  def build_tree_with_conflict(self):
    tree = self.make_unpacked_source()
    self.build_tree([self.commited_file, self.uncommited_file,
                     self.unadded_file])
    tree.add([self.commited_file])
    tree.commit("one", rev_id=b'revid1')
    newtree = tree.controldir.sprout('newtree').open_workingtree()
    tree.add([self.uncommited_file])
    tree.commit("two", rev_id=b'revid2')

    p = '%s/work/newtree/%s' % (self.test_base_dir, self.uncommited_file)
    with open(p, 'w') as fh:
        fh.write('** This is the conflicting line.')
    newtree.add([self.uncommited_file])
    newtree.commit("new-two", rev_id=b'revidn2')
    conflicts = tree.merge_from_branch(newtree.branch) 

    return (conflicts, tree)

  def test_builddeb_uses_working_tree(self):
    self.build_really_simple_tree()
    self.run_bzr("builddeb --native --builder true --dont-purge")
    self.assertInBuildDir([self.commited_file, self.uncommited_file])
    self.assertNotInBuildDir([self.unadded_file])

  def test_builddeb_refuses_tree_with_conflicts(self):
    (conflicts, tree) = self.build_tree_with_conflict()
    self.assertTrue(conflicts)
    self.run_bzr_error(
      ['There are conflicts in the working tree. You must resolve these'],
      "builddeb --native --builder true --dont-purge")

  def test_builddeb_strict(self):
    tree = self.build_really_simple_tree()
    self.run_bzr_error(
      ['brz: ERROR: Build refused because there are unknown files in the tree. '
       "To list all known files, run 'bzr unknowns'."],
      "builddeb --strict")

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

  def orig_dir(self):
    return '..'

  def make_upstream_tarball(self):
    f = open(os.path.join(self.orig_dir(), self.package_name + "_" +
                          str(self.package_version.upstream_version) +
                          ".orig.tar.gz"), 'wb')
    f.close()

  def test_builder(self):
    tree = self.make_unpacked_source()
    self.run_bzr('bd --dont-purge --native --builder "touch built"')
    self.assertInBuildDir('built')

  def test_package_merge_first(self):
    tree = self.make_unpacked_source()
    self.make_upstream_tarball()
    self.run_bzr('bd --package-merge --builder true')

  def test_hooks(self):
    tree = self.make_unpacked_source()
    self.make_upstream_tarball()
    os.mkdir('.bzr-builddeb/')
    with open('.bzr-builddeb/default.conf', 'w') as f:
      f.write('[HOOKS]\npre-export = touch pre-export\n')
      f.write('pre-build = touch pre-build\npost-build = touch post-build\n')
    self.run_bzr('add .bzr-builddeb/default.conf')
    self.run_bzr('bd --dont-purge --builder true')
    self.assertPathExists('pre-export')
    self.assertInBuildDir(['pre-build', 'post-build'])

  def test_utf8_changelog(self):
    from ... import debian_changelog_commit
    from .....msgeditor import hooks
    hooks.install_named_hook("set_commit_message",
      debian_changelog_commit, "Test builddeb set commit msg hook")
    tree = self.make_unpacked_source()
    # The changelog is only used for commit message when it already exists and
    # is then changed, so need to clear it, commit, then set the contents.
    with open("debian/changelog", "w") as f:
      pass
    tree.commit("Prepare for release")
    # Would be nice to use debian.changelog to make one, but it's changed
    # across versions as to how it wants non-ascii bytes provided.
    with open("debian/changelog", "wb") as f:
      f.write(b"  * \xe2\x80\xa6and another thing")
    self.run_bzr(['commit'])
    branch = tree.branch
    self.assertEqual(u"\u2026and another thing",
      branch.repository.get_revision(branch.last_revision()).message)

# vim: ts=2 sts=2 sw=2
