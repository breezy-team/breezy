#    builder.py -- Classes for building packages
#    Copyright (C) 2006 James Westby <jw+debian@jameswestby.net>
#    
#    This file is part of bzr-builddeb.
#
#    bzr-builldeb is free software; you can redistribute it and/or modify
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

import glob
import shutil
import tempfile
import os

from bzrlib.export import export

from changes import DebianChanges
from errors import (DebianError,
                    NoSourceDirError,
                    BuildFailedError)
from bdlogging import info, debug
from util import recursive_copy


def remove_bzrbuilddeb_dir(dir):
  """Removes the .bzr-builddeb dir from the specfied directory."""

  #Is this what we want??
  bzr_builddeb_dir = os.path.join(dir, ".bzr-builddeb")
  if os.path.exists(bzr_builddeb_dir) and os.path.isdir(bzr_builddeb_dir):
    shutil.rmtree(bzr_builddeb_dir)


class DebBuild(object):
  """The object that does the building work."""

  def __init__(self, properties, tree):
    self._properties = properties
    self._tree = tree

  def prepare(self, keep_source_dir=False):
    build_dir = self._properties.build_dir()
    info("Preparing the build area: %s", build_dir);
    if not os.path.exists(build_dir):
      os.makedirs(build_dir)
    source_dir = self._properties.source_dir()
    if os.path.exists(source_dir):
      if not keep_source_dir:
        info("Purging the build dir: %s", source_dir)
        shutil.rmtree(source_dir)
      else:
        info("Not purging build dir as requested: %s", build_dir)
    else:
      if keep_source_dir:
        raise NoSourceDirError;

  def export(self, reuse_existing=False):
    source_dir = self._properties.source_dir()
    info("Exporting to %s", source_dir)
    export(self._tree,source_dir,None,None)
    remove_bzrbuilddeb_dir(source_dir)

  def build(self, builder):
    wd = os.getcwdu()
    source_dir = self._properties.source_dir()
    info("Building the package in %s, using %s", source_dir, builder)
    os.chdir(source_dir)
    result = os.system(builder)
    os.chdir(wd)
    if result > 0:
      raise BuildFailedError;

  def clean(self):
    source_dir = self._properties.source_dir()
    info("Cleaning build dir: %s", source_dir)
    shutil.rmtree(source_dir)

  def move_result(self, result):
    info("Placing result in %s", result)
    package = self._properties.package()
    version = self._properties.full_version()
    changes = DebianChanges(package, version, self._properties.build_dir())
    files = changes.files()
    if not os.path.exists(result):
      os.makedirs(result)
    debug("Moving %s to %s", changes.filename(), result)
    shutil.move(changes.filename(), result)
    debug("Moving all files given in %s", changes.filename())
    for file in files:
      debug("Moving %s to %s", file['name'], result)
      shutil.move(os.path.join(self._properties.build_dir(), file['name']), 
                  result)

  def tag_release(self):
    #TODO decide what command should be able to remove a tag notice
    info("If you are happy with the results and upload use tagdeb to tag this"
        +" release. If you do not release it...")


class DebMergeBuild(DebBuild):
  """A subclass of DebBuild that uses the merge method."""

  def export(self, use_existing=False):
    package = self._properties.package()
    upstream = self._properties.upstream_version()
    build_dir = self._properties.build_dir()
    tarballdir = self._properties.tarball_dir()
    tarball = os.path.join(tarballdir,package+"_"+upstream+".orig.tar.gz")
    source_dir = self._properties.source_dir()
    info("Exporting to %s in merge mode", source_dir)
    if not use_existing:
      info("Looking for %s to use as upstream source", tarball)
      if not os.path.exists(tarballdir):
        raise DebianError('Could not find dir with upstream tarballs: '
            +tarballdir)
      if not os.path.exists(tarball):
        raise DebianError('Could not find upstrean tarball at '+tarball)

      debug("Extracting %s to %s", tarball, source_dir)
      tempdir = tempfile.mkdtemp(prefix='builddeb-', dir=build_dir)
      os.system('tar xzf '+tarball+' -C '+tempdir)
      files = glob.glob(tempdir+'/*')
      os.makedirs(source_dir)
      for file in files:
        shutil.move(file, source_dir)
      shutil.rmtree(tempdir)
      shutil.copy(tarball, build_dir)
    else:
      info("Reusing existing build dir as requested")

    info("Exporting debian/ part to %s", source_dir)
    basetempdir = tempfile.mkdtemp(prefix='builddeb-', dir=build_dir)
    tempdir = os.path.join(basetempdir,"export")
    if self._properties.larstiq():
      os.makedirs(tempdir)
      export_dir = os.path.join(tempdir,'debian')
    else:
      export_dir = tempdir
    export(self._tree,export_dir,None,None)
    recursive_copy(tempdir, source_dir)
    shutil.rmtree(basetempdir)
    remove_bzrbuilddeb_dir(os.path.join(source_dir, "debian"))



