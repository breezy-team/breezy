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
import commands

from bzrlib.commands import Command, register_command
from bzrlib.option import Option
from bzrlib.workingtree import WorkingTree

from builder import DebBuild, DebMergeBuild, DebNativeBuild
from config import DebBuildConfig
from errors import NotInBaseError, ChangedError, DebianError
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
native_opt = Option('native',
    help="Build a native package")


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
  working_tree_opt = Option('working-tree', help="Use the working tree",
                            short_name='w')
  export_only_opt = Option('export-only', help="Export only, don't build",
                           short_name='e')
  use_existing_opt = Option('use-existing',
                            help="Use an existing build directory")
  ignore_changes_opt = Option('ignore-changes',
      help="Ignore any changes that are in the working tree when building the"
         +" branch. You may also want --working to use these uncommited "
         + "changes")
  ignore_unknowns_opt = Option('ignore-unknowns',
      help="Ignore any unknown files, but still fail if there are any changes"
         +", the default is to fail if there are unknowns as well.")
  quick_opt = Option('quick', help="Quickly build the package, uses "
                     +"quick-builder, which defaults to \"fakeroot "
                     +"debian/rules binary\"")
  reuse_opt = Option('reuse', help="Try to avoid expoting too much on each "
                     +"build. Only works in merge mode; it saves unpacking "
                     +"the upstream tarball each time. Implies --dont-purge "
                     +"and --use-existing")
  takes_args = ['branch?']
  aliases = ['bd']
  takes_options = ['verbose', working_tree_opt, export_only_opt,
      dont_purge_opt, use_existing_opt, result_opt, builder_opt, merge_opt,
      build_dir_opt, orig_dir_opt, ignore_changes_opt, ignore_unknowns_opt,
      quick_opt, reuse_opt, native_opt]

  def run(self, branch=None, verbose=False, working_tree=False,
          export_only=False, dont_purge=False, use_existing=False,
          result=None, builder=None, merge=False, build_dir=None,
          orig_dir=None, ignore_changes=False, ignore_unknowns=False,
          quick=False, reuse=False, native=False):
    retcode = 0

    set_verbose(verbose)

    goto_branch(branch)

    tree, relpath = WorkingTree.open_containing('.')
    
    config = DebBuildConfig()

    if reuse:
      info("Reusing existing build dir")
      dont_purge = True
      use_existing = True

    if not merge:
      merge = config.merge()

    if merge:
      info("Running in merge mode")

    if not native:
      native = config.native()

    if native:
      info("Running in native mode")

    if not ignore_unknowns:
      ignore_unknowns = config.ignore_unknowns()

    if ignore_unknowns:
      info("Not stopping the build if there are any unknown files. If you "
          +"have just created a file, make sure you have added it.")

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
      if not ignore_changes and not is_clean(t, tree, ignore_unknowns):
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
    elif native:
      build = DebNativeBuild(properties, t)
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

register_command(cmd_builddeb)
