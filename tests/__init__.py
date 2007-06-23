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

import changes
import config
import shutil
import tarfile
import zipfile

from copy import deepcopy
import doctest
import os
from unittest import TestSuite

from bzrlib.tests import TestUtil, adapt_modules

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
            'test_util',
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

    return suite

