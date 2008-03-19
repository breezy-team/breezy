#    __init__.py -- The plugin for bzr
#    Copyright (C) 2005 Jamie Wilkinson <jaq@debian.org> 
#                  2006, 2007 James Westby <jw+debian@jameswestby.net>
#                  2007 Reinhard Tartler <siretart@tauware.de>
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

"""bzr-builddeb - manage packages in a Bazaar branch."""

import os
import subprocess

from bzrlib.commands import Command, register_command
from bzrlib.errors import (BzrCommandError,
                           NoWorkingTree,
                           NotBranchError,
                           FileExists,
                           )
from bzrlib.option import Option
from bzrlib.trace import info, warning
from bzrlib.transport import get_transport
from bzrlib import urlutils
from bzrlib.workingtree import WorkingTree

from bzrlib.plugins.builddeb.builder import (DebBuild,
                     DebMergeBuild,
                     DebNativeBuild,
                     DebSplitBuild,
                     DebMergeExportUpstreamBuild,
                     DebExportUpstreamBuild,
                     )
from bzrlib.plugins.builddeb.config import DebBuildConfig
from bzrlib.plugins.builddeb.errors import (StopBuild,
                    )
from bzrlib.plugins.builddeb.hooks import run_hook
from bzrlib.plugins.builddeb.properties import BuildProperties
from bzrlib.plugins.builddeb.util import goto_branch, find_changelog, tarball_name
from bzrlib.plugins.builddeb.version import version_info


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

builddeb_dir = '.bzr-builddeb'
default_conf = os.path.join(builddeb_dir, 'default.conf')
global_conf = os.path.expanduser('~/.bazaar/builddeb.conf')
local_conf = os.path.join(builddeb_dir, 'local.conf')

default_build_dir = '../build-area'
default_orig_dir = '../tarballs'


class cmd_builddeb(Command):
  """Builds a Debian package from a branch.

  If BRANCH is specified it is assumed that the branch you wish to build is
  located there. If it is not specified then the current directory is used.

  By default the working tree is used to build. If you wish to build the
  last committed revision use --revision -1. You can specify any other
  revision using the --revision option.

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

  The --reuse option will be useful if you are in merge mode, and the upstream
  tarball is very large. It attempts to reuse a build directory from an earlier
  build. It will fail if one doesn't exist, but you can create one by using 
  --export-only. 

  --quick allows you to define a quick-builder in your configuration files, 
  which will be used when this option is passed. It defaults to 'fakeroot 
  debian/rules binary'. It is overriden if --builder is passed. Using this
  and --reuse allows for fast rebuilds. 

  --source allows you to build a source package without having to
  specify a builder to do so with --builder. It uses the source-builder
  option from your configuration files, and defaults to 'dpkg-buildpackage 
  -rfakeroot -uc -us -S'. It is overriden if either --builder or --quick are
  used.

  """
  working_tree_opt = Option('working-tree', help="This option has no effect",
                            short_name='w')
  export_only_opt = Option('export-only', help="Export only, don't build",
                           short_name='e')
  use_existing_opt = Option('use-existing',
                            help="Use an existing build directory")
  ignore_changes_opt = Option('ignore-changes',
      help="This option has no effect")
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
  no_user_conf = Option('no-user-config', help="Stop builddeb from reading the user's "
                        +"config file. Used mainly for tests")
  takes_args = ['branch?']
  aliases = ['bd']
  takes_options = [working_tree_opt, export_only_opt,
      dont_purge_opt, use_existing_opt, result_opt, builder_opt, merge_opt,
      build_dir_opt, orig_dir_opt, ignore_changes_opt, ignore_unknowns_opt,
      quick_opt, reuse_opt, native_opt, split_opt, export_upstream_opt,
      export_upstream_revision_opt, source_opt, 'revision', no_user_conf]

  def run(self, branch=None, verbose=False, working_tree=False,
          export_only=False, dont_purge=False, use_existing=False,
          result=None, builder=None, merge=False, build_dir=None,
          orig_dir=None, ignore_changes=False, ignore_unknowns=False,
          quick=False, reuse=False, native=False, split=False,
          export_upstream=None, export_upstream_revision=None,
          source=False, revision=None, no_user_config=False):

    goto_branch(branch)

    tree, relpath = WorkingTree.open_containing('.')
    
    if no_user_config:
        config_files = [(local_conf, True), (default_conf, False)]
    else:
        config_files = [(local_conf, True), (global_conf, True),
                             (default_conf, False)]
    config = DebBuildConfig(config_files)

    if reuse:
      info("Reusing existing build dir")
      dont_purge = True
      use_existing = True

    if not merge:
      merge = config.merge

    if merge:
      info("Running in merge mode")
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

    if revision is None:
      info("Building using working tree")
      t = tree
      working_tree = True
    else:
      if len(revision) != 1:
        raise BzrCommandError('bzr builddeb --revision takes exactly one '
                              'revision specifier.')
      b = tree.branch
      rev = revision[0].in_history(b)
      info("Building branch from revision %s", rev.rev_id)
      t = b.repository.revision_tree(rev.rev_id)
      working_tree = False

    (changelog, larstiq) = find_changelog(t, merge)

    config.set_version(changelog.version)

    if export_upstream is None:
      export_upstream = config.export_upstream

    if export_upstream_revision is None:
      export_upstream_revision = config.export_upstream_revision

    if build_dir is None:
      build_dir = config.build_dir
      if build_dir is None:
        build_dir = default_build_dir

    if orig_dir is None:
      orig_dir = config.orig_dir
      if orig_dir is None:
        orig_dir = default_orig_dir
    
    properties = BuildProperties(changelog,build_dir,orig_dir,larstiq)

    if merge:
      if export_upstream is None:
        build = DebMergeBuild(properties, t, _is_working_tree=working_tree)
      else:
        prepull_upstream = config.prepull_upstream
        stop_on_no_change = config.prepull_upstream_stop
        build = DebMergeExportUpstreamBuild(properties, t, export_upstream,
                                            export_upstream_revision,
                                            prepull_upstream,
                                            stop_on_no_change,
                                            _is_working_tree=working_tree)
    elif native:
      build = DebNativeBuild(properties, t, _is_working_tree=working_tree)
    elif split:
      build = DebSplitBuild(properties, t, _is_working_tree=working_tree)
    else:
      if export_upstream is None:
        build = DebBuild(properties, t, _is_working_tree=working_tree)
      else:
        prepull_upstream = config.prepull_upstream
        stop_on_no_change = config.prepull_upstream_stop
        build = DebExportUpstreamBuild(properties, t, export_upstream,
                                       export_upstream_revision,
                                       prepull_upstream,
                                       stop_on_no_change,
                                       _is_working_tree=working_tree)

    build.prepare(use_existing)

    run_hook('pre-export', config)

    try:
      build.export(use_existing)
    except StopBuild, e:
      warning('Stopping the build: %s.', e.reason)
      return

    if not export_only:
      run_hook('pre-build', config, wd=properties.source_dir())
      build.build(builder)
      run_hook('post-build', config, wd=properties.source_dir())
      if not dont_purge:
        build.clean()
      if result is not None:
        build.move_result(result)


register_command(cmd_builddeb)


class cmd_merge_upstream(Command):
  """Merges a new upstream version into the current branch.

  Takes a new upstream version and merges it in to your branch, so that your
  packaging changes are applied to the new version.

  You must supply the source to import from, and the version number of the
  new release. The source can be a .tar.gz, .tar, .tar.bz2, .tgz or .zip
  archive, or a directory. The source may also be a remote file.

  If there is no debian changelog in the branch to retrieve the package
  name from then you must pass the --package option. If this version
  will change the name of the source package then you can use this option
  to set the new name.
  """
  takes_args = ['path']
  aliases = ['mu']

  package_opt = Option('package', help="The name of the source package.",
                       type=str)
  version_opt = Option('version', help="The version number of the new "
                       "upstream release. (Required).", type=str)
  takes_options = [package_opt, version_opt]

  def run(self, path, version=None, package=None):

    from bzrlib.errors import (NoSuchTag,
                               TagAlreadyExists,
                               )
    from bzrlib.plugins.builddeb.errors import MissingChangelogError
    from bzrlib.plugins.builddeb.merge_upstream import merge_upstream
    from bzrlib.plugins.builddeb.repack_tarball import repack_tarball

    if version is None:
      raise BzrCommandError("You must supply the --version argument.")

    tree, relpath = WorkingTree.open_containing('.')

    config = DebBuildConfig([(local_conf, True), (global_conf, True),
                             (default_conf, False)])

    if config.merge:
      raise BzrCommandError("Merge upstream in merge mode is not yet "
                            "supported")
    if config.native:
      raise BzrCommandError("Merge upstream in native mode is not yet "
                            "supported")
    if config.export_upstream:
      raise BzrCommandError("Export upstream mode is not yet "
                            "supported")
    if config.split:
      raise BzrCommandError("Split mode is not yet supported")

    if package is None:
      try:
        package = find_changelog(tree, False)[0].package
      except MissingChangelogError:
        raise BzrCommandError("There is no changelog to rertrieve the package "
                              "information from, please use the --package "
                              "option to give the name of the package")

    orig_dir = config.orig_dir or '../tarballs'
    orig_dir = os.path.join(tree.basedir, orig_dir)

    dest_name = tarball_name(package, version)
    try:
      repack_tarball(path, dest_name, target_dir=orig_dir)
    except FileExists:
      raise BzrCommandError("The target file %s already exists, and is either "
                            "different to the new upstream tarball, or they "
                            "are of different formats. Either delete the target "
                            "file, or use it as the argument to import.")
    filename = os.path.join(orig_dir, dest_name)

    try:
      merge_upstream(tree, filename, version)
    # TODO: tidy all of this up, and be more precise in what is wrong and
    #       what can be done.
    except NoSuchTag, e:
      raise BzrCommandError("The tag of the last upstream import can not be "
                            "found. You should tag the revision that matches "
                            "the last upstream version. Expected to find %s." % \
                            e.tag_name)
    except TagAlreadyExists:
      raise BzrCommandError("It appears as though this merge has already "
                            "been performed, as there is already a tag "
                            "for this upstream version. If that is not the "
                            "case then delete that tag and try again.")
    info("The new upstream version has been imported. You should now update "
         "the changelog (try dch -v %s), and then commit. Note that debcommit "
         "will not do what you want in this case." % str(version))


register_command(cmd_merge_upstream)


class cmd_import_dsc(Command):
  """Import a series of source packages.

  Provide a number of source packages (.dsc files), and they will
  be imported to create a branch with history that reflects those
  packages. You must provide the --to option with the name of the
  branch that will be created, and the --initial option to indicate
  this is an initial import.

  If there are packages that are available on snapshot.debian.net
  then you can use the --snapshot option to supplement the packages
  you provide with those available on that service. Pass the name
  of the source package as on snapshot.debian.net as this option,
  i.e. to import all versions of apt

    import-dsc --initial --snapshot apt

  If you use the --snapshot option then you don't have to provide
  any source packages on the command line, and if you omit the
  --to option then the name of the package as passed to --snapshot
  will be used as the branch name.

  In addition to the above choices you can specify a file
  (possibly remote) that contains a list of source packages (.dsc
  files) to import. Each line is taken to be a URI or path to
  import. The sources specified in the file are used in addition
  to those specified by other methods.

  If you have an existing branch containing packaging and you want to
  import a .dsc from an upload done from outside the version control
  system you can use this command. In this case you can only specify
  one file on the command line, or use a file containing only a single
  filename, and do not use the --initial option.
  """

  takes_args = ['files*']
  
  to_opt = Option('to', help="The branch to import to.", type=str)
  snapshot_opt = Option('snapshot', help="Retrieve source packages from "
                        "snapshot.debian.net.", type=str)
  filename_opt = Option('file', help="File containing URIs of source "
                        "packages to import.", type=str, argname="filename",
                        short_name='F')
  initial_opt = Option('initial',
        help="Perform an initial import to create a new branch.")

  takes_options = [to_opt, snapshot_opt, filename_opt, initial_opt]

  def run(self, files_list, to=None, snapshot=None, filename=None,
          initial=False):
    from bzrlib.plugins.builddeb.import_dsc import DscImporter, SnapshotImporter
    if files_list is None:
      files_list = []
    if filename is not None:
      if isinstance(filename, unicode):
        filename = filename.encode('utf-8')
      base_dir, path = urlutils.split(filename)
      sources_file = get_transport(base_dir).get(path)
      for line in sources_file:
        line.strip()
        files_list.append(line)
    if snapshot is None:
      if not initial:
        if len(files_list) != 1:
          raise BzrCommandError("You must give the location of exactly one "
                                "source package.")
      else:
        if len(files_list) < 1:
          raise BzrCommandError("You must give the location of at least one "
                                "source package to install, or use the "
                                "--file or --snapshot options.")
        if to is None:
          raise BzrCommandError("You must specify the name of the "
                                "destination branch using the --to option.")
      importer = DscImporter(files_list)
    else:
      if not initial:
        raise BzrCommandError("You cannot use the --snapshot option without "
            "the --initial option.")
      if to is None:
        to = snapshot
      importer = SnapshotImporter(snapshot, other_sources=files_list)
    if initial:
      orig_target = os.path.join(to, '../tarballs')
      importer.import_dsc(to, orig_target=orig_target)
    else :
      inc_to = '.'
      if to is not None:
        inc_to = to
      _local_conf = os.path.join(inc_to, local_conf)
      _global_conf = os.path.join(inc_to, global_conf)
      _default_conf = os.path.join(inc_to, default_conf)
      config = DebBuildConfig([(_local_conf, True), (_global_conf, True),
                             (_default_conf, False)])
      orig_target = config.orig_dir
      if orig_target is None:
        orig_target = os.path.join(inc_to, '../tarballs')
      importer.incremental_import_dsc(inc_to, orig_target=orig_target)


register_command(cmd_import_dsc)


class cmd_bd_do(Command):
  """Run a command in an exported package, copying the result back.
  
  For a merge mode package the full source is not available, making some
  operations difficult. This command allows you to run any command in an
  exported source directory, copying the resulting debian/ directory back
  to your branch if the command is successful.

  For instance:

    bzr bd-do

  will run a shell in the unpacked source. Any changes you make in the
  ``debian/`` directory (and only those made in that directory) will be copied
  back to the branch. If you exit with a non-zero exit code (e.g. "exit 1"),
  then the changes will not be copied back.

  You can also specify single commands to be run, e.g.

    bzr bd-do "dpatch-edit-patch 01-fix-build"

  Note that only the first argument is used as the command, and so the above
  example had to be quoted.
  """

  takes_args = ['command?']

  def run(self, command=None):

    config = DebBuildConfig([(local_conf, True), (global_conf, True),
                             (default_conf, False)])

    if not config.merge:
      raise BzrCommandError("This command only works for merge mode "
                            "packages. See /usr/share/doc/bzr-builddeb"
                            "/user_manual/merge.html for more information.")

    give_instruction = False
    if command is None:
      try:
        command = os.environ['SHELL']
      except KeyError:
        command = "/bin/sh"
      give_instruction = True
    t = WorkingTree.open_containing('.')[0]
    (changelog, larstiq) = find_changelog(t, True)
    build_dir = config.build_dir
    if build_dir is None:
      build_dir = default_build_dir
    orig_dir = config.orig_dir
    if orig_dir is None:
      orig_dir = default_orig_dir
    properties = BuildProperties(changelog, build_dir, orig_dir, larstiq)
    export_upstream = config.export_upstream
    export_upstream_revision = config.export_upstream_revision

    if export_upstream is None:
      build = DebMergeBuild(properties, t, _is_working_tree=True)
    else:
      prepull_upstream = config.prepull_upstream
      stop_on_no_change = config.prepull_upstream_stop
      build = DebMergeExportUpstreamBuild(properties, t, export_upstream,
                                          export_upstream_revision,
                                          prepull_upstream,
                                          stop_on_no_change,
                                          _is_working_tree=True)

    build.prepare()
    try:
      build.export()
    except StopBuild, e:
      warning('Stopping the build: %s.', e.reason)
    info('Running "%s" in the exported directory.' % (command))
    if give_instruction:
      info('If you want to cancel your changes then exit with a non-zero '
           'exit code, e.g. run "exit 1".')
    proc = subprocess.Popen(command, shell=True,
                            cwd=properties.source_dir())
    proc.wait()
    if proc.returncode != 0:
      raise BzrCommandError('Not updating the working tree as the command '
                            'failed.')
    info("Copying debian/ back")
    if larstiq:
      destination = '.'
    else:
      destination = 'debian/'
    source_debian = os.path.join(properties.source_dir(), 'debian')
    for filename in os.listdir(source_debian):
      proc = subprocess.Popen('cp -apf "%s" "%s"' % (
           os.path.join(source_debian, filename), destination),
           shell=True)
      proc.wait()
      if proc.returncode != 0:
        raise BzrCommandError('Copying back debian/ failed')
    build.clean()
    info('If any files were added or removed you should run "bzr add" or '
         '"bzr rm" as appropriate.')


register_command(cmd_bd_do)


def test_suite():
    from unittest import TestSuite
    from bzrlib.plugins.builddeb import tests
    result = TestSuite()
    result.addTest(tests.test_suite())
    return result


class cmd_test_builddeb(Command):
    """Run the builddeb test suite"""

    hidden = True

    def run(self):
        from bzrlib.tests import selftest
        result = selftest(test_suite_factory=test_suite)
        return not result


register_command(cmd_test_builddeb)


if __name__ == '__main__':
  print ("This is a Bazaar plugin. Copy this directory to ~/.bazaar/plugins "
          "to use it.\n")
  import unittest
  runner = unittest.TextTestRunner()
  runner.run(test_suite())
else:
  import sys
  sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# vim: ts=2 sts=2 sw=2
