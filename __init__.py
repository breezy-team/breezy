#!/usr/bin/python2.4

import os
import sys
import shutil
import re
import commands
import tempfile
import glob

from bzrlib.commands import Command, register_command
from bzrlib.option import Option
from bzrlib.errors import (NoSuchFile, NotBranchError, BzrNewError)
from bzrlib.branch import Branch
from bzrlib.workingtree import WorkingTree
from bzrlib.export import export
from bzrlib.config import ConfigObj

class DebianChanges(object):
  """Abstraction of the .changes file. Use it to find out what files were built
  """

  def __init__(self, package, version, dir):
    status, arch = commands.getstatusoutput('dpkg-architecture -qDEB_BUILD_ARCH')
    if status > 0:
      raise DebianError("Could not find the build architecture")
    changes = str(package)+"_"+str(version)+"_"+str(arch)+".changes"
    if dir is not None:
      changes = dir+"/"+changes
    if not os.path.exists(changes):
      raise DebianError("Could not find "+package)
    f = open(changes)
    p = re.compile('^ [a-z0-9]+ [0-9]+ [a-z]+ [a-z]+ (.*)$')
    files = []
    for line in f:
      m = p.match(line)
      if m is not None:
        file = m.group(1)
        if dir is not None:
          file = dir+"/"+file
        files.append(file)
    self._files = files
    self._filename = changes

  def files(self):
    return self._files

  def filename(self):
    return self._filename

class DebianChangelog(object):
  """Represents a debian/changelog file. You can ask it several things about
     the file.
  """

  def __init__(self, file=None):
    if file is None:
      f = open("debian/changelog", 'r')
      contents = f.read()
      close(f)
      self._file = contents
    else:
      self._file = file
    p = re.compile('([a-z0-9][-a-z0-9.+]+) \(([-0-9a-z.:]+)\) [-a-zA-Z]+; urgency=[a-z]+')
    m = p.search(self._file)
    if m is not None:
      self._package = m.group(1)
      self._full_version = m.group(2)
 
    if self._full_version is None:
      raise DebianError("Could not parse debian/changelog")

    p = re.compile('(.+)-([^-]+)')
    m = p.match(self._full_version)
    if m is not None:
      self._upstream_version = m.group(1)
      self._debian_version = m.group(2)
    else:
      self._upstream_version = self._full_version
      self._debian_version = None


  def full_version(self):
    return self._full_version

  def debian_version(self):
    return self._debian_version

  def upstream_version(self):
    return self._upstream_version

  def package(self):
    return self._package

class BuildProperties(object):

  def __init__(self, changelog, build_dir, tarball_dir, larstiq):
    self._changelog = changelog
    self._build_dir = build_dir
    self._tarball_dir = tarball_dir
    self._larstiq = larstiq
  
  def package(self):
    return self._changelog.package()

  def upstream_version(self):
    return self._changelog.upstream_version()

  def debian_version(self):
    return self._changelog.debian_version()

  def full_version(self):
    return self._changelog.full_version()

  def build_dir(self):
    return self._build_dir

  def source_dir(self):
    return self.build_dir()+"/"+self.package()+"-"+self.full_version()

  def tarball_dir(self):
    return self._tarball_dir

  def larstiq(self):
    return self._larstiq

class DebBuild(object):

  def __init__(self, properties, tree):
    self._properties = properties
    self._tree = tree

  def prepare(self):
    build_dir = self._properties.build_dir()
    if not os.path.exists(build_dir):
      os.makedirs(build_dir)
    source_dir = self._properties.source_dir()
    if os.path.exists(source_dir):
      shutil.rmtree(source_dir)

  def export(self):
    source_dir = self._properties.source_dir()
    export(self._tree,source_dir,None,None)

  def build(self, builder):
    wd = os.getcwdu()
    os.chdir(self._properties.source_dir())
    os.system(builder)
    os.chdir(wd)

  def clean(self):
    shutil.rmtree(self._properties.source_dir())

  def move_result(self, result):
    package = self._properties.package()
    version = self._properties.full_version()
    changes = DebianChanges(package, version, self._properties.build_dir())
    files = changes.files()
    if not os.path.exists(result):
      os.makedirs(result)
    shutil.move(changes.filename(), result)
    for file in files:
      shutil.move(file, result)

class DebMergeBuild(DebBuild):

  def export(self):
    package = self._properties.package()
    upstream = self._properties.upstream_version()
    build_dir = self._properties.build_dir()
    tarballdir = self._properties.tarball_dir()
    tarball = tarballdir+"/"+package+"_"+upstream+".orig.tar.gz"
    if not os.path.exists(tarballdir):
      raise DebianError('Could not find dir with upstream tarballs: '+tarballdir)
    if not os.path.exists(tarball):
      raise DebianError('Could not find upstrean tarball at '+tarball)

    tempdir = tempfile.mkdtemp(prefix='builddeb-', dir=build_dir)

    os.system('tar xzf '+tarball+' -C '+tempdir)

    source_dir = self._properties.source_dir()

    if self._properties.larstiq():
      export_dir = source_dir+'/debian/'
      os.makedirs(source_dir)
    else:
      export_dir = source_dir

    export(self._tree,export_dir,None,None)

    files = glob.glob(tempdir+'/*/*')

    for file in files:
      shutil.move(file, source_dir)

    shutil.rmtree(tempdir)


class DebianError(BzrNewError):
  """A Debian packaging error occured: %(message)s"""

  def __init__(self, message):
    BzrNewError.__init__(self)
    self.message = message

class BuildDebConfig(ConfigObj):

  def __init__(self):
    file = os.path.expanduser('~/.bazaar/builddeb.conf')
    super(ConfigObj, self).__init__(file)

  def _get_opt(self, key):
    try:
      return self.get_value('builddeb', key)
    except KeyError:
      return None

  def builder(self):
    return self._get_opt('builder')


class cmd_builddeb(Command):
  """Build the package
  """
  working_tree_opt = Option('working-tree', help="Use the wokring tree")
  Option.SHORT_OPTIONS['w'] = working_tree_opt
  export_only_opt = Option('export-only', help="Export only, don't build")
  Option.SHORT_OPTIONS['e'] = export_only_opt
  dont_purge_opt = Option('dont-purge', help="Don't purge the build directory after building")
  result_opt = Option('result', help="Directory in which to place the resulting package files", type=str)
  builder_opt = Option('builder', help="Command to build the package", type=str)
  merge_opt = Option('merge', help='Merge the debian part of the source in to the upstream tarball')
#  Option.SHORT_OPTIONS['m'] = merge_opt
  takes_args = ['branch?', 'version?']
  aliases = ['bd']
  takes_options = ['verbose',
           working_tree_opt, export_only_opt, dont_purge_opt, result_opt, builder_opt, merge_opt]

  def run(self, branch=None, version=None, verbose=False, working_tree=False, export_only=False, dont_purge=False, result=None, builder=None, merge=False):
    retcode = 0

    if branch is None:
      tree = WorkingTree.open_containing('.')[0]
    else:
      tree = WorkingTree.open_containing(branch)[0]

    if result is not None:
      result = os.path.realpath(result)

    config = BuildDebConfig()

    if builder is None:
      builder = config.builder()
      if builder is None:
        builder = "dpkg-buildpackage -uc -us -rfakeroot"

    if not working_tree:
      b = tree.branch
      rev_id = b.last_revision()
      t = b.repository.revision_tree(rev_id)
    else:
      t = tree
    changelog_file = 'debian/changelog'
    larstiq = False
    if not t.has_filename(changelog_file):
      if merge:
        #Assume LartstiQ's layout (.bzr in debian/)
        changelog_file = 'changelog'
        larstiq = True
        if not t.has_filename(changelog_file):
          raise DebianError("Could not open changelog")
      else:
        raise DebianError("Could not open debian/changelog")

    changelog_id = t.inventory.path2id(changelog_file)
    contents = t.get_file_text(changelog_id)
    changelog = DebianChangelog(contents)
    if branch is None:
      build_dir = '../build-area'
      tarball_dir = '../tarballs'
    else:
      build_dir = 'build-area'
      tarball_dir = 'tarballs'
    properties = BuildProperties(changelog,build_dir,tarball_dir,larstiq)
    if merge:
      build = DebMergeBuild(properties, t)
    else:
      build = DebBuild(properties, t)

    build.prepare()
    build.export()

    if not export_only:
      build.build(builder)
      if not dont_purge:
        build.clean()
      if result is not None:
        build.move_result(result)


    return retcode

#class cmd_recorddeb(Command):
#  """Record the package
#  """
#  dry_run_opt = Option('dry-run', help="don't do anything")
#  Option.SHORT_OPTIONS['n'] = dry_run_opt
#  takes_args = ['package', 'version?']
#  takes_options = ['verbose',
#           dry_run_opt]
#
#  def run(self, package, version=None, verbose=False):
#    retcode = 0
#
#    return retcode
#
def test_suite():
  from unittest import TestSuite, TestLoader
  import test_buildpackage
  suite = TestSuite()
  suite.addTest(TestLoader().loadTestsFromModule(test_buildpackage))
  return suite

register_command(cmd_builddeb)
#register_command(cmd_recorddeb)
