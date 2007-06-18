#    __init__.py -- The plugin for bzr
#    Copyright (C) 2005 Jamie Wilkinson <jaq@debian.org> 
#                  2006, 2007 James Westby <jw+debian@jameswestby.net>
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

from bzrlib.commands import Command, register_command
from bzrlib.trace import info, warning
from bzrlib.option import Option
from bzrlib.workingtree import WorkingTree
from bzrlib.bzrdir import BzrDir
from bzrlib.errors import NoSuchFile, BzrCommandError, NotBranchError
import bzrlib.transport

from builder import (DebBuild,
                     DebMergeBuild,
                     DebNativeBuild,
                     DebSplitBuild,
                     DebMergeExportUpstreamBuild,
                     )
from config import DebBuildConfig
from errors import (ChangedError,
                    StopBuild,
                    )
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
split_opt = Option('split',
    help="Automatically create an .orig.tar.gz from a full source branch")
export_upstream_opt = Option('export-upstream',
    help="Create the .orig.tar.gz from a bzr branch before building",
    type=unicode)
export_upstream_revision_opt = Option('export-upstream-revision',
    help="Select the upstream revision that will be exported",
    type=str)


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

  --source allows you to build a source package without having to
  specify a builder to do so with --builder. It uses the source-builder
  option from your configuration files, and defaults to 'dpkg-buildpackage 
  -rfakeroot -uc -us -S'. It is overriden if either --builder or --quick are
  used.

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
  source_opt = Option('source', help="Build a source package, uses "
                      +"source-builder, which defaults to \"dpkg-buildpackage "
                      +"-rfakeroot -uc -us -S\"", short_name='S')
  takes_args = ['branch?']
  aliases = ['bd']
  takes_options = [working_tree_opt, export_only_opt,
      dont_purge_opt, use_existing_opt, result_opt, builder_opt, merge_opt,
      build_dir_opt, orig_dir_opt, ignore_changes_opt, ignore_unknowns_opt,
      quick_opt, reuse_opt, native_opt, split_opt, export_upstream_opt,
      export_upstream_revision_opt, source_opt]

  def run(self, branch=None, verbose=False, working_tree=False,
          export_only=False, dont_purge=False, use_existing=False,
          result=None, builder=None, merge=False, build_dir=None,
          orig_dir=None, ignore_changes=False, ignore_unknowns=False,
          quick=False, reuse=False, native=False, split=False,
          export_upstream=None, export_upstream_revision=None,
          source=False):

    retcode = 0

    goto_branch(branch)

    tree, relpath = WorkingTree.open_containing('.')

    config = DebBuildConfig()

    if reuse:
      info("Reusing existing build dir")
      dont_purge = True
      use_existing = True

    if not merge:
      merge = config.merge

    if merge:
      info("Running in merge mode")
      if export_upstream is None:
        export_upstream = config.export_upstream
    else:
      if not native:
        native = config.native

      if native:
        info("Running in native mode")
      else:
        if not split:
          split = config.split

        if split:
          info("Running in split mode")

    if not ignore_unknowns:
      ignore_unknowns = config.ignore_unknowns

    if ignore_unknowns:
      info("Not stopping the build if there are any unknown files. If you "
          +"have just created a file, make sure you have added it.")

    if result is None:
      result = config.result_dir
    if result is not None:
      result = os.path.realpath(result)

    if builder is None:
      if quick:
        builder = config.quick_builder
        if builder is None:
          builder = "fakeroot debian/rules binary"
      else:
        if source:
          builder = config.source_builder
          if builder is None:
            builder = "dpkg-buildpackage -rfakeroot -uc -us -S"
        else:
          builder = config.builder
          if builder is None:
            builder = "dpkg-buildpackage -uc -us -rfakeroot"

    if not working_tree:
      b = tree.branch
      rev_id = b.last_revision()
      info("Building branch from revision %s", rev_id)
      t = b.repository.revision_tree(rev_id)
      if not ignore_changes and not is_clean(t, tree, ignore_unknowns):
        raise ChangedError
    else:
      info("Building using working tree")
      t = tree

    (changelog, larstiq) = find_changelog(t, merge)

    if build_dir is None:
      build_dir = config.build_dir
      if build_dir is None:
        build_dir = '../build-area'

    if orig_dir is None:
      orig_dir = config.orig_dir
      if orig_dir is None:
        orig_dir = '../tarballs'
    
    properties = BuildProperties(changelog,build_dir,orig_dir,larstiq)

    if merge:
      if export_upstream is None:
        build = DebMergeBuild(properties, t)
      else:
        prepull_upstream = config.prepull_upstream
        stop_on_no_change = config.prepull_upstream_stop
        build = DebMergeExportUpstreamBuild(properties, t, export_upstream,
                                            export_upstream_revision,
                                            prepull_upstream,
                                            stop_on_no_change)
    elif native:
      build = DebNativeBuild(properties, t)
    elif split:
      build = DebSplitBuild(properties, t)
    else:
      build = DebBuild(properties, t)

    build.prepare(use_existing)

    try:
      build.export(use_existing)
    except StopBuild, e:
      warning('Stopping the build: %s.', e.reason)
      return retcode

    if not export_only:
      build.build(builder)
      if not dont_purge:
        build.clean()
      if result is not None:
        build.move_result(result)

    return retcode

register_command(cmd_builddeb)

class cmd_merge_upstream(Command):
  """ merges a new upstream version into the current branch

  you need to specify the revision of the last upstream import at the
  moment

  """
#  config = DebBuildConfig()
  takes_args = ['filename']
  takes_options = ['revision']
  aliases = ['mu']

  def run(self, revision=None, location=None, filename=None):

    from bzrlib.plugins.bzrtools.upstream_import import do_import, import_tar
    from bzrlib.builtins import _merge_helper
    from bzrlib.commit import Commit
    from bzrlib.repository import RootCommitBuilder

    tree, relpath = WorkingTree.open_containing('.')
    if tree.changes_from(tree.basis_tree()).has_changed():
      raise BzrCommandError("Working tree has uncommitted changes.")

    from_branch = tree.branch
    revno, rev_id = revision[0].in_branch(from_branch)
    tree.revert([], tree.branch.repository.revision_tree(rev_id))
    tar_input = open(filename, 'rb')
    import_tar(tree, tar_input)

    builder = RootCommitBuilder(tree.branch.repository,
                                [rev_id],
                                tree.branch.get_config())

    # look at commit.py:295
    builder.commit('import upstream from file %s' % file)
    return
  
    to_transport = bzrlib.transport.get_transport('/tmp/bzrfoo')
    dir_to = from_branch.bzrdir.clone_on_transport(to_transport,rev_id)
    to_tree = dir_to.open_workingtree()
    to_tree.revert([])
    do_import(file, '/tmp/bzrfoo')
    to_tree.commit('import upstream from file %s' % file)
    other_revision = ['.', None]
    _merge_helper(other_revision, [None, None], this_dir='/tmp/bzrfoo')

register_command(cmd_merge_upstream)

def test_suite():
    from unittest import TestSuite
    import tests
    result = TestSuite()
    result.addTest(tests.test_suite())
    return result

if __name__ == '__main__':
  print ("This is a Bazaar plugin. Copy this directory to ~/.bazaar/plugins "
          "to use it.\n")
  import unittest
  runner = unittest.TextTestRunner()
  runner.run(test_suite())
else:
  import sys
  sys.path.append(os.path.dirname(os.path.abspath(__file__)))

