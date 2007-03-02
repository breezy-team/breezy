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
import shutil
import tarfile

from debian_bundle.changelog import (Changelog, Version)

from bzrlib.errors import NotBranchError
from bzrlib.tests import (TestCaseInTempDir,
                          TestCaseWithTransport,
                          )
from bzrlib.workingtree import WorkingTree

from builder import (remove_dir,
                     remove_bzrbuilddeb_dir,
                     remove_debian_dir,
                     DebBuild,
                     DebNativeBuild,
                     DebSplitBuild,
                     DebMergeBuild,
                     DebMergeExportUpstreamBuild,
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
    return tree

  def build_branch_tree(self, files, *args, **kwargs):
    #divert in to base
    newfiles = []
    for filename in files:
      newfiles.append(join(self.branch_dir, filename))
    self.build_tree(newfiles, *args, **kwargs)

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

  def check_tarball_contents(self, tarball, expected, basedir=None,
                             skip_basedir=False, mode=None):
    """Test that the tarball has certain contents.

    Test that the tarball has exactly expected contents. The basedir
    is checked for and prepended if it is not None. The mode is the mode
    used in tarfile.open defaults to r:gz. If skip_basedir is True and
    basedir is not None then the basedir wont be tested for itself.
    """
    if basedir is None:
      real_expected = expected[:]
    else:
      if skip_basedir:
        real_expected = []
      else:
        real_expected = [basedir]
      for item in expected:
        real_expected.append(join(basedir, item))
    extras = []
    tar = tarfile.open(tarball, 'r:gz')
    try:
      for tarinfo in tar:
        if tarinfo.name in real_expected:
          index = real_expected.index(tarinfo.name)
          del real_expected[index:index+1]
        else:
            extras.append(tarinfo.name)

      if len(real_expected) > 0:
        self.fail("Files not found in %s: %s" % (tarball,
                                                 ", ".join(real_expected)))
      if len(extras) > 0:
        self.fail("Files not expected to be found in %s: %s" % (tarball,
                                                 ", ".join(extras)))
    finally:
      tar.close()

class TestDefaultBuilder(BuilderTestCase):
  """Test the default builder (full source, non-native)"""

  def get_builder(self, version=None, wt=None, larstiq=False):
    """Returns a builder set up for this type."""
    if wt is None:
      wt = self._make_branch()
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
    
    This might not be the desired behaviour, but add a test for it
    either way.
    """
    builder = self.get_builder()
    self.make_orig_tarball()
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
    wt = self._make_branch()
    self.build_branch_tree(['a', 'b'])
    wt.add(['a', 'b'])
    wt.commit('commit one')
    self.build_branch_tree(['c', 'd'])
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
    wt = self._make_branch()
    files = ['a', '.bzr-builddeb/', '.bzr-builddeb/default.conf']
    self.build_branch_tree(files)
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
      wt = self._make_branch()
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
    wt = self._make_branch()
    self.build_branch_tree(['a', 'b'])
    wt.add(['a', 'b'])
    wt.commit('commit one')
    self.build_branch_tree(['c', 'd'])
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
    wt = self._make_branch()
    files = ['a', '.bzr-builddeb/', '.bzr-builddeb/default.conf']
    self.build_branch_tree(files)
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
    if wt is None:
      wt = self._make_branch()
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
    wt = self._make_branch()
    files = ['a', 'b', 'dir/', 'debian/', 'debian/control', '.bzr-builddeb/',
             '.bzr-builddeb/default.conf']
    self.build_branch_tree(files)
    wt.add(files)
    wt.commit('commit one')
    self.build_branch_tree(['c', 'd'])
    wt.add(['c'])
    wt.remove(['b'])
    builder = self.get_builder(wt=wt)
    builder.prepare()
    builder.export()
    tarball = join(self.build_dir, self.tarball_name)
    expected = ['a', 'dir/', 'c']
    basename = self.package_name + '-' + self.upstream_version + '/'
    self.check_tarball_contents(tarball, expected, basedir=basename)

  def test_source_dir_has_full_contents(self):
    """Test that the source dir has the full contents after an export.
    
    The export of a split build should leave the full branch contents in
    the source dir (including debian/) except for the .bzr-builddeb/ dir.
    """
    wt = self._make_branch()
    files = ['a', 'b', 'dir/', 'debian/', 'debian/control', '.bzr-builddeb/',
             '.bzr-builddeb/default.conf']
    self.build_branch_tree(files)
    wt.add(files)
    wt.commit('commit one')
    self.build_branch_tree(['c', 'd'])
    wt.add(['c'])
    wt.remove(['b'])
    builder = self.get_builder(wt=wt)
    builder.prepare()
    builder.export()
    expected = ['a', 'c', 'dir/', 'debian/', 'debian/control']
    for filename in expected:
      self.failUnlessExists(join(self.source_dir, filename))


class TestMergeBuilder(BuilderTestCase):
  """Test the merge builder."""

  def get_builder(self, wt=None, version=None, larstiq=False):
    if wt is None:
      wt = self._make_branch()
    changelog = self.make_changelog(version=version)
    properties = self.make_properties(changelog, larstiq)
    return DebMergeBuild(properties, wt)

  upstream_files = ['a', 'b', 'dir/', 'dir/c']
  debian_files = ['control', 'changelog', 'patches/', 'patches/patch']

  def make_orig_tarball(self):
    """Make the orig tarball with some content for merge builders."""
    os.mkdir(self.orig_dir)
    tarball = join(self.orig_dir, self.tarball_name)
    basedir = self.package_name+'-'+self.upstream_version+'/'
    files = [basedir]
    files = files + [join(basedir, f) for f in self.upstream_files]
    self.build_tree(files)
    tar = tarfile.open(join(self.orig_dir, self.tarball_name), 'w:gz')
    try:
      tar.add(basedir)
    finally:
      tar.close()
    shutil.rmtree(basedir)

  def test__export_upstream_branch(self):
    """Simple sanity check on this private function."""
    builder = self.get_builder()
    self.assertEqual(builder._export_upstream_branch(), False)

  def test_export_creates_source_dir(self):
    """Test that the source dir is created on export."""
    builder = self.get_builder()
    self.make_orig_tarball()
    builder.prepare()
    builder.export()
    self.failUnlessExists(self.source_dir)

  def test_export_extracts_tarball(self):
    """Test that the upstream tarball is extracted in to the source dir."""
    builder = self.get_builder()
    self.make_orig_tarball()
    self.failUnlessExists(join(self.orig_dir, self.tarball_name))
    builder.prepare()
    builder.export()
    for f in self.upstream_files:
      self.failUnlessExists(join(self.source_dir, f))

  def test_export_copies_tarball(self):
    """Test that the tarball is copied in to the build dir."""
    builder = self.get_builder()
    self.make_orig_tarball()
    builder.prepare()
    builder.export()
    self.failUnlessExists(join(self.build_dir, self.tarball_name))

  def test_export_use_existing_doesnt_copy_tarball(self):
    """Test that if use_existing is true it doesn't copy the tarball."""
    builder = self.get_builder()
    self.make_orig_tarball()
    builder.prepare()
    builder.export(use_existing=True)
    self.failIfExists(join(self.build_dir, self.tarball_name))

  def test_export_use_existing_doesnt_extract_tarball(self):
    """Test that the tarball is not extracted if use_existing is True."""
    builder = self.get_builder()
    self.make_orig_tarball()
    builder.prepare()
    builder.export(use_existing=True)
    self.failIfExists(self.source_dir)

  def test_export_has_correct_contents_in_source_dir(self):
    """Test that the exported source dir has the correct contents."""
    wt = self._make_branch()
    basedir = 'debian/'
    files = [basedir]
    files = files + [join(basedir, f) for f in self.debian_files]
    self.build_branch_tree(files)
    wt.add(files)
    wt.commit('commit one')
    self.build_branch_tree(join(basedir, f) for f in ['rules', 'unknown'])
    wt.add(join(basedir, 'rules'))
    wt.remove(join(basedir, 'control'))
    builder = self.get_builder(wt=wt)
    self.make_orig_tarball()
    builder.prepare()
    builder.export()
    expected = ['changelog', 'patches', 'patches/patch', 'rules']
    for f in expected:
      self.failUnlessExists(join(self.source_dir, basedir, f))
    for f in ['control', 'unknown']:
      self.failIfExists(join(self.source_dir, basedir, f))

  def test_export_removes_builddeb_dir(self):
    """Test that the builddeb dir is removed from the export."""
    wt = self._make_branch()
    basedir = 'debian/'
    files = [basedir]
    files = files + [join(basedir, f) for f in ['.bzr-builddeb/',
                             '.bzr-builddeb/default.conf']]
    files = files + [join(basedir, f) for f in self.debian_files]
    self.build_branch_tree(files)
    wt.add(files)
    wt.commit('commit one')
    builder = self.get_builder(wt=wt)
    self.make_orig_tarball()
    builder.prepare()
    builder.export()
    for f in self.debian_files:
      self.failUnlessExists(join(self.source_dir, join(basedir, f)))
    self.failIfExists(join(self.source_dir, '.bzr-builddeb'))

  def test_larstiq(self):
    """Test that LarstiQ format is exported correctly"""
    wt = self._make_branch()
    self.build_branch_tree(self.debian_files)
    wt.add(self.debian_files)
    wt.commit('commit one')
    self.build_branch_tree(['rules', 'unknown'])
    wt.add('rules')
    wt.remove('control')
    builder = self.get_builder(wt=wt, larstiq=True)
    self.make_orig_tarball()
    builder.prepare()
    builder.export()
    expected = ['changelog', 'patches', 'patches/patch', 'rules']
    basedir = 'debian'
    for f in expected:
      self.failUnlessExists(join(self.source_dir, basedir, f))
    for f in self.upstream_files:
      self.failUnlessExists(join(self.source_dir, f))
    for f in ['control', 'unknown']:
      self.failIfExists(join(self.source_dir, f))


class TestMergeExportUpstreamBuilder(BuilderTestCase):

  upstream_branch = property(lambda self: join(self.basedir, 'upstream'))
  upstream_parent = property(lambda self: join(self.basedir, 'parent'))

  def get_builder(self, wt=None, version=None, larstiq=False,
                  export_revision=None, export_prepull=False,
                  stop_on_no_change=False):
    if wt is None:
      wt = self._make_branch()
    changelog = self.make_changelog(version=version)
    properties = self.make_properties(changelog, larstiq)
    return DebMergeExportUpstreamBuild(properties, wt, self.upstream_branch,
                                       export_revision, export_prepull,
                                       stop_on_no_change)

  def make_upstream_branch(self, parent=None):
    """Make the upstream branch that will be exported."""
    wt = self.make_branch_and_tree(self.upstream_branch)
    files = ['a', 'dir/', 'dir/b']
    newfiles = [join(self.upstream_branch, f) for f in files]
    self.build_tree(newfiles)
    wt.add(files)
    wt.commit('commit one', rev_id='rev1')
    self.build_tree([join(self.upstream_branch, 'c')])
    wt.add('c')
    wt.commit('commit two', rev_id='rev2')
    self.build_tree([join(self.upstream_branch, f) for f in
                                          ['added', 'unknown']])
    wt.add('added')
    if parent is not None:
      wt.branch.set_parent(parent)
    self._upstream_tree = wt

  def make_upstream_parent_no_changes(self):
    """Makes the upstream parent by just sprouting it off the upstream."""
    upstream = self._upstream_tree
    upstream.branch.bzrdir.sprout(os.path.abspath(self.upstream_parent))

  def make_upstream_parent_changes(self):
    """Makes the upstream parent and adds a commit."""
    self.make_upstream_parent_no_changes()
    parent_location = os.path.abspath(self.upstream_parent)
    parent = WorkingTree.open_containing(parent_location)[0]
    self.build_tree([join(self.upstream_parent, 'parent'),
                     join(self.upstream_parent, 'parent2')])
    parent.add(['parent'])
    parent.commit('parent commit 1', rev_id='parent1')
    parent.add(['parent2'])
    parent.commit('parent commit 2', rev_id='parent2')

  def test__find_tarball(self):
    """Test that the tarball is located in the build dir."""
    builder = self.get_builder()
    self.assertEqual(builder._find_tarball(), join(self.build_dir,
                     self.tarball_name))

  def test__export_upstream_branch_errors_on_no_branch(self):
    """Test that an error is raised if there is no branch to export."""
    wt = self._make_branch()
    changelog = self.make_changelog()
    properties = self.make_properties(changelog, False)
    builder = DebMergeExportUpstreamBuild(properties, wt, None, None, False,
                                          False)
    builder.prepare()
    self.assertRaises(errors.DebianError, builder._export_upstream_branch)

  def test__export_upstream_branch_errors_on_non_branch(self):
    """Test that the builder wont pull a branch that doesn't exists"""
    wt = self._make_branch()
    changelog = self.make_changelog()
    properties = self.make_properties(changelog, False)
    builder = DebMergeExportUpstreamBuild(properties, wt, 'invalid', None,
                                          False, False)
    builder.prepare()
    self.assertRaises(NotBranchError, builder._export_upstream_branch)

  def test__export_upstream_branch_errors_export_prepull_no_default(self):
    """Test that the export_prepull fails if the default location is not set."""
    builder = self.get_builder(export_prepull=True)
    self.make_upstream_branch()
    builder.prepare()
    self.assertRaises(errors.DebianError, builder._export_upstream_branch)

  def test__export_upstream_branch_errors_invalid_parent(self):
    """Test that the export_prepull fails if the parent doesn't exist."""
    builder = self.get_builder(export_prepull=True)
    self.make_upstream_branch(parent='invalid')
    builder.prepare()
    self.assertRaises(NotBranchError, builder._export_upstream_branch)

  def test__export_upstream_branch_stops_on_trivial(self):
    """Test that StopBuild is raised if there are no changes to pull."""
    builder = self.get_builder(export_prepull=True, stop_on_no_change=True)
    self.make_upstream_branch(parent=os.path.abspath(self.upstream_parent))
    self.make_upstream_parent_no_changes()
    builder.prepare()
    self.assertRaises(errors.StopBuild, builder._export_upstream_branch)

  def test__export_upstream_branch_doesnt_stop_on_trivial(self):
    """Test that the build normally doesn't stop if there is nothing to do."""
    builder = self.get_builder(export_prepull=True)
    self.make_upstream_branch(parent=os.path.abspath(self.upstream_parent))
    self.make_upstream_parent_no_changes()
    builder.prepare()
    builder._export_upstream_branch()

  def test__export_upstream_branch_doesnt_stop_on_changes(self):
    """Test the the build doesn't stop if there is something to do."""
    builder = self.get_builder(export_prepull=True, stop_on_no_change=True)
    self.make_upstream_branch(parent=os.path.abspath(self.upstream_parent))
    self.make_upstream_parent_changes()
    builder.prepare()
    builder._export_upstream_branch()

  def test__export_upstream_branch_has_correct_files(self):
    """Test that the upstream tarball has the correct files."""
    builder = self.get_builder()
    self.make_upstream_branch()
    builder.prepare()
    builder._export_upstream_branch()
    tarball = join(self.build_dir, self.tarball_name)
    self.failUnlessExists(tarball)
    expected = ['a', 'dir/', 'dir/b', 'c']
    basename = self.package_name + '-' + self.upstream_version + '/'
    self.check_tarball_contents(tarball, expected, basedir=basename,
                                skip_basedir=True)

  def test__export_upstream_pull_no_changes_has_correct_files(self):
    """Test that the upstream tarball has the correct files."""
    builder = self.get_builder(export_prepull=True)
    self.make_upstream_branch(parent=os.path.abspath(self.upstream_parent))
    self.make_upstream_parent_no_changes()
    builder.prepare()
    builder._export_upstream_branch()
    tarball = join(self.build_dir, self.tarball_name)
    self.failUnlessExists(tarball)
    expected = ['a', 'dir/', 'dir/b', 'c']
    basename = self.package_name + '-' + self.upstream_version + '/'
    self.check_tarball_contents(tarball, expected, basedir=basename,
                                skip_basedir=True)

  def test__export_upstream_pull_changes_has_correct_files(self):
    """Test that the upstream tarball has the correct files."""
    builder = self.get_builder(export_prepull=True)
    self.make_upstream_branch(parent=os.path.abspath(self.upstream_parent))
    self.make_upstream_parent_changes()
    builder.prepare()
    builder._export_upstream_branch()
    tarball = join(self.build_dir, self.tarball_name)
    self.failUnlessExists(tarball)
    expected = ['a', 'dir/', 'dir/b', 'c', 'parent', 'parent2']
    basename = self.package_name + '-' + self.upstream_version + '/'
    self.check_tarball_contents(tarball, expected, basedir=basename,
                                skip_basedir=True)

  def test__export_upstream_selects_correct_revision(self):
    """Test that if an upstream revision is selected it will be used."""
    builder = self.get_builder(export_prepull=True,
                               export_revision='revid:rev1')
    self.make_upstream_branch(parent=os.path.abspath(self.upstream_parent))
    self.make_upstream_parent_no_changes()
    builder.prepare()
    builder._export_upstream_branch()
    tarball = join(self.build_dir, self.tarball_name)
    self.failUnlessExists(tarball)
    expected = ['a', 'dir/', 'dir/b']
    basename = self.package_name + '-' + self.upstream_version + '/'
    self.check_tarball_contents(tarball, expected, basedir=basename,
                                skip_basedir=True)

  def test__export_upstream_can_select_parent_revision(self):
    """Test that if an upstream parent revision is selected it will be used."""
    builder = self.get_builder(export_prepull=True,
                               export_revision='revid:parent1')
    self.make_upstream_branch(parent=os.path.abspath(self.upstream_parent))
    self.make_upstream_parent_changes()
    builder.prepare()
    builder._export_upstream_branch()
    tarball = join(self.build_dir, self.tarball_name)
    self.failUnlessExists(tarball)
    expected = ['a', 'dir/', 'dir/b', 'c', 'parent']
    basename = self.package_name + '-' + self.upstream_version + '/'
    self.check_tarball_contents(tarball, expected, basedir=basename,
                                skip_basedir=True)

  def test__export_upstream_returns_true(self):
    """Sanity check that the function returns true."""
    builder = self.get_builder()
    self.make_upstream_branch()
    builder.prepare()
    self.assertEqual(builder._export_upstream_branch(), True)

