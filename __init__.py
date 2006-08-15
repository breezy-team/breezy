#!/usr/bin/python2.4

import os
import sys
import shutil
import re
import commands
import tempfile
import glob

from bzrlib.atomicfile import AtomicFile
from bzrlib.branch import Branch
from bzrlib.commands import Command, register_command
from bzrlib.config import ConfigObj
from bzrlib.errors import (NoSuchFile, NotBranchError, BzrNewError)
from bzrlib.export import export
from bzrlib.ignores import parse_ignore_file
from bzrlib.option import Option
from bzrlib.trace import mutter
from bzrlib.workingtree import WorkingTree
from debian_bundle import deb822

class DebianChanges(deb822.changes):
  """Abstraction of the .changes file. Use it to find out what files were 
  built."""

  def __init__(self, package, version, dir):
    status, arch = commands.getstatusoutput(
        'dpkg-architecture -qDEB_BUILD_ARCH')
    if status > 0:
      raise DebianError("Could not find the build architecture")
    changes = str(package)+"_"+str(version)+"_"+str(arch)+".changes"
    if dir is not None:
      changes = os.path.join(dir,changes)
    if not os.path.exists(changes):
      raise DebianError("Could not find "+package)
    fp = open(changes)
    super(DebianChanges, self).__init__(fp)
    self._filename = changes
    
  def files(self):
    return self['Files']

  def filename(self):
    return self._filename

class DebianChangelog(object):
  """Represents a debian/changelog file. You can ask it several things about
  the file."""

  def __init__(self, file=None):
    self._full_version = None
    self._package = None
    if file is None:
      f = open(os.path.join("debian","changelog"), 'r')
      contents = f.read()
      close(f)
      self._file = contents
    else:
      self._file = file
    p = re.compile('([a-z0-9][-a-z0-9.+]+) \(([-0-9a-z.:]+)\) [-a-zA-Z]+;'
        +' urgency=[a-z]+')
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


def recursive_copy(fromdir, todir):
  """Copy the contents of fromdir to todir. Like shutil.copytree, but the 
  destination directory must already exist with this method, rather than 
  not exists for shutil."""

  for entry in os.listdir(fromdir):
    path = os.path.join(fromdir, entry)
    if os.path.isdir(path):
      tosubdir = os.path.join(todir, entry)
      if not os.path.exists(tosubdir):
        os.mkdir(tosubdir)
      recursive_copy(path, tosubdir)
    else:
      shutil.copy(path, todir)

class BuildProperties(object):
  """Properties of this specific build"""

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
    return os.path.join(self.build_dir(), 
                        self.package()+"-"+self.full_version())

  def tarball_dir(self):
    return self._tarball_dir

  def larstiq(self):
    return self._larstiq

class DebBuild(object):
  """The object that does the building work."""

  def __init__(self, properties, tree):
    self._properties = properties
    self._tree = tree

  def prepare(self, keep_source_dir=False):
    build_dir = self._properties.build_dir()
    if not os.path.exists(build_dir):
      os.makedirs(build_dir)
    source_dir = self._properties.source_dir()
    if os.path.exists(source_dir):
      if not keep_source_dir:
        shutil.rmtree(source_dir)
    else:
      if keep_source_dir:
        raise NoSourceDirError;

  def export(self, reuse_existing=False):
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
      shutil.move(os.path.join(self._properties.build_dir(), file['name']), 
                  result)

class DebMergeBuild(DebBuild):
  """A subclass of DebBuild that uses the merge method."""

  def export(self, use_existing):
    package = self._properties.package()
    upstream = self._properties.upstream_version()
    build_dir = self._properties.build_dir()
    tarballdir = self._properties.tarball_dir()
    tarball = os.path.join(tarballdir,package+"_"+upstream+".orig.tar.gz")
    source_dir = self._properties.source_dir()

    if not use_existing:
      if not os.path.exists(tarballdir):
        raise DebianError('Could not find dir with upstream tarballs: '
            +tarballdir)
      if not os.path.exists(tarball):
        raise DebianError('Could not find upstrean tarball at '+tarball)

      tempdir = tempfile.mkdtemp(prefix='builddeb-', dir=build_dir)
      os.system('tar xzf '+tarball+' -C '+tempdir)
      files = glob.glob(tempdir+'/*/*')
      os.makedirs(source_dir)
      for file in files:
        shutil.move(file, source_dir)
      shutil.rmtree(tempdir)

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


class DebianError(BzrNewError):
  """A Debian packaging error occured: %(message)s"""

  def __init__(self, message):
    BzrNewError.__init__(self)
    self.message = message

class ChangedError(DebianError):
  """There are modified files in the working tree. Either commit the 
  changes, use --working to build the working tree, or --ignore-changes
  to override this and build the branch without the changes in the working 
  tree. Use bzr status to see the changes"""

  def __init__(self):
    DebianError.__init__(self, None)

class NoSourceDirError(DebianError):
  """There is no existing source directory to use. Use --export-only or 
  --dont-purge to get one that can be used"""

  def __init__(self):
    DebianError.__init__(self, None)

def add_ignore(file):
  """Adds file to .bzrignore if it exists and not already in the file."""
  if os.path.exists(file):
    tree, relpath = WorkingTree.open_containing(u'.')
    ifn = tree.abspath('.bzrignore')
    ignored = set()
    if os.path.exists(ifn):
      f = open(ifn, 'rt')
      ignored = parse_ignore_file(f)
      f.close()
    
    if file not in ignored:
      ignored.add(file)

    f = AtomicFile(ifn, 'wt')
    try:
      for ign in ignored:
        f.write(ign.encode('utf-8')+"\n")
      f.commit()
    finally:
      f.close()

    inv = tree.inventory
    if inv.path2id('.bzrignore'):
      mutter('.bzrignore is already versioned')
    else:
      mutter('need to make new .bzrignore file versioned')
      tree.add(['.bzrignore'])


class BuildDebConfig(object):
  """Holds the configuration settings for builddeb. These are taken from
  a hierarchy of config files. .bzr-builddeb/local.conf then 
  ~/.bazaar/builddeb.conf, finally .bzr-builddeb/default.conf. The value is 
  taken from the first file in which it is specified."""

  def __init__(self):
    globalfile = os.path.expanduser('~/.bazaar/builddeb.conf')
    localfile = ('.bzr-builddeb/local.conf')
    defaultfile = ('.bzr-builddeb/default.conf')
    self._config_files = [ConfigObj(localfile), ConfigObj(globalfile), ConfigObj(defaultfile)]
    add_ignore(localfile)

  def _get_opt(self, config, key):
    """Returns the value for key from config, of None if it is not defined in 
    the file"""
    try:
      return config.get_value('BUILDDEB', key)
    except KeyError:
      return None

  def _get_best_opt(self, key):
    """Returns the value for key from the first file in which it is defined,
    or None if none of the files define it."""

    for file in self._config_files:
      value = self._get_opt(file, key)
      if value is not None:
        return value
    return None

  def _get_bool(self, config, key):
    try:
      return True, config.get_bool('BUILDDEB', key)
    except KeyError:
      return False, False

  def _get_best_bool(self, key, default=False):
    for file in self._config_files:
      (found, value) = self._get_bool(file, key)
      if found:
        return value
    return default

  def build_dir(self):
    return self._get_best_opt('build-dir')

  def orig_dir(self):
    return self._get_best_opt('orig-dir')

  def builder(self):
    return self._get_best_opt('builder')

  def result_dir(self):
    return self._get_best_opt('result-dir')

  def merge(self):
    return self._get_best_bool('merge', False)

  def quick_builder(self):
    return self._get_best_opt('quick-builder')

def is_clean(oldtree, newtree):
  """Return True if there are no uncommited changes or unknown files. 
  I don't like this, but I can't see a better way to do it, and dont
  want to add the dependency on bzrtools for an equivalent method, (even
  if I knew how to access it)."""

  changes = newtree.changes_from(oldtree)
  if changes.has_changed() or len(list(newtree.unknowns())) > 0:
    return False
  return True

class cmd_builddeb(Command):
  """Builds a Debian package from a branch.

  If BRANCH is specified it is assumed that the branch you wish to build is
  located there. If it is not specified then the current directory is used.

  By default the commited modifications of the branch are used to build
  the package. If you wish to use the woking tree to build the package use
  --working-tree.

  If you only wish to export the package, and not build it (especially useful
  for merge mode), use --export-only.

  To leave the build directory when the build is completed use --dont-purge.

  Specify the command to use when building using the --builder option,

  You can also specify directories to use for different things. --build-dir
  is the directory to build the packages beneath, defaults to ../build-area.
  --orig-dir specifies the directory that contains the .orig.tar.gz files 
  for use in merge mode, defaults to ../tarballs. --result-dir specifies where
  the resulting package files should be placed, defaults to whatever is 
  used for the build directory.

  When not using --working-tree and there uncommited changes or unknown files 
  in the working tree the build will not proceed. Use --ignore-changes to 
  override this and build ignoring all changes in the working tree.
  
  """
  working_tree_opt = Option('working-tree', help="Use the working tree")
  Option.SHORT_OPTIONS['w'] = working_tree_opt
  export_only_opt = Option('export-only', help="Export only, don't build")
  Option.SHORT_OPTIONS['e'] = export_only_opt
  use_existing_opt = Option('use-existing', help="Use an existing build directory")
  dont_purge_opt = Option('dont-purge', 
      help="Don't purge the build directory after building")
  result_opt = Option('result', 
      help="Directory in which to place the resulting package files", type=str)
  builder_opt = Option('builder', 
      help="Command to build the package", type=str)
  merge_opt = Option('merge', 
      help='Merge the debian part of the source in to the upstream tarball')
  build_dir_opt = Option('build-dir', 
      help="The dir to use for building", type=str)
  orig_dir_opt = Option('orig-dir', 
      help="Directory containing the .orig.tar.gz files. For use when only"
         +"debian/ is versioned", type=str)
  ignore_changes_opt = Option('ignore-changes',
      help="Ignore any changes that are in the working tree when building the"
         +" branch. You may also want --working to use these uncommited "
         + "changes")
  quick_opt = Option('quick', help="Quickly build the package, uses quick-builder, which defaults to \"fakeroot debian/rules binary\"")
  reuse_opt = Option('reuse', help="Try to avoid expoting too much on each build. Only works in merge mode; it saves unpacking the upstream tarball each time. Implies --dont-purge and --use-existing")
  takes_args = ['branch?']
  aliases = ['bd']
  takes_options = ['verbose', working_tree_opt, export_only_opt, 
      dont_purge_opt, use_existing_opt, result_opt, builder_opt, merge_opt, 
      build_dir_opt, orig_dir_opt, ignore_changes_opt, quick_opt, reuse_opt]

  def run(self, branch=None, verbose=False, working_tree=False, 
          export_only=False, dont_purge=False, use_existing=False, 
          result=None, builder=None, merge=False, build_dir=None, 
          orig_dir=None, ignore_changes=False, quick=False, reuse=False):
    retcode = 0

    if branch is not None:
      os.chdir(branch)

    tree = WorkingTree.open_containing('.')[0]
    
    config = BuildDebConfig()

    if reuse:
      dont_purge = True
      use_existing = True

    if not merge:
      merge = config.merge()

    if result is None:
      result = config.result_dir()
    if result is not None:
      result = os.path.realpath(result)

    if builder is None:
      if quick:
        builder = config.quick_builder()
        if builder is None:
          builder = "fakeroot debian/rules binary"
      else:
        builder = config.builder()
        if builder is None:
          builder = "dpkg-buildpackage -uc -us -rfakeroot"

    if not working_tree:
      b = tree.branch
      rev_id = b.last_revision()
      t = b.repository.revision_tree(rev_id)
      if not ignore_changes and not is_clean(t, tree):
        raise ChangedError
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
          raise DebianError("Could not open debian/changelog or changelog")
      else:
        raise DebianError("Could not open debian/changelog")

    changelog_id = t.inventory.path2id(changelog_file)
    contents = t.get_file_text(changelog_id)
    changelog = DebianChangelog(contents)
    if build_dir is None:
      build_dir = config.build_dir()
      if build_dir is None:
        build_dir = '../build-area'

    if orig_dir is None:
      orig_dir = config.orig_dir()
      if orig_dir is None:
        orig_dir = '../tarballs'
    
    properties = BuildProperties(changelog,build_dir,orig_dir,larstiq)

    if merge:
      build = DebMergeBuild(properties, t)
    else:
      build = DebBuild(properties, t)

    build.prepare(use_existing)
    build.export(use_existing)

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
