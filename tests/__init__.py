#    __init__.py -- Testsuite for builddeb
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

import shutil
import tarfile
import zipfile

from copy import deepcopy
import doctest
import os
from unittest import TestSuite

from debian_bundle.changelog import Version, Changelog

from bzrlib.tests import TestUtil, adapt_modules, TestCaseWithTransport

from bzrlib.plugins.builddeb.tests import blackbox


def make_new_upstream_dir(dir):
  def _make_upstream_dir():
    os.rename('package-0.2', dir)
  return _make_upstream_dir

def make_new_upstream_tarball(tarball):
  def _make_upstream_tarball():
    tar = tarfile.open(tarball, 'w:gz')
    try:
      tar.add('package-0.2')
    finally:
      tar.close()
    shutil.rmtree('package-0.2')
  return _make_upstream_tarball

def make_new_upstream_tarball_bz2(tarball):
  def _make_upstream_tarball():
    tar = tarfile.open(tarball, 'w:bz2')
    try:
      tar.add('package-0.2')
    finally:
      tar.close()
    shutil.rmtree('package-0.2')
  return _make_upstream_tarball

def make_new_upstream_tarball_zip(tarball):
  def _make_upstream_tarball():
    zip = zipfile.ZipFile(tarball, 'w')
    try:
      zip.writestr('package-0.2/', '')
      for (dirpath, dirnames, names) in os.walk('package-0.2'):
        for dir in dirnames:
          zip.writestr(os.path.join(dirpath, dir, ''), '')
        for name in names:
          zip.write(os.path.join(dirpath, name))
    finally:
      zip.close()
    shutil.rmtree('package-0.2')
  return _make_upstream_tarball

def make_new_upstream_tarball_bare(tarball):
  def _make_upstream_tarball():
    tar = tarfile.open(tarball, 'w')
    try:
      tar.add('package-0.2')
    finally:
      tar.close()
    shutil.rmtree('package-0.2')
  return _make_upstream_tarball

tarball_functions = [('dir', make_new_upstream_dir, '../package-0.2'),
                     ('.tar.gz', make_new_upstream_tarball,
                      '../package-0.2.tar.gz'),
                     ('.tar.bz2', make_new_upstream_tarball_bz2,
                      '../package-0.2.tar.bz2'),
                     ('.zip', make_new_upstream_tarball_zip,
                      '../package-0.2.zip'),
                     ('.tar', make_new_upstream_tarball_bare,
                      '../package-0.2.tar'),
                     ]


class MergeUpstreamAdaptor(object):

  def adapt(self, test):
    result = TestSuite()
    for (name, function, source) in tarball_functions:
      new_test = deepcopy(test)
      new_test.build_tarball = function(source)
      new_test.upstream_tarball = source
      def make_new_id():
        new_id = '%s(%s)' % (test.id(), name)
        return lambda: new_id
      new_test.id = make_new_id()
      result.addTest(new_test)
    return result


class RepackTarballAdaptor(object):

  def adapt(self, test):
    result = TestSuite()
    for (name, function, source) in tarball_functions:
      # XXX: Zip files are horrible, but work out how to repack them.
      if name == '.zip':
        continue
      new_test = deepcopy(test)
      source = os.path.basename(source)
      new_test.build_tarball = function(source)
      new_test.old_tarball = source
      def make_new_id():
        new_id = '%s(%s)' % (test.id(), name)
        return lambda: new_id
      new_test.id = make_new_id()
      result.addTest(new_test)
    return result


def test_suite():
    loader = TestUtil.TestLoader()
    suite = TestSuite()
    testmod_names = [
            'test_builder',
            'test_config',
            'test_hooks',
            'test_import_dsc',
            'test_repack_tarball_extra',
            'test_util',
            'test_version',
            ]
    suite.addTest(loader.loadTestsFromModuleNames(["%s.%s" % (__name__, i)
                                            for i in testmod_names]))

    doctest_mod_names = [
             'changes',
             'config'
             ]
    for mod in doctest_mod_names:
      suite.addTest(doctest.DocTestSuite(mod))

    adapt_modules(['%s.test_merge_upstream' % __name__],
                  MergeUpstreamAdaptor(), loader, suite)
    adapt_modules(['%s.test_repack_tarball' % __name__],
                  RepackTarballAdaptor(), loader, suite)

    packages_to_test = [
             blackbox,
             ]

    for package in packages_to_test:
      suite.addTest(package.test_suite())

    return suite

class BuilddebTestCase(TestCaseWithTransport):

  package_name = 'test'
  package_version = Version('0.1-1')
  upstream_version = property(lambda self: \
                              self.package_version.upstream_version)

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
    changelog.write_to_open_file(f)
    f.close()

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
        real_expected.append(os.path.join(basedir, item))
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

# vim: ts=2 sts=2 sw=2

