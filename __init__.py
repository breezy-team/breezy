#    __init__.py -- The plugin for bzr
#    Copyright (C) 2005 Jamie Wilkinson <jaq@debian.org> 
#                  2006, 2007 James Westby <jw+debian@jameswestby.net>
#                  2007 Reinhard Tartler <siretart@tauware.de>
#                  2008 Canonical Ltd.
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
import shutil
import subprocess
import tempfile
import urlparse

from debian_bundle.changelog import Version

from bzrlib import bzrdir
from bzrlib.branch import Branch
from bzrlib.commands import Command, register_command
from bzrlib.config import ConfigObj
from bzrlib.errors import (BzrCommandError,
                           NoWorkingTree,
                           NotBranchError,
                           FileExists,
                           AlreadyBranchError,
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
from bzrlib.plugins.builddeb.import_dsc import (
        DistributionBranch,
        DistributionBranchSet,
        DscCache,
        DscComp,
        )
from bzrlib.plugins.builddeb.properties import BuildProperties
from bzrlib.plugins.builddeb.util import (find_changelog,
        lookup_distribution,
        tarball_name,
        )
from bzrlib.plugins.builddeb.version import version_info


dont_purge_opt = Option('dont-purge',
    help="Don't purge the build directory after building")
result_opt = Option('result-dir',
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
no_user_conf_opt = Option('no-user-config',
    help="Stop builddeb from reading the user's config file. Used mainly "
    "for tests")

builddeb_dir = '.bzr-builddeb'
default_conf = os.path.join(builddeb_dir, 'default.conf')
global_conf = os.path.expanduser('~/.bazaar/builddeb.conf')
local_conf = os.path.join(builddeb_dir, 'local.conf')

default_build_dir = '../build-area'
default_orig_dir = '..'
default_result_dir = '..'


def debuild_config(tree, working_tree, no_user_config):
  """Obtain the Debuild configuration object.

  :param tree: A Tree object, can be a WorkingTree or RevisionTree.
  :param working_tree: Whether the tree is a working tree.
  :param no_user_config: Whether to skip the user configuration
  """
  config_files = []
  user_config = None
  if (working_tree and 
      tree.has_filename(local_conf) and tree.path2id(local_conf) is None):
    config_files.append((tree.get_file_byname(local_conf), True))
  if not no_user_config:
    config_files.append((global_conf, True))
    user_config = global_conf
  if tree.path2id(default_conf):
    config_files.append((tree.get_file(tree.path2id(default_conf)), False))
  config = DebBuildConfig(config_files)
  config.set_user_config(user_config)
  return config


class cmd_builddeb(Command):
  """Builds a Debian package from a branch.

  If BRANCH is specified it is assumed that the branch you wish to build is
  located there. If it is not specified then the current directory is used.

  By default the if a working tree is found it is used to build and otherwise
  the last committed revision was used. To force building the last committed 
  revision use --revision -1. You can specify any other revision using the 
  --revision option.

  If you only wish to export the package, and not build it (especially useful
  for merge mode), use --export-only.

  To leave the build directory when the build is completed use --dont-purge.

  Specify the command to use when building using the --builder option,

  You can also specify directories to use for different things. --build-dir
  is the directory to build the packages beneath, which defaults to
  '../build-area'. '--orig-dir' specifies the directory that contains the
  .orig.tar.gz files , which defaults to '..'. '--result-dir' specifies where
  the resulting package files should be placed, which defaults to '..'.
  --result-dir will have problems if you use a build command that places
  the results in a different directory.

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
  result_compat_opt = Option('result', help="Present only for compatibility "
          "with bzr-builddeb <= 2.0. Use --result-dir instead.")
  takes_args = ['branch?']
  aliases = ['bd']
  takes_options = [working_tree_opt, export_only_opt,
      dont_purge_opt, use_existing_opt, result_opt, builder_opt, merge_opt,
      build_dir_opt, orig_dir_opt, ignore_changes_opt, ignore_unknowns_opt,
      quick_opt, reuse_opt, native_opt, split_opt, export_upstream_opt,
      export_upstream_revision_opt, source_opt, 'revision',
      no_user_conf_opt, result_compat_opt]

  def run(self, branch=None, verbose=False, working_tree=False,
          export_only=False, dont_purge=False, use_existing=False,
          result_dir=None, builder=None, merge=False, build_dir=None,
          orig_dir=None, ignore_changes=False, ignore_unknowns=False,
          quick=False, reuse=False, native=False, split=False,
          export_upstream=None, export_upstream_revision=None,
          source=False, revision=None, no_user_config=False, result=None):

    if branch is None:
      branch = "."

    # Find out if we were passed a local or remote branch
    is_local = urlparse.urlsplit(branch)[0] in ('', 'file')
    if is_local:
      os.chdir(branch)

    try:
      tree, _ = WorkingTree.open_containing(branch)
      branch = tree.branch
    except NoWorkingTree:
      tree = None
      branch, _ = Branch.open_containing(branch)

    if revision is None and tree is not None:
      info("Building using working tree")
      working_tree = True
    else:
      if revision is None:
        revid = branch.last_revision()
      elif len(revision) == 1:
        revid = revision[0].in_history(branch).rev_id
      else:
        raise BzrCommandError('bzr builddeb --revision takes exactly one '
                              'revision specifier.')
      info("Building branch from revision %s", revid)
      tree = branch.repository.revision_tree(revid)
      working_tree = False

    tree.lock_read()
    try:
      config = debuild_config(tree, working_tree, no_user_config)

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

      (changelog, larstiq) = find_changelog(tree, merge)

      config.set_version(changelog.version)

      if export_upstream is None:
        export_upstream = config.export_upstream

      if export_upstream_revision is None:
        export_upstream_revision = config.export_upstream_revision

      if result_dir is None:
        result_dir = result

      if result_dir is None:
        if is_local:
          result_dir = config.result_dir
        else:
          result_dir = config.user_result_dir
      if result_dir is not None:
        result_dir = os.path.realpath(result_dir)
      
      if build_dir is None:
        if is_local:
          build_dir = config.build_dir or default_build_dir
        else:
          build_dir = config.user_build_dir or 'build-area'

      if orig_dir is None:
        if is_local:
          orig_dir = config.orig_dir or default_orig_dir
        else:
          orig_dir = config.user_orig_dir or 'build-area'
      
      properties = BuildProperties(changelog, build_dir, orig_dir, larstiq)

      if merge:
        if export_upstream is None:
          build = DebMergeBuild(properties, tree, _is_working_tree=working_tree)
        else:
          prepull_upstream = config.prepull_upstream
          stop_on_no_change = config.prepull_upstream_stop
          build = DebMergeExportUpstreamBuild(properties, tree, export_upstream,
                                              export_upstream_revision,
                                              prepull_upstream,
                                              stop_on_no_change,
                                              _is_working_tree=working_tree)
      elif native:
        build = DebNativeBuild(properties, tree, _is_working_tree=working_tree)
      elif split:
        build = DebSplitBuild(properties, tree, _is_working_tree=working_tree)
      else:
        if export_upstream is None:
          build = DebBuild(properties, tree, _is_working_tree=working_tree)
        else:
          prepull_upstream = config.prepull_upstream
          stop_on_no_change = config.prepull_upstream_stop
          build = DebExportUpstreamBuild(properties, tree, export_upstream,
                                         export_upstream_revision,
                                         prepull_upstream,
                                         stop_on_no_change,
                                         _is_working_tree=working_tree)

      build.prepare(use_existing)

      run_hook(tree, 'pre-export', config)

      try:
        build.export(use_existing)
      except StopBuild, e:
        warning('Stopping the build: %s.', e.reason)
        return

      if not export_only:
        run_hook(tree, 'pre-build', config, wd=properties.source_dir())
        build.build(builder)
        run_hook(tree, 'post-build', config, wd=properties.source_dir())
        if not dont_purge:
          build.clean()
        arch = None
        if source:
          arch = "source"
        if result_dir is not None:
          build.move_result(result_dir, arch=arch)
        else:
          build.move_result(default_result_dir, allow_missing=True, arch=arch)
    finally:
      tree.unlock()


register_command(cmd_builddeb)


class cmd_merge_upstream(Command):
    """Merges a new upstream version into the current branch.

    Takes a new upstream version and merges it in to your branch, so that your
    packaging changes are applied to the new version.

    You must supply the source to import from, and the version number of the
    new release. The source can be a .tar.gz, .tar, .tar.bz2, .tgz or .zip
    archive, or a directory. The source may also be a remote file.

    You must supply the version number of the new upstream release
    using --version, and the target distribution using --distribution.
    The target distribtution is the distribution that you aim to upload to,
    one of "debian" or "ubuntu". You can also specify the target used in
    the changelog, e.g. "unstable", and it will be resolved automatically.

    If there is no debian changelog in the branch to retrieve the package
    name from then you must pass the --package option. If this version
    will change the name of the source package then you can use this option
    to set the new name.
    """
    takes_args = ['tarball']
    aliases = ['mu']

    package_opt = Option('package', help="The name of the source package.",
                         type=str)
    version_opt = Option('version', help="The version number of this release.",
                         type=str)
    distribution_opt = Option('distribution', help="The distribution that "
            "this release is targetted at", type=str)

    takes_options = [package_opt, no_user_conf_opt, version_opt,
            distribution_opt]

    def run(self, tarball, version=None, distribution=None, package=None,
            no_user_config=None):
        from bzrlib.plugins.builddeb.errors import MissingChangelogError
        from bzrlib.plugins.builddeb.repack_tarball import repack_tarball
        if version is None:
            raise BzrCommandError("You must specify the version number using "
                    "--version.")
        else:
            version = Version(version)
        if distribution is None:
            raise BzrCommandError("You must specify the target distribution "
                    "using --distribution.")
        tree, _ = WorkingTree.open_containing('.')
        tree.lock_write()
        try:
            # Check for uncommitted changes.
            if tree.changes_from(tree.basis_tree()).has_changed():
                raise BzrCommandError("There are uncommitted changes in the "
                        "working tree. You must commit before using this "
                        "command")
            config = debuild_config(tree, tree, no_user_config)
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

            try:
                changelog = find_changelog(tree, False)[0]
                current_version = changelog.version
                if package is None:
                    package = changelog.package
            except MissingChangelogError:
                current_version = None

            if package is None:
                raise BzrCommandError("You did not specify --package, and there "
                        "is no changelog from which to determine the package "
                        "name, which is needed to know the name to give the "
                        ".orig.tar.gz. Please specify --package.")

            orig_dir = config.orig_dir or default_orig_dir
            orig_dir = os.path.join(tree.basedir, orig_dir)
            version_str = version.upstream_version
            dest_name = tarball_name(package, version_str)
            try:
                repack_tarball(tarball, dest_name, target_dir=orig_dir)
            except FileExists:
                raise BzrCommandError("The target file %s already exists, and is either "
                                      "different to the new upstream tarball, or they "
                                      "are of different formats. Either delete the target "
                                      "file, or use it as the argument to import.")
            tarball_filename = os.path.join(orig_dir, dest_name)
            distribution = distribution.lower()
            distribution_name = lookup_distribution(distribution)
            target_name = distribution
            if distribution_name is None:
                if distribution not in ("debian", "ubuntu"):
                    raise BzrCommandError("Unknown target distribution: %s" \
                            % target_dist)
                else:
                    target_name = None
                    distribution_name = distribution
            db = DistributionBranch(distribution_name, tree.branch, None,
                    tree=tree)
            dbs = DistributionBranchSet()
            dbs.add_branch(db)
            conflicts = db.merge_upstream(tarball_filename,
                    Version(version), current_version)
            info("The new upstream version has been imported. You should "
                 "now update the changelog (try dch -v %s), resolve any "
                 "conflicts, and then commit." % str(version))
        finally:
            tree.unlock()


register_command(cmd_merge_upstream)


class cmd_import_dsc(Command):
    """Import a series of source packages.

    Provide a number of source packages (.dsc files), and they will
    be imported to create a branch with history that reflects those
    packages.

    The first argument is the distribution that these source packages
    were uploaded to, one of "debian" or "ubuntu". It can also
    be the target distribution from the changelog, e.g. "unstable",
    which will be resolved to the correct distribution.

    You can also specify a file (possibly remote) that contains a
    list of source packages (.dsc files) to import using the --file
    option. Each line is taken to be a URI or path to import. The
    sources specified in the file are used in addition to those
    specified on the command line.

    If you have an existing branch containing packaging and you want to
    import a .dsc from an upload done from outside the version control
    system you can use this command.
    """

    takes_args = ['files*']
    
    filename_opt = Option('file', help="File containing URIs of source "
                          "packages to import.", type=str, argname="filename",
                          short_name='F')
    distribution_opt = Option('distribution', help="The distribution that "
            "these packages were uploaded to.", type=str)

    takes_options = [filename_opt, distribution_opt]

    def import_many(self, db, files_list, orig_target):
        cache = DscCache()
        files_list.sort(cmp=DscComp(cache).cmp)
        if not os.path.exists(orig_target):
            os.makedirs(orig_target)
        for dscname in files_list:
            dsc = cache.get_dsc(dscname)
            def get_dsc_part(from_transport, filename):
                from_f = from_transport.get(filename)
                contents = from_f.read()
                to_f = open(os.path.join(orig_target, filename), 'wb')
                try:
                    to_f.write(contents)
                finally:
                    to_f.close()
            base, filename = urlutils.split(dscname)
            from_transport = cache.get_transport(dscname)
            get_dsc_part(from_transport, filename)
            for file_details in dsc['files']:
                name = file_details['name']
                get_dsc_part(from_transport, name)
            db.import_package(os.path.join(orig_target, filename))

    def run(self, files_list, distribution=None, filename=None):
        from bzrlib.plugins.builddeb.errors import MissingChangelogError
        if distribution is None:
            raise BzrCommandError("You must specify the distribution "
                    "these packages were uploaded to using --distribution.")
        distribution = distribution.lower()
        distribution_name = lookup_distribution(distribution)
        if distribution_name is None:
            if distribution not in ("debian", "ubuntu"):
                raise BzrCommandError("Unknown target distribution: %s" \
                        % target_dist)
            else:
                distribution_name = distribution
        try:
            tree = WorkingTree.open_containing('.')[0]
        except NotBranchError:
            raise BzrCommandError("There is no tree to import the packages in to")
        tree.lock_write()
        try:
            if tree.changes_from(tree.basis_tree()).has_changed():
                raise BzrCommandError("There are uncommitted changes in the "
                        "working tree. You must commit before using this "
                        "command")
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
            if len(files_list) < 1:
                raise BzrCommandError("You must give the location of at least one "
                                      "source package to install, or use the "
                                      "--file option.")
            config = debuild_config(tree, tree, False)
            orig_dir = config.orig_dir or default_orig_dir
            orig_target = os.path.join(tree.basedir, default_orig_dir)
            db = DistributionBranch(distribution_name, tree.branch,
                    None, tree=tree)
            dbs = DistributionBranchSet()
            dbs.add_branch(db)
            try:
                (changelog, larstiq) = find_changelog(tree, False)
                last_version = changelog.version
            except MissingChangelogError:
                last_version = None
            tempdir = tempfile.mkdtemp(dir=os.path.join(tree.basedir,
                        '..'))
            try:
                if last_version is not None:
                    upstream_tip = db._revid_of_upstream_version_from_branch(
                            last_version)
                    db._extract_upstream_tree(upstream_tip, tempdir)
                else:
                    db._create_empty_upstream_tree(tempdir)
                self.import_many(db, files_list, orig_target)
            finally:
                shutil.rmtree(tempdir)
        finally:
            tree.unlock()

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
    t = WorkingTree.open_containing('.')[0]
    config = debuild_config(t, t, False)

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


class cmd_mark_uploaded(Command):
    """Mark that this branch has been uploaded, prior to pushing it.
    
    When a package has been uploaded we want to mark the revision
    that it was uploaded in. This command automates doing that
    by marking the current tip revision with the version indicated
    in debian/changelog.
    """
    force = Option('force', help="Mark the upload even if it is already "
            "marked.")

    takes_options = [merge_opt, no_user_conf_opt, force]

    def run(self, merge=False, no_user_config=False, force=None):
        t = WorkingTree.open_containing('.')[0]
        t.lock_write()
        try:
            if t.changes_from(t.basis_tree()).has_changed():
              raise BzrCommandError("There are uncommitted changes in the "
                      "working tree. You must commit before using this "
                      "command")
            config = debuild_config(t, t, no_user_config)
            if not merge:
                merge = config.merge
            (changelog, larstiq) = find_changelog(t, False)
            distributions = changelog.distributions.strip()
            target_dist = distributions.split()[0]
            distribution_name = lookup_distribution(target_dist)
            if distribution_name is None:
                raise BzrCommandError("Unknown target distribution: %s" \
                        % target_dist)
            db = DistributionBranch(distribution_name, t.branch, None)
            dbs = DistributionBranchSet()
            dbs.add_branch(db)
            if db.has_version(changelog.version):
                if not force:
                    raise BzrCommandError("This version has already been "
                            "marked uploaded. Use --force to force marking "
                            "this new version.")
            db.tag_version(changelog.version)
        finally:
            t.unlock()


register_command(cmd_mark_uploaded)


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
        passed = selftest(test_suite_factory=test_suite)
        # invert for shell exit code rules
        return not passed


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
