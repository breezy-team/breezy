#    __init__.py -- The plugin for bzr
#    Copyright (C) 2005 Jamie Wilkinson <jaq@debian.org> 
#                  2006 James Westby <jw+debian@jameswestby.net>
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
import os
import sys
import shutil
import commands

from bzrlib.branch import Branch
from bzrlib.commands import Command, register_command
from bzrlib.option import Option
from bzrlib.workingtree import WorkingTree
from debian_bundle.changelog import Changelog

from builder import DebBuild, DebMergeBuild
from changes import DebianChanges
from config import DebBuildConfig
from errors import NotInBaseError, ChangedError
from bdlogging import debug, info, set_verbose
from properties import BuildProperties
from util import goto_branch, find_changelog, is_clean

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
  used for the build directory. --result-dir will have problems if you use a
  build command that places the results in a different directory.

  When not using --working-tree and there uncommited changes or unknown files 
  in the working tree the build will not proceed. Use --ignore-changes to 
  override this and build ignoring all changes in the working tree.
  
  The --reuse option will be useful if you are in merge mode, and the upstream
  tarball is very large. It attempts to reuse a build directory from an earlier
  build. It will fail if one doesn't exist, but you can create one by using 
  --export-only. 

  --quick allows you to define a quick-builder in your configuration files, 
  which will be used when this option is passed. It defaults to 'fakeroot 
  debian/rules binary'. It is overriden if --builder is passed. Using this
  and --reuse allows for fast rebuilds. If --working-tree is used as well 
  then changes do not need to be commited. 

  """
  working_tree_opt = Option('working-tree', help="Use the working tree")
  Option.SHORT_OPTIONS['w'] = working_tree_opt
  export_only_opt = Option('export-only', help="Export only, don't build")
  Option.SHORT_OPTIONS['e'] = export_only_opt
  use_existing_opt = Option('use-existing', help="Use an existing build directory")
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

    set_verbose(verbose)

    goto_branch(branch)

    tree, relpath = WorkingTree.open_containing('.')

    if relpath != '':
      raise NotInBaseError()
    
    config = DebBuildConfig()

    if reuse:
      info("Reusing existing build dir")
      dont_purge = True
      use_existing = True

    if not merge:
      merge = config.merge()

    if merge:
      info("Running in merge mode")

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
      debug("Building branch from revision %s", rev_id)
      t = b.repository.revision_tree(rev_id)
      if not ignore_changes and not is_clean(t, tree):
        raise ChangedError
    else:
      info("Building using working tree")
      t = tree

    (changelog, larstiq) = find_changelog(t, merge)

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

class cmd_releasedeb(Command):
  """Build a version of the deb after running dch -r. Also marks the tree to
  remind the user to tag the release."""

  distribution_opt = Option('distribution', help="The distribution that should"
            +" be relased to. Defaults to unstable", type=str)
  takes_args = ['package?']
  takes_options = ['verbose', distribution_opt, builder_opt, dont_purge_opt,
      build_dir_opt, orig_dir_opt, merge_opt, result_opt]

  def run(self, verbose=False, branch=None, distribution='unstable', 
          builder=None, dont_purge=False, build_dir=None, orig_dir=None, 
          merge=False, result=None):

    retcode = 0

    set_verbose(verbose)

    goto_branch(branch)

    config = DebBuildConfig()
    
    if not merge:
      merge = config.merge()

    if merge:
      info("Running in merge mode")

    if result is None:
      result = config.result_dir()
    if result is not None:
      result = os.path.realpath(result)

    if builder is None:
        builder = config.builder()
        if builder is None:
          builder = "dpkg-buildpackage -uc -us -rfakeroot"

    tree, relpath = WorkingTree.open_containing('.')

    if relpath != '':
      raise NotInBaseError()

    b = tree.branch
    rev_id = b.last_revision()
    debug("Building branch from revision %s", rev_id)
    t = b.repository.revision_tree(rev_id)
    if not is_clean(t, tree):
      raise ChangedError

    (changelog, larstiq) = find_changelog(t, merge)

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

    build.prepare()
    build.export()
    wd = os.getcwdu()
    os.chdir(properties.source_dir())
    command = 'dch -r --distribution '+distribution+" \" \""
    debug("Executing %s to ready the package for release", command)
    (status, output) = commands.getstatusoutput(command)
    if status > 0:
      raise DebianError("Couldn't execute dch: %s" % output)
    os.chdir(wd)
    build.build(builder)
    if not dont_purge:
      build.clean()
    if result is not None:
      build.move_result(result)

    build.tag_release()

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
#def test_suite():
#  from unittest import TestSuite, TestLoader
#  import test_buildpackage
#  suite = TestSuite()
#  suite.addTest(TestLoader().loadTestsFromModule(test_buildpackage))
#  return suite

register_command(cmd_builddeb)
register_command(cmd_releasedeb)
#register_command(cmd_recorddeb)
