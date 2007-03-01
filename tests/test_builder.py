#    __init__.py -- Testsuite for builddeb builder.py
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

import commands
import os
from os.path import join
import tarfile

from debian_bundle.changelog import (Changelog, Version)

from bzrlib.tests import (TestCaseInTempDir,
                          TestCaseWithTransport,
                          )

from builder import (remove_dir,
                     remove_bzrbuilddeb_dir,
                     remove_debian_dir,
                     DebBuild,
                     DebNativeBuild,
                     DebSplitBuild,
                     DebMergeBuild,
                     )
import errors
from properties import BuildProperties

class TestUtil(TestCaseInTempDir):
  """Test the utility functions from builder.py."""

  def test_remove_dir(self):
    """Test that remove_dir correctly removes teh named directory/."""
    os.mkdir('dir1')
    os.mkdir('dir2')
    self.assert_(os.path.isdir('dir1'))
    self.assert_(os.path.isdir('dir2'))
    remove_dir('.', 'dir1')
    self.failIf(os.path.exists('dir1'))
    self.assert_(os.path.isdir('dir2'))

  def test_remove_dir_in_dir(self):
    """Test that remove_dir correctly removes a subdir."""
    os.mkdir('dir1')
    os.mkdir('dir2')
    self.assert_(os.path.isdir('dir1'))
    self.assert_(os.path.isdir('dir2'))
    os.mkdir(join('dir1', 'subdir1'))
    os.mkdir(join('dir1', 'subdir2'))
    os.mkdir(join('dir2', 'subdir1'))

    self.assert_(os.path.isdir(join('dir1', 'subdir1')))
    self.assert_(os.path.isdir(join('dir1', 'subdir2')))
    self.assert_(os.path.isdir(join('dir2', 'subdir1')))
    remove_dir('dir1', 'subdir1')
    self.failIf(os.path.exists(join('dir1', 'subdir1')))
    self.assert_(os.path.isdir(join('dir1', 'subdir2')))
    self.assert_(os.path.isdir(join('dir2', 'subdir1')))

  def test_remove_dir_works_on_non_empty_dirs(self):
    """Test that t can remove a non empty dir"""
    os.mkdir('dir1')
    os.mkdir(join('dir1', 'subdir1'))
    self.assert_(os.path.isdir(join('dir1', 'subdir1')))
    remove_dir('.', 'dir1')
    self.failIf(os.path.exists('dir1'))

  def test_remove_dir_copes_with_no_dir(self):
    """Test that it doesn't fail if the path doesn't exist."""
    self.failIf(os.path.exists('dir1'))
    remove_dir('.', 'dir1')

  def test_remove_dir_no_remove_file(self):
    """Test that it doesn't remove files"""
    file = open('file', 'w')
    file.write('test\n')
    file.close()
    self.assert_(os.path.exists('file'))
    remove_dir('.', 'file')
    self.assert_(os.path.exists('file'))

  def test_remove_dir_no_remove_symlink(self):
    """Test that it neither removes the symlink or the target."""
    os.mkdir('dir1')
    os.symlink('dir1', 'link1')
    self.assert_(os.path.exists('dir1'))
    self.assert_(os.path.exists('link1'))
    remove_dir(',', 'link1')
    self.assert_(os.path.exists('dir1'))
    self.assert_(os.path.exists('link1'))

  def test_remove_bzr_builddeb_dir(self):
    """Tests that a dir named .bzr-buiddeb is removed"""
    os.mkdir('.bzr-builddeb')
    self.assert_(os.path.exists('.bzr-builddeb'))
    remove_bzrbuilddeb_dir('.')
    self.failIf(os.path.exists('.bzr-builddeb'))

  def test_remove_debian_dir(self):
    """Tests that a dir named debian/ is removed"""
    os.mkdir('debian')
    self.assert_(os.path.exists('debian'))
    remove_debian_dir('.')
    self.failIf(os.path.exists('debian'))

class BuilderTestCase(TestCaseWithTransport):
  """A class that helps with the testing of builders."""

  package_name = 'test'
  package_version = Version('0.1-1')
  upstream_version = property(lambda self: \
                              self.package_version.upstream_version)

  def __init__(self, *args, **kwargs):
    self.basedir = 'base'
    self.build_dir = join(self.basedir, 'build')
    self.orig_dir = join(self.basedir, 'orig')
    self.result_dir = join(self.basedir, 'result')
    self.branch_dir = join(self.basedir, 'branch')
    self.source_dir = join(self.build_dir,
                           self.package_name + '-' + self.upstream_version)
    self.tarball_name = self.package_name + '_' + self.upstream_version + \
                        '.orig.tar.gz'
    super(BuilderTestCase, self).__init__(*args, **kwargs)

  def make_properties(self, changelog, larstiq):
    return BuildProperties(changelog, self.build_dir, self.orig_dir, larstiq)

  def change_to_branch_dir(self):
    os.chdir(self.branch_dir)

  def _make_branch(self):
    os.mkdir(self.basedir)
    tree = self.make_branch_and_tree(self.branch_dir)
    branch = tree.branch
    return (tree, branch)

  def build_tree(self, files, *args, **kwargs):
    #divert in to base
    newfiles = []
    for filename in files:
      newfiles.append(join('base', filename))
    super(BuilderTestCase, self).build_tree(newfiles, *args, **kwargs)

  def make_orig_tarball(self):
    os.mkdir(self.orig_dir)
    tarball = join(self.orig_dir, self.tarball_name)
    f = open(tarball, 'wb')
    f.close()

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

  def write_changelog(self, changelog, filename):
    f = open(filename, 'w')
    c.write_to_open_file(f)
    f.close()

  def get_arch(self):
    status, arch = commands.getstatusoutput(
        'dpkg-architecture -qDEB_BUILD_ARCH')
    if status > 0:
      self.fail("Couldn't discover arch")
    return arch

  def changes_filename(self):
    arch = self.get_arch()
    changesfilename = "%s_%s_%s.changes" % (self.package_name,
                                            self.package_version, arch)
    return changesfilename

  def make_changes_file(self):
    os.mkdir(self.build_dir)
    arch = self.get_arch()
    changesfilename = self.changes_filename()
    changesfile = open(join(self.build_dir, changesfilename), 'wb')
    changesfile.write("""Format: 1.7
Date: Wed, 31 Jan 2007 20:15:42 +0000
Source: """)
    changesfile.write(self.package_name)
    changesfile.write("\nBinary: %s" % self.package_name)
    changesfile.write("\nArchitecture: source %s" % arch)
    changesfile.write("\nVersion: %s" % self.package_version)
    changesfile.write("""
Distribution: experimental
Urgency: low
Maintainer: Noone <noone@nowhere.con>
Changed-By: Noone <noone@nowhere.com>
Description:
 test - A test package
Changes:""")
    changesfile.write("\n %s (%s) experimental; urgency=low" % (
                                self.package_name, self.package_version))
    changesfile.write("""
 .
   * A change.
Files:
 7fee96643187b7d498ca2ef32aea1b3c 441 devel optional """)
    changesfile.write("%s_%s.dsc\n" % (self.package_name, self.package_version))
    changesfile.write(" 3808bdf49220a86f097316207f8a7fce 24786 devel optional ")
    changesfile.write("%s_%s.tar.gz\n" % (self.package_name,
                                        self.package_version))
    changesfile.write(" 645fb698444a226c55e9af861604d643 29574 devel optional ")
    changesfile.write("%s_%s_%s.deb\n" % (self.package_name,
                                        self.package_version, arch))
    changesfile.close()

  def get_result_filenames(self):
    """Return a list of the filenames that a build might produce."""
    arch = self.get_arch()
    dsc = "%s_%s.dsc" % (self.package_name, self.package_version)
    tar = "%s_%s.tar.gz" % (self.package_name, self.package_version)
    deb = "%s_%s_%s.deb" % (self.package_name, self.package_version, arch)
    return [dsc, tar, deb]

  def make_result_files(self):
    """Make the files to go along with the .changes file."""
    for filename in self.get_result_filenames():
      f = open(join(self.build_dir, filename), 'wb')
      f.close()

  def get_builder(self, version=None, wt=None, larstiq=False):
    raise NotImplementedError("You must provide this method in the subclass")

class TestDefaultBuilder(BuilderTestCase):
  """Test the default builder (full source, non-native)"""

  def get_builder(self, version=None, wt=None, larstiq=False):
    """Returns a builder set up for this type."""
    if wt is None:
      (wt, branch) = self._make_branch()
    changelog = self.make_changelog(version=version)
    properties = self.make_properties(changelog, larstiq)
    return DebBuild(properties, wt)

  def test_prepare_creates_build_dir(self):
    """Test that the build dir is created correctly."""
    builder = self.get_builder()
    self.failIfExists(self.build_dir)
    builder.prepare(False)
    self.failUnlessExists(self.build_dir)

  def test_prepare_allows_build_dir_to_exist(self):
    """Test that prepare doen't fall over if the build dir exists."""
    builder = self.get_builder()
    os.mkdir(self.build_dir)
    self.failUnlessExists(self.build_dir)
    builder.prepare(False)
    self.failUnlessExists(self.build_dir)

  def test_prepare_purges_the_source_dir(self):
    """Test that the source dir is purged if not keep_source_dir."""
    builder = self.get_builder()
    os.mkdir(self.build_dir)
    os.mkdir(self.source_dir)
    self.failUnlessExists(self.source_dir)
    builder.prepare(False)
    self.failIfExists(self.source_dir)

  def test_prepare_keeps_the_source_dir(self):
    """Test that the source dir is kept if keep_source_dir."""
    builder = self.get_builder()
    os.mkdir(self.build_dir)
    os.mkdir(self.source_dir)
    self.failUnlessExists(self.source_dir)
    builder.prepare(True)
    self.failUnlessExists(self.source_dir)

  def test_prepare_errors_on_keep_source_dir_and_it_doesnt_exist(self):
    """Test that there is an exception if keep_source_dir and there is none."""
    builder = self.get_builder()
    self.failIfExists(self.source_dir)
    self.assertRaises(errors.NoSourceDirError, builder.prepare, True)
    self.failIfExists(self.source_dir)

  def test__tarball_name_native(self):
    """Test the correct upstream tarball name for native package."""
    version = '0.1'
    builder = self.get_builder(version)
    self.assertEqual(builder._tarball_name(),
                     self.package_name+'_' + version + '.orig.tar.gz')

  def test__tarball_name_non_native(self):
    """Test the correct upstream tarball name for non-native package."""
    builder = self.get_builder()
    self.assertEqual(builder._tarball_name(),
                     self.package_name + '_' + self.upstream_version + \
                     '.orig.tar.gz')

  def test__find_tarball_present(self):
    """Test that _find_tarball returns the correct path if present."""
    builder = self.get_builder()
    tarball = join(self.orig_dir, builder._tarball_name())
    self.make_orig_tarball()
    self.failUnlessExists(tarball)
    self.assertEqual(builder._find_tarball(), tarball)

  def test__find_tarball_no_orig_dir(self):
    """Test that an exception is raised it the orig dir is not present."""
    builder = self.get_builder()
    self.failIfExists(self.orig_dir)
    self.assertRaises(errors.DebianError, builder._find_tarball)

  def test__find_tarball_not_exists(self):
    """Test that an exception is raised if the tarball is not found."""
    builder = self.get_builder()
    os.mkdir(self.orig_dir)
    tarball = join(self.orig_dir, builder._tarball_name())
    self.failIfExists(tarball)
    self.assertRaises(errors.DebianError, builder._find_tarball)

  def test_export_copies_tarball(self):
    """Test that the tarball is copied in to the build dir."""
    builder = self.get_builder()
    self.make_orig_tarball()
    builder.prepare()
    builder.export()
    self.failUnlessExists(join(self.build_dir, self.tarball_name))

  def test_export_use_existing_doesnt_copy_tarball(self):
    """Test that the tarball is not copied in to the build dir.
    
    If use_existing is given then the tarball should not be copied.
    This is currently checked by just not creating the one in the orig_dir
    and checking that it doesn't barf. It might be better to use a checksum
    or similar to make it more robust.
    
    This might not be the desired behaviour, but add a test for it
    either way."""
    builder = self.get_builder()
    builder.prepare()
    builder.export(use_existing=True)
    self.failIfExists(join(self.build_dir, self.tarball_name))

  def test_export_creates_source_dir(self):
    """Test that the source dir is created on export."""
    builder = self.get_builder()
    self.make_orig_tarball()
    builder.prepare()
    builder.export()
    self.failUnlessExists(self.source_dir)

  def test_export_has_correct_contents_in_source_dir(self):
    """Test that the exported source dir has the correct contents."""
    wt = self.make_branch_and_tree(self.basedir)
    self.build_tree(['a', 'b'])
    wt.add(['a', 'b'])
    wt.commit('commit one')
    self.build_tree(['c', 'd'])
    wt.add(['c'])
    wt.remove(['b'])
    builder = self.get_builder(wt=wt)
    self.make_orig_tarball()
    builder.prepare()
    builder.export()
    self.failUnlessExists(join(self.source_dir, 'a'))
    self.failIfExists(join(self.source_dir, 'b'))
    self.failUnlessExists(join(self.source_dir, 'c'))
    self.failIfExists(join(self.source_dir, 'd'))

  def test_export_removes_builddeb_dir(self):
    """Test that the builddeb dir is removed from the export."""
    wt = self.make_branch_and_tree(self.basedir)
    files = ['a', '.bzr-builddeb/', '.bzr-builddeb/default.conf']
    self.build_tree(files)
    wt.add(files)
    wt.commit('commit one')
    builder = self.get_builder(wt=wt)
    self.make_orig_tarball()
    builder.prepare()
    builder.export()
    self.failUnlessExists(join(self.source_dir, 'a'))
    self.failIfExists(join(self.source_dir, '.bzr-builddeb'))

  def test_build(self):
    """Test that the build command is run correctly."""
    builder = self.get_builder()
    self.make_orig_tarball()
    builder.prepare()
    builder.export()
    self.failIfExists(join(self.source_dir, 'built'))
    builder.build('touch built')
    self.failUnlessExists(join(self.source_dir, 'built'))

  def test_build_fails(self):
    """Test that a failing build raises an error."""
    builder = self.get_builder()
    self.make_orig_tarball()
    builder.prepare()
    builder.export()
    self.assertRaises(errors.BuildFailedError, builder.build, 'false')

  def test_clean(self):
    """Test that clean removes the source dir."""
    builder = self.get_builder()
    os.mkdir(self.build_dir)
    os.mkdir(self.source_dir)
    # make it non-empty for good measure
    f = open(join(self.source_dir, 'file'), 'wb')
    f.close()
    self.failUnlessExists(self.source_dir)
    builder.clean()
    self.failIfExists(self.source_dir)

  def test_move_result_creates_result_dir(self):
    """Test that move_result creates the result directory."""
    builder = self.get_builder()
    self.make_changes_file()
    self.make_result_files()
    self.failIfExists(self.result_dir)
    builder.move_result(self.result_dir)
    self.failUnlessExists(self.result_dir)

  def test_move_result_allows_existing_result_dir(self):
    """Test that move_result doesn't choke if the result directory exists."""
    builder = self.get_builder()
    self.make_changes_file()
    self.make_result_files()
    os.mkdir(self.result_dir)
    self.failUnlessExists(self.result_dir)
    builder.move_result(self.result_dir)
    self.failUnlessExists(self.result_dir)

  def test_move_result_moves_files(self):
    """Test that the move_result places the expected files in the result dir"""
    builder = self.get_builder()
    self.make_changes_file()
    self.make_result_files()
    builder.move_result(self.result_dir)
    self.failUnlessExists(join(self.result_dir, self.changes_filename()))
    for filename in self.get_result_filenames():
      self.failUnlessExists(join(self.result_dir, filename))

  def test_move_result_errors_on_missing_changes_file(self):
    """Test that the move_result errors if the changes file is missing."""
    builder = self.get_builder()
    self.assertRaises(errors.DebianError, builder.move_result, self.result_dir)

  def test_move_result_errors_on_missing_result_file(self):
    """Test that the move_result errors if one of the files is missing."""
    builder = self.get_builder()
    self.make_changes_file()
    self.assertRaises(errors.DebianError, builder.move_result, self.result_dir)


class TestNativeBuilder(BuilderTestCase):
  """Test the native builder."""

  package_version = Version('0.1')

  def get_builder(self, wt=None, version=None, larstiq=False):
    """Returns a native builder."""
    if wt is None:
      (wt, branch) = self._make_branch()
    changelog = self.make_changelog(version=version)
    properties = self.make_properties(changelog, larstiq)
    return DebNativeBuild(properties, wt)

  def test_export_creates_source_dir(self):
    """Test that the source dir is created by export."""
    builder = self.get_builder()
    builder.prepare()
    builder.export()
    self.failUnlessExists(self.source_dir)

  def test_export_has_correct_contents_in_source_dir(self):
    """Test that the exported source dir has the correct contents."""
    wt = self.make_branch_and_tree(self.basedir)
    self.build_tree(['a', 'b'])
    wt.add(['a', 'b'])
    wt.commit('commit one')
    self.build_tree(['c', 'd'])
    wt.add(['c'])
    wt.remove(['b'])
    builder = self.get_builder(wt=wt)
    builder.prepare()
    builder.export()
    self.failUnlessExists(join(self.source_dir, 'a'))
    self.failIfExists(join(self.source_dir, 'b'))
    self.failUnlessExists(join(self.source_dir, 'c'))
    self.failIfExists(join(self.source_dir, 'd'))

  def test_export_removes_builddeb_dir(self):
    """Test that the builddeb dir is removed from the export."""
    wt = self.make_branch_and_tree(self.basedir)
    files = ['a', '.bzr-builddeb/', '.bzr-builddeb/default.conf']
    self.build_tree(files)
    wt.add(files)
    wt.commit('commit one')
    builder = self.get_builder(wt=wt)
    builder.prepare()
    builder.export()
    self.failUnlessExists(join(self.source_dir, 'a'))
    self.failIfExists(join(self.source_dir, '.bzr-builddeb'))

class TestSplitBuilder(BuilderTestCase):
  """Test that the split builder does its thing correctly."""

  def get_builder(self, wt=None, version=None, larstiq=False):
    """Returns a native builder."""
    if wt is None:
      (wt, branch) = self._make_branch()
    changelog = self.make_changelog(version=version)
    properties = self.make_properties(changelog, larstiq)
    return DebSplitBuild(properties, wt)

  def test_export_creates_source_dir(self):
    """Test that the source dir is created by export."""
    builder = self.get_builder()
    builder.prepare()
    builder.export()
    self.failUnlessExists(self.source_dir)

  def test_export_creates_tarball(self):
    """Test that a tarball is created in the build dir"""
    builder = self.get_builder()
    builder.prepare()
    builder.export()
    self.failUnlessExists(join(self.build_dir, self.tarball_name))

  def test_created_tarball_has_correct_contents(self):
    """Test that the tarball has the correct contents.

    The working tree state should be reflected, but the debian/ and
    .bzr-builddeb/ dirs should be removed.
    """
    wt = self.make_branch_and_tree(self.basedir)
    files = ['a', 'b', 'dir/', 'debian/', 'debian/control', '.bzr-builddeb/',
             '.bzr-builddeb/default.conf']
    self.build_tree(files)
    wt.add(files)
    wt.commit('commit one')
    self.build_tree(['c', 'd'])
    wt.add(['c'])
    wt.remove(['b'])
    builder = self.get_builder(wt=wt)
    builder.prepare()
    builder.export()
    tar = tarfile.open(join(self.build_dir, self.tarball_name), "r:gz")
    expected = ['a', 'dir/', 'c']
    extras = []
    basename = self.package_name + '-' + self.upstream_version + '/'
    real_expected = [basename]
    for item in expected:
      real_expected.append(join(basename, item))
    for tarinfo in tar:
      if tarinfo.name in real_expected:
        index = real_expected.index(tarinfo.name)
        del real_expected[index:index+1]
      else:
        extras.append(tarinfo.name)

    if len(real_expected) > 0:
      self.fail("Files not found in %s: %s" % (self.tarball_name,
                                               ", ".join(real_expected)))
    if len(extras) > 0:
      self.fail("Files not expected to be found in %s: %s" % (self.tarball_name,
                                                            ", ".join(extras)))

  def test_source_dir_has_full_contents(self):
    """Test that the source dir has the full contents after an export.
    
    The export of a split build should leave the full branch contents in
    the source dir (including debian/) except for the .bzr-builddeb/ dir.
    """
    wt = self.make_branch_and_tree(self.basedir)
    files = ['a', 'b', 'dir/', 'debian/', 'debian/control', '.bzr-builddeb/',
             '.bzr-builddeb/default.conf']
    self.build_tree(files)
    wt.add(files)
    wt.commit('commit one')
    self.build_tree(['c', 'd'])
    wt.add(['c'])
    wt.remove(['b'])
    builder = self.get_builder(wt=wt)
    builder.prepare()
    builder.export()
    expected = ['a', 'c', 'dir/', 'debian/', 'debian/control']
    for filename in expected:
      self.failUnlessExists(join(self.source_dir, filename))

