#    __init__.py -- The plugin for bzr
#    Copyright (C) 2005 Jamie Wilkinson <jaq@debian.org> 
#                  2006, 2007 James Westby <jw+debian@jameswestby.net>
#                  2007 Reinhard Tartler <siretart@tauware.de>
#                  2008-2011 Canonical Ltd.
#
#    This file is part of breezy-debian.
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
import shutil
import tempfile
from typing import Optional

from ... import (
    urlutils,
    )
from ...branch import Branch
try:
    from ...controldir import (
        ControlDir,
        NoColocatedBranchSupport,
        )
except ImportError:  # brz < 3.3
    from ...controldir import ControlDir
    from ...errors import NoColocatedBranchSupport
from ...commands import Command
from ...errors import (
    BzrError,
    BzrCommandError,
    NotBranchError,
    NotLocalUrl,
    NoWorkingTree,
    )
try:
    from ...transport import (
        FileExists,
        NoSuchFile,
    )
except ImportError:
    from ...errors import (
        FileExists,
        NoSuchFile,
    )
from ...option import Option
from ...trace import mutter, note, warning
from ...transport import get_transport
from ...workingtree import WorkingTree

from . import (
    default_build_dir,
    default_orig_dir,
    default_result_dir,
    gettext,
    )
from .config import (
    BUILD_TYPE_MERGE,
    BUILD_TYPE_NATIVE,
    BUILD_TYPE_SPLIT,
    )
from .util import (
    debuild_config,
    )

dont_purge_opt = Option(
    'dont-purge',
    help="Don't purge the build directory after building.")
result_opt = Option(
    'result-dir',
    help="Directory in which to place the resulting package files.", type=str,
    argname="DIRECTORY")
builder_opt = Option(
    'builder',
    help="Command to build the package.", type=str,
    argname="BUILDER")
merge_opt = Option(
    'merge',
    help='Merge the debian part of the source in to the upstream tarball.')
split_opt = Option(
    'split',
    help="Automatically create an .orig.tar.gz from a full source branch.")
build_dir_opt = Option(
    'build-dir',
    help="The dir to use for building.", type=str)
orig_dir_opt = Option(
    'orig-dir',
    help="Directory containing the .orig.tar.gz files. For use when only "
         "debian/ is versioned.", type=str,
         argname="DIRECTORY")
native_opt = Option(
    'native',
    help="Build a native package.")
export_upstream_opt = Option(
    'export-upstream',
    help="Create the .orig.tar.gz from specified bzr branch before building.",
    type=str, argname="BRANCH")
export_upstream_revision_opt = Option(
    'export-upstream-revision',
    help="Select the upstream revision that will be exported.",
    type=str, argname="REVISION")
apt_repository_opts = [Option(
    'apt-repository',
    help='Apt repository to attempt to fetch from',
    type=str), Option(
    'apt-repository-key',
    help='Apt repository key to use for validation',
    type=str)]


class StrictBuildFailed(BzrCommandError):

    _fmt = ("Build refused because there are unknown files in the tree. "
            "To list all known files, run 'bzr unknowns'.")


def _check_tree(tree, subpath, strict=False):
    if strict:
        for unknown in tree.unknowns():
            raise StrictBuildFailed()

    if len(tree.conflicts()) > 0:
        raise BzrCommandError(
            "There are conflicts in the working tree. "
            "You must resolve these before building.")


def _check_uncommitted(tree, subpath):
    if tree.changes_from(tree.basis_tree()).has_changed():
        raise BzrCommandError(gettext(
            "There are uncommitted "
            "changes in the working tree. You must commit "
            "before using this command"))


def _get_changelog_info(tree, subpath, last_version=None, package=None,
                        distribution=None):
    from .util import (
        find_changelog,
        find_last_distribution,
        lookup_distribution,
        MissingChangelogError,
        )
    DEFAULT_FALLBACK_DISTRIBUTION = "debian"
    current_version = last_version
    try:
        (changelog, top_level) = find_changelog(
            tree, subpath, merge=False, max_blocks=2)
    except MissingChangelogError:
        top_level = False
        changelog = None
        if distribution is None:
            distribution = DEFAULT_FALLBACK_DISTRIBUTION
            note(gettext("No distribution specified, and no changelog, "
                         "assuming '%s'"), distribution)
    else:
        if last_version is None:
            current_version = changelog.version.upstream_version
        if package is None:
            package = changelog.package
        if distribution is None:
            distribution = find_last_distribution(changelog)
            if distribution is not None:
                note(gettext("Using distribution %s") % distribution)
            else:
                distribution = DEFAULT_FALLBACK_DISTRIBUTION
                note(gettext("No distribution specified, and no previous "
                             "distribution in changelog. Assuming '%s'"),
                     distribution)
    distribution = distribution.lower()
    distribution_name = lookup_distribution(distribution)
    if distribution_name is None:
        raise BzrCommandError(
            gettext("Unknown target distribution: %s") % distribution)
    return (current_version, package, distribution, distribution_name,
            changelog, top_level)


def _get_upstream_branch_source(
        export_upstream, export_upstream_revision, config, version,
        other_repository=None, guess_upstream_url=None):
    if export_upstream is None and config.upstream_branch:
        export_upstream = config.upstream_branch
    if export_upstream is None:
        if guess_upstream_url is None:
            return None
        export_upstream = guess_upstream_url
    from .upstream.branch import (
        LazyUpstreamBranchSource,
        )
    upstream_revision_map = {}
    if export_upstream_revision:
        upstream_revision_map[version] = export_upstream_revision
    return LazyUpstreamBranchSource(
        export_upstream, config=config,
        upstream_revision_map=upstream_revision_map,
        other_repository=other_repository)


def _get_upstream_sources(local_tree, subpath, packaging_branch,
                          build_type, config, upstream_version, top_level,
                          export_upstream=None,
                          export_upstream_revision=None,
                          trust_package=True,
                          guess_upstream_branch_url=False,
                          apt=None):
    from .upstream import (
        AptSource,
        SelfSplitSource,
        DirectoryScanSource,
        )
    from .upstream.uscan import (
        UScanSource,
        NoWatchFile,
        )
    from .upstream.pristinetar import (
        get_pristine_tar_source,
        )
    yield get_pristine_tar_source(local_tree, packaging_branch)
    yield AptSource(apt=apt)
    try:
        yield UScanSource.from_tree(local_tree, subpath, top_level)
    except NoWatchFile:
        pass

    if guess_upstream_branch_url:
        try:
            from upstream_ontologist.guess import (
                guess_upstream_metadata,
                )
        except ModuleNotFoundError:
            guess_upstream_url = None
        else:
            def guess_upstream_url():
                guessed_upstream_metadata = guess_upstream_metadata(
                    local_tree.abspath(subpath), trust_package=trust_package,
                    net_access=True, consult_external_directory=False)
                return guessed_upstream_metadata.get('Repository')
    else:
        guess_upstream_url = None

    upstream_branch_source = _get_upstream_branch_source(
        export_upstream, export_upstream_revision, config,
        upstream_version, other_repository=packaging_branch.repository,
        guess_upstream_url=guess_upstream_url)
    if upstream_branch_source:
        yield upstream_branch_source

    if build_type == BUILD_TYPE_SPLIT:
        yield SelfSplitSource(local_tree)

    yield DirectoryScanSource('..')


def _get_distiller(
        tree, subpath, packaging_branch, changelog, build_type, config,
        contains_upstream_source=True, top_level=False,
        orig_dir=default_orig_dir, use_existing=False,
        export_upstream=None, export_upstream_revision=None,
        guess_upstream_branch_url=False,
        apt=None):
    from .util import (
        guess_build_type,
        )
    from .upstream import (
        UpstreamProvider,
        )
    from .source_distiller import (
        FullSourceDistiller,
        MergeModeDistiller,
        NativeSourceDistiller,
        DebcargoDistiller,
        )

    if build_type is None:
        build_type = config.build_type
    if build_type is None:
        build_type = guess_build_type(
            tree, changelog.version, subpath, contains_upstream_source)

    note(gettext("Building package in %s mode") % build_type)

    upstream_sources = list(_get_upstream_sources(
        tree, subpath, packaging_branch, build_type=build_type,
        config=config, upstream_version=changelog.version.upstream_version,
        top_level=top_level, export_upstream=export_upstream,
        export_upstream_revision=export_upstream_revision,
        guess_upstream_branch_url=guess_upstream_branch_url,
        apt=apt))

    upstream_provider = UpstreamProvider(
        changelog.package, changelog.version.upstream_version, orig_dir,
        upstream_sources)

    # Turn this into a build type?
    if tree.has_filename(os.path.join(subpath, 'debian/debcargo.toml')):
        return DebcargoDistiller(
            tree, subpath, top_level=top_level,
            use_existing=use_existing)
    if build_type == BUILD_TYPE_MERGE:
        return MergeModeDistiller(
            tree, subpath, upstream_provider, top_level=top_level,
            use_existing=use_existing)
    elif build_type == BUILD_TYPE_NATIVE:
        return NativeSourceDistiller(tree, subpath, use_existing=use_existing)
    else:
        return FullSourceDistiller(tree, subpath, upstream_provider, use_existing=use_existing)


class cmd_builddeb(Command):
    """Builds a Debian package from a branch.

    If BRANCH is specified it is assumed that the branch you wish to build is
    located there. If it is not specified then the current directory is used.

    By default, if a working tree is found, it is used to build. Otherwise the
    last committed revision found in the branch is used. To force building the
    last committed revision use --revision -1. You can also specify any other
    revision with the --revision option.

    If you only wish to export the package, and not build it (especially useful
    for merge mode), use --export-only.

    To leave the build directory when the build is completed use --dont-purge.

    Specify the command to use when building using the --builder option, by
    default "debuild" is used. It can be overriden by setting the "builder"
    variable in you configuration. You can specify extra options to build with
    by adding them to the end of the command, after using "--" to indicate the
    end of the options to builddeb itself. The builder that you specify must
    accept the options you provide at the end of its command line.

    You can also specify directories to use for different things. --build-dir
    is the directory to build the packages beneath, which defaults to
    '../build-area'. '--orig-dir' specifies the directory that contains the
    .orig.tar.gz files , which defaults to '..'. '--result-dir' specifies where
    the resulting package files should be placed, which defaults to '..'.
    --result-dir will have problems if you use a build command that places
    the results in a different directory.

    The --reuse option will be useful if you are in merge mode, and the
    upstream tarball is very large. It attempts to reuse a build directory from
    an earlier build. It will fail if one doesn't exist, but you can create one
    by using --export-only.

    --quick allows you to define a quick-builder in your configuration files,
    which will be used when this option is passed. It defaults to 'fakeroot
    debian/rules binary'. It is overriden if --builder is passed. Using this
    and --reuse allows for fast rebuilds.
    """
    export_only_opt = Option('export-only', help="Export only, don't build.",
                             short_name='e')
    use_existing_opt = Option('use-existing',
                              help="Use an existing build directory.")
    quick_opt = Option('quick', help="Quickly build the package, uses "
                       "quick-builder, which defaults to \"fakeroot "
                       "debian/rules binary\".")
    reuse_opt = Option('reuse', help="Try to avoid exporting too much on each "
                       "build. Only works in merge mode; it saves unpacking "
                       "the upstream tarball each time. Implies --dont-purge "
                       "and --use-existing.")
    source_opt = Option('source', help="Build a source package.",
                        short_name='S')
    strict_opt = Option(
        'strict',
        help='Refuse to build if there are unknown files in'
        ' the working tree, --no-strict disables the check.')
    package_merge_opt = Option(
        'package-merge', help="Build using the "
        "appropriate -v and -sa options for merging in the changes from "
        "another source.")
    guess_upstream_branch_url_opt = Option(
        'guess-upstream-branch-url', help=(
            'Guess upstream branch URL if unknown '
            '(requires upstream-ontologist)'))
    takes_args = ['branch_or_build_options*']
    aliases = ['bd', 'debuild']
    takes_options = [
        export_only_opt, dont_purge_opt, use_existing_opt, result_opt,
        builder_opt, merge_opt, build_dir_opt, orig_dir_opt, split_opt,
        export_upstream_opt, export_upstream_revision_opt, quick_opt,
        reuse_opt, native_opt, source_opt, 'revision', strict_opt,
        package_merge_opt, guess_upstream_branch_url_opt,
        ] + apt_repository_opts

    def _get_tree_and_branch(self, location):
        if location is None:
            location = "."
        transport = get_transport(location)
        try:
            transport.local_abspath('.')
        except NotLocalUrl:
            is_local = False
        else:
            is_local = True
        controldir, relpath = ControlDir.open_containing_from_transport(
            transport)
        tree, branch = controldir._get_tree_branch()
        return tree, branch, is_local, controldir.user_url, relpath

    def _get_build_tree(self, revision, tree, branch):
        if revision is None and tree is not None:
            note(gettext("Building using working tree"))
        else:
            if revision is None:
                revid = branch.last_revision()
            elif len(revision) == 1:
                revid = revision[0].in_history(branch).rev_id
            else:
                raise BzrCommandError(gettext(
                    'bzr builddeb --revision takes exactly one '
                    'revision specifier.'))
            note(gettext("Building branch from revision %s"), revid)
            tree = branch.repository.revision_tree(revid)
        return tree

    def _build_type(self, merge, native, split):
        if merge:
            return BUILD_TYPE_MERGE
        if native:
            return BUILD_TYPE_NATIVE
        if split:
            return BUILD_TYPE_SPLIT
        return None

    def _get_build_command(self, config, builder, quick, build_options):
        if builder is None:
            if quick:
                builder = config.quick_builder
                if builder is None:
                    builder = "fakeroot debian/rules binary"
            else:
                builder = config.builder
                if builder is None:
                    builder = "debuild"
        if build_options:
            builder += " " + " ".join(build_options)
        return builder

    def _get_dirs(self, config, location, is_local, result_dir, build_dir,
                  orig_dir):
        def _get_dir(supplied, if_local, if_not):
            if supplied is None:
                if is_local:
                    supplied = if_local
                else:
                    supplied = if_not
            if supplied is not None:
                if is_local:
                    supplied = os.path.join(
                            urlutils.local_path_from_url(location),
                            supplied)
                    supplied = os.path.realpath(supplied)
            return supplied

        result_dir = _get_dir(
            result_dir, config.result_dir, config.user_result_dir)
        build_dir = _get_dir(
            build_dir, config.build_dir or default_build_dir,
            config.user_build_dir or 'build-area')
        orig_dir = _get_dir(
            orig_dir, config.orig_dir or default_orig_dir,
            config.user_orig_dir or 'build-area')
        return result_dir, build_dir, orig_dir

    def _branch_and_build_options(self, branch_or_build_options_list,
                                  source=False):
        branch = None
        build_options = []
        source_opt = False
        if branch_or_build_options_list is not None:
            for opt in branch_or_build_options_list:
                if opt.startswith("-") or branch is not None:
                    build_options.append(opt)
                    if opt == "-S" or opt == "--source":
                        source_opt = True
                else:
                    branch = opt
        if source and not source_opt:
            build_options.append("-S")
        if source_opt:
            source = True
        return branch, build_options, source

    def run(self, branch_or_build_options_list=None, verbose=False,
            export_only=False, dont_purge=False, use_existing=False,
            result_dir=None, builder=None, merge=None, build_dir=None,
            export_upstream=None, export_upstream_revision=None,
            orig_dir=None, split=None,
            quick=False, reuse=False, native=None,
            source=False, revision=None, package_merge=None,
            strict=False, guess_upstream_branch_url=False,
            apt_repository=None, apt_repository_key=None):
        from debian.changelog import ChangelogParseError
        from .builder import DebBuild
        from .config import UpstreamMetadataSyntaxError
        from .hooks import run_hook
        from .source_distiller import DebcargoError
        from .util import (
            NoPreviousUpload,
            dget_changes,
            find_changelog,
            find_previous_upload,
            tree_contains_upstream_source,
            find_changes_files,
            )

        location, build_options, source = self._branch_and_build_options(
                branch_or_build_options_list, source)
        tree, branch, is_local, location, subpath = self._get_tree_and_branch(
            location)
        tree = self._get_build_tree(revision, tree, branch)
        _check_tree(tree, subpath, strict=strict)

        if apt_repository is not None:
            from .apt_repo import RemoteApt
            apt = RemoteApt.from_string(apt_repository, apt_repository_key)
        else:
            apt = None

        with tree.lock_read():
            try:
                config = debuild_config(tree, subpath)
            except UpstreamMetadataSyntaxError as e:
                raise BzrCommandError(
                    gettext('Unable to parse upstream metadata file %s: %s')
                    % (e.path, e.error))
            if reuse:
                note(gettext("Reusing existing build dir"))
                dont_purge = True
                use_existing = True
            build_type = self._build_type(merge, native, split)

            contains_upstream_source = tree_contains_upstream_source(
                    tree, subpath)
            try:
                (changelog, top_level) = find_changelog(
                    tree, subpath, merge=not contains_upstream_source)
            except ChangelogParseError as e:
                raise BzrCommandError(
                    gettext("Unable to parse changelog: %s") %
                    e)

            if package_merge:
                try:
                    prev_version = find_previous_upload(
                        tree, subpath, not contains_upstream_source)
                except NoPreviousUpload:
                    prev_version = None
                if prev_version is None:
                    build_options.extend(["-sa", "-v0"])
                else:
                    build_options.append("-v%s" % str(prev_version))
                    if (prev_version.upstream_version !=
                            changelog.version.upstream_version or
                            prev_version.epoch != changelog.version.epoch):
                        build_options.append("-sa")
            build_cmd = self._get_build_command(
                config, builder, quick, build_options)
            result_dir, build_dir, orig_dir = self._get_dirs(
                config, location or ".", is_local, result_dir, build_dir,
                orig_dir)

            distiller = _get_distiller(
                tree, subpath, branch, build_type=build_type, config=config,
                changelog=changelog,
                contains_upstream_source=contains_upstream_source,
                orig_dir=orig_dir, use_existing=use_existing,
                top_level=top_level, export_upstream=export_upstream,
                export_upstream_revision=export_upstream_revision,
                guess_upstream_branch_url=guess_upstream_branch_url,
                apt=apt)

            build_source_dir = os.path.join(
                build_dir,
                "%s-%s" % (changelog.package,
                           changelog.version.upstream_version))

            builder = DebBuild(
                distiller, build_source_dir, build_cmd,
                use_existing=use_existing)
            builder.prepare()
            run_hook(tree, 'pre-export', config)
            try:
                builder.export()
            except DebcargoError as e:
                raise BzrCommandError(str(e))
            if not export_only:
                run_hook(tree, 'pre-build', config, wd=build_source_dir)
                builder.build()
                run_hook(tree, 'post-build', config, wd=build_source_dir)
                if not dont_purge:
                    builder.clean()
                changes_paths = []
                for kind, entry in find_changes_files(
                        build_dir, changelog.package, changelog.version):
                    changes_paths.append(entry.path)
                if not changes_paths:
                    if result_dir is not None:
                        raise BzrCommandError(
                            "Could not find the .changes "
                            "file from the build: %s" % build_dir)
                    return
                if is_local:
                    target_dir = result_dir or default_result_dir
                    target_dir = os.path.join(
                            urlutils.local_path_from_url(location),
                            target_dir)
                else:
                    target_dir = "."
                if not os.path.exists(target_dir):
                    os.makedirs(target_dir)
                for changes_path in changes_paths:
                    dget_changes(changes_path, target_dir)


class cmd_get_orig_source(Command):
    """Gets the upstream tar file for the packaging branch."""

    directory_opt = Option(
        'directory',
        help='Directory from which to retrieve the packaging data',
        short_name='d', type=str)

    takes_options = [directory_opt] + apt_repository_opts
    takes_args = ["version?"]

    def run(self, directory='.', version=None, apt_repository=None,
            apt_repository_key=None):
        from .upstream import (
            AptSource,
            UpstreamProvider,
            )
        from .upstream.uscan import (
            UScanSource,
            NoWatchFile,
            )
        from .upstream.pristinetar import (
            get_pristine_tar_source,
            )
        from .util import (
            find_changelog,
            )
        tree, subpath = WorkingTree.open_containing(directory)
        config = debuild_config(tree, subpath)

        (changelog, larstiq) = find_changelog(tree, subpath, merge=True)
        orig_dir = config.orig_dir
        if orig_dir is None:
            orig_dir = default_orig_dir

        if version is None:
            version = changelog.version.upstream_version

        if apt_repository is not None:
            from .apt_repo import RemoteApt
            apt = RemoteApt.from_string(apt_repository, apt_repository_key)
        else:
            apt = None

        upstream_sources = [
            get_pristine_tar_source(tree, tree.branch),
            AptSource(apt)]
        try:
            uscan_source = UScanSource.from_tree(tree, subpath, larstiq)
        except NoWatchFile:
            pass
        else:
            upstream_sources.append(uscan_source)

        upstream_provider = UpstreamProvider(
            changelog.package,
            str(version), orig_dir,
            upstream_sources)

        result = upstream_provider.provide(orig_dir)
        for tar, component in result:
            note(gettext("Tar now in %s") % tar)


class cmd_merge_upstream(Command):
    """Merges a new upstream version into the current branch.

    Takes a new upstream version and merges it in to your branch, so that your
    packaging changes are applied to the new version.

    You must supply the source to import from, and in some cases
    the version number of the new release. The source can be a .tar.gz, .tar,
    .tar.bz2, .tar.xz, .tgz or .zip archive, a directory or a branch. The
    source may also be a remote file described by a URL.

    In most situations the version can be guessed from the upstream source.
    If the upstream version can not be guessed or if it is guessed
    incorrectly then the version number can be specified with --version.

    The distribution this version is targetted at can be specified with
    --distribution. This will be used to guess the version number suffix
    that you want, but you can always correct it in the resulting
    debian/changelog.

    If there is no debian changelog in the branch to retrieve the package
    name from then you must pass the --package option. If this version
    will change the name of the source package then you can use this option
    to set the new name.

    examples::

        bzr merge-upstream --version 0.2 \
            http://example.org/releases/scruff-0.2.tar.gz

    If you are merging a branch as well as the tarball then you can
    specify the branch after the tarball, along with -r to specify the
    revision of that branch to take::

        bzr merge-upstream --version 0.2 \
            http://example.org/releases/scruff-0.2.tar.gz \
            http://scruff.org/bzr/scruff.dev -r tag:0.2

    If there is no upstream release tarball, and you want bzr-builddeb to
    create the tarball for you::

        bzr merge-upstream --version 0.2 http://scruff.org/bzr/scruff.dev

    Note that the created tarball is just the same as the contents of
    the branch at the specified revision. If you wish to have something
    different, for instance the results of running "make dist", then you
    should create the tarball first, and pass it to the command as in
    the second example.
    """
    takes_args = ['location?', 'upstream_branch?']
    aliases = ['mu']

    package_opt = Option('package', help="The name of the source package.",
                         type=str)
    version_opt = Option(
        'version',
        help="The upstream version number of this release, for example "
        "\"0.2\".", type=str)
    distribution_opt = Option(
        'distribution', help="The distribution that "
        "this release is targetted at.", type=str)
    directory_opt = Option('directory',
                           help='Working tree into which to merge.',
                           short_name='d', type=str)
    last_version_opt = Option('last-version',
                              help='The full version of the last time '
                              'upstream was merged.', type=str)
    force_opt = Option('force',
                       help=('Force a merge even if the upstream branch '
                             'has not changed.'))
    snapshot_opt = Option(
        'snapshot', help="Merge a snapshot from the "
        "upstream branch rather than a new upstream release.")

    release_opt = Option(
        'release', help='Merge a release from the upstream branch.')

    force_pristine_tar_opt = Option(
        'force-pristine-tar', help=(
            'Force the use of pristine-tar, even if no '
            'pristine-tar branch exists'))

    dist_command_opt = Option(
        'dist-command', type=str,
        help='Command to run for creating an upstream tarball from a '
        'VCS snapshot.')

    guess_upstream_branch_url_opt = Option(
        'guess-upstream-branch-url', help=(
            'Guess upstream branch URL if unknown '
            '(requires upstream-ontologist)'))

    takes_options = [
        package_opt, version_opt,
        distribution_opt, directory_opt, last_version_opt,
        force_opt, 'revision', 'merge-type',
        snapshot_opt, force_pristine_tar_opt,
        dist_command_opt, guess_upstream_branch_url_opt, release_opt]

    def run(self, location: Optional[str] = None,
            upstream_branch: Optional[str] = None,
            version: Optional[str] = None,
            distribution: Optional[str] = None, package: Optional[str] = None,
            directory: str = ".", revision=None, merge_type=None,
            last_version: Optional[str] = None,
            force: Optional[bool] = None, snapshot: Optional[bool] = None,
            release: Optional[bool] = None,
            force_pristine_tar: bool = False,
            dist_command: Optional[str] = None,
            guess_upstream_branch_url: bool = False):
        from debian.changelog import Version

        from .hooks import run_hook
        from .merge_upstream import (
            changelog_add_new_version,
            do_merge,
            get_tarballs,
            PreviousVersionTagMissing,
            )
        from .upstream import (
            PackageVersionNotPresent,
            TarfileSource,
            )
        from .upstream.branch import (
            UpstreamBranchSource,
            run_dist_command,
            )
        from .upstream.uscan import (
            UScanSource,
            NoWatchFile,
            )
        from .util import (
            detect_version_kind,
            guess_build_type,
            get_files_excluded,
            tree_contains_upstream_source,
            )

        tree, subpath = WorkingTree.open_containing(directory)
        with tree.lock_write():
            _check_uncommitted(tree, subpath)
            config = debuild_config(tree, subpath)
            (current_version, package, distribution, distribution_name,
             changelog, top_level) = _get_changelog_info(
                 tree, subpath, last_version, package, distribution)
            if package is None:
                raise BzrCommandError(
                    "You did not specify --package, and "
                    "there is no changelog from which to determine the "
                    "package name, which is needed to know the name to "
                    "give the .orig.tar.gz. Please specify --package.")

            if snapshot is None and release is None:
                if current_version is not None:
                    version_kind = detect_version_kind(current_version)
                else:
                    version_kind = None
            elif snapshot is not None and release is not None:
                raise BzrCommandError(
                    '--release and --snapshot are incompatible')
            elif snapshot:
                version_kind = "snapshot"
            elif release:
                version_kind = "release"

            if version_kind is None:
                version_kind = "release"

            try:
                files_excluded = get_files_excluded(tree, subpath, top_level)
            except NoSuchFile as e:
                mutter('Copyright file not found: %s', e)
                files_excluded = []
            contains_upstream_source = tree_contains_upstream_source(
                tree, subpath)
            if changelog is None:
                changelog_version = None
            else:
                changelog_version = changelog.version
            build_type = config.build_type
            if build_type is None:
                build_type = guess_build_type(
                    tree, changelog_version, subpath, contains_upstream_source)
            need_upstream_tarball = (build_type != BUILD_TYPE_MERGE)
            if build_type == BUILD_TYPE_NATIVE:
                raise BzrCommandError(gettext(
                    "Merge upstream in native mode is not supported."))

            if upstream_branch is not None:
                upstream_branch = Branch.open(upstream_branch)
            elif location is not None and not os.path.isfile(location):
                try:
                    upstream_branch = Branch.open(location)
                except NotBranchError:
                    upstream_branch = None
            elif (upstream_branch is None and
                    config.upstream_branch is not None):
                note(gettext("Using upstream branch %s (from configuration)"),
                     config.upstream_branch)
                upstream_branch = Branch.open(config.upstream_branch)
            elif upstream_branch is None and guess_upstream_branch_url:
                try:
                    from upstream_ontologist.guess import (
                        guess_upstream_metadata,
                        )
                except ModuleNotFoundError:
                    warning(
                        'upstream-ontologist not available, '
                        'not guess upstream branch URL')
                    upstream_branch = None
                else:
                    guessed_upstream_metadata = guess_upstream_metadata(
                        tree.abspath(subpath), trust_package=False,
                        net_access=True, consult_external_directory=False)
                    guessed_repo = guessed_upstream_metadata.get('Repository')
                    if guessed_repo:
                        note('Opening upstream-ontologist provided branch %s',
                             guessed_repo)
                        upstream_branch = Branch.open(guessed_repo)
                    else:
                        upstream_branch = None

            if dist_command:
                def create_dist(tree, package, version, target_dir):
                    return run_dist_command(
                        tree, package, version, target_dir, dist_command)
            else:
                create_dist = None

            if upstream_branch is not None:
                upstream_branch_source = UpstreamBranchSource.from_branch(
                    upstream_branch, config=config, local_dir=tree.controldir,
                    create_dist=create_dist, version_kind=version_kind)
            else:
                upstream_branch_source = None

            if location is not None:
                try:
                    primary_upstream_source = UpstreamBranchSource.from_branch(
                        Branch.open(location), config=config,
                        local_dir=tree.controldir,
                        create_dist=create_dist, version_kind=version_kind)
                except NotBranchError:
                    primary_upstream_source = TarfileSource(location, version)
            else:
                if snapshot:
                    if upstream_branch_source is None:
                        raise BzrCommandError(gettext(
                            "--snapshot requires an upstream branch source"))
                    primary_upstream_source = upstream_branch_source
                else:
                    try:
                        primary_upstream_source = UScanSource.from_tree(
                            tree, subpath, top_level)
                    except NoWatchFile:
                        if upstream_branch_source is None:
                            raise BzrCommandError(gettext(
                                "no upstream source location known; "
                                "add watch file or specify upstream repository?"))
                        primary_upstream_source = upstream_branch_source

            if revision is not None:
                if upstream_branch is None:
                    raise BzrCommandError(gettext(
                        "--revision can only be "
                        "used with a valid upstream branch"))
                if len(revision) > 1:
                    raise BzrCommandError(gettext(
                        "merge-upstream takes only a single --revision"))
                upstream_revspec = revision[0]
                upstream_revisions = {
                    None: upstream_revspec.as_revision_id(upstream_branch)}
            else:
                upstream_revisions = None

            if version is None and upstream_revisions is not None:
                # Look up the version from the upstream revision
                unmangled_version, version = upstream_branch_source.get_version(
                    package, current_version, upstream_revisions[None])
            elif version is None and primary_upstream_source is not None:
                unmangled_version, version = primary_upstream_source.get_latest_version(
                    package, current_version)
            if version is None:
                if upstream_branch_source is not None:
                    raise BzrCommandError(gettext(
                        "You must specify "
                        "the version number using --version or specify "
                        "--snapshot to merge a snapshot from the upstream "
                        "branch."))
                else:
                    raise BzrCommandError(gettext(
                        "You must specify the "
                        "version number using --version."))
            note(gettext("Using version string %s."), version)
            # Look up the revision id from the version string
            if (upstream_revisions is None and
                    upstream_branch_source is not None):
                try:
                    upstream_revisions = upstream_branch_source\
                        .version_as_revisions(package, version)
                except PackageVersionNotPresent:
                    raise BzrCommandError(
                        "Version %s can not be found in upstream branch %r. "
                        "Specify the revision manually using --revision or "
                        "adjust 'export-upstream-revision' in the "
                        "configuration." % (version, upstream_branch_source))
            if need_upstream_tarball:
                target_dir = self.enter_context(tempfile.TemporaryDirectory())
                try:
                    locations = primary_upstream_source.fetch_tarballs(
                        package, version, target_dir, components=[None])
                except PackageVersionNotPresent:
                    if upstream_revisions is not None:
                        locations = upstream_branch_source.fetch_tarballs(
                            package, version, target_dir, components=[None],
                            revisions=upstream_revisions)
                    else:
                        raise
                orig_dir = config.orig_dir or default_orig_dir
                try:
                    tarball_filenames = get_tarballs(
                        orig_dir, tree, package, version, locations)
                except FileExists as e:
                    raise BzrCommandError(
                        "The target file %s already exists, and is either "
                        "different to the new upstream tarball, or they "
                        "are of different formats. Either delete the target "
                        "file, or use it as the argument to import."
                        % e.path)
                try:
                    conflicts, imported_revids = do_merge(
                        tree, subpath, tarball_filenames, package, version,
                        current_version, upstream_branch, upstream_revisions,
                        merge_type, force=force,
                        force_pristine_tar=force_pristine_tar,
                        files_excluded=files_excluded)
                except PreviousVersionTagMissing as e:
                    raise BzrCommandError(str(e))
            if (current_version is not None and
                    Version(current_version) >= Version(version)):
                raise BzrCommandError(
                    gettext("Upstream version %s has already been merged.") %
                    version)
            changelog_add_new_version(
                tree, subpath, version, distribution_name, changelog, package)
            run_hook(tree, 'merge-upstream', config)
        if not need_upstream_tarball:
            note(gettext("An entry for the new upstream version has been "
                 "added to the changelog."))
        else:
            note(gettext("The new upstream version has been imported."))
            if conflicts:
                note(gettext("You should now resolve the conflicts, review "
                     "the changes, and then commit."))
            else:
                note(gettext("You should now review the changes and "
                             "then commit."))


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
                          "packages to import.", type=str, short_name='F')

    takes_options = [filename_opt]

    def import_many(self, db, files_list, orig_target):
        from .import_dsc import (
            DscCache,
            DscComp,
            )
        from .util import (
            open_file_via_transport,
            )
        cache = DscCache()
        files_list.sort(key=DscComp(cache).key)
        if not os.path.exists(orig_target):
            os.makedirs(orig_target)
        for dscname in files_list:
            dsc = cache.get_dsc(dscname)

            def get_dsc_part(from_transport, filename):
                from_f = open_file_via_transport(filename, from_transport)
                contents = from_f.read()
                with open(os.path.join(orig_target, filename), 'wb') as to_f:
                    to_f.write(contents)
            base, filename = urlutils.split(dscname)
            from_transport = cache.get_transport(dscname)
            get_dsc_part(from_transport, filename)
            for file_details in dsc['files']:
                name = file_details['name']
                get_dsc_part(from_transport, name)
            db.import_package(os.path.join(orig_target, filename))

    def run(self, files_list, file=None):
        from .import_dsc import (
            DistributionBranch,
            DistributionBranchSet,
            )
        from .util import (
            find_changelog,
            open_file,
            MissingChangelogError,
            )
        try:
            tree, subpath = WorkingTree.open_containing('.')
        except NotBranchError:
            raise BzrCommandError(gettext(
                "There is no tree to import the packages in to"))
        with tree.lock_write():
            _check_uncommitted(tree, subpath)
            if files_list is None:
                files_list = []
            if file is not None:
                if isinstance(file, str):
                    file = file.encode('utf-8')
                sources_file = open_file(file)
                for line in sources_file:
                    line = line.strip()
                    if len(line) > 0:
                        files_list.append(line)
            if len(files_list) < 1:
                raise BzrCommandError(gettext(
                    "You must give the location of "
                    "at least one source package to install, or use the "
                    "--file option."))
            config = debuild_config(tree, subpath)
            if config.build_type == BUILD_TYPE_MERGE:
                raise BzrCommandError(
                    gettext("import-dsc in merge mode is not yet supported."))
            orig_target = os.path.join(tree.basedir, default_orig_dir)
            db = DistributionBranch(tree.branch, tree.branch, tree=tree)
            dbs = DistributionBranchSet()
            dbs.add_branch(db)
            try:
                (changelog, top_level) = find_changelog(
                    tree, subpath, merge=False)
                last_version = changelog.version
            except MissingChangelogError:
                last_version = None
            with tempfile.TemporaryDirectory(
                    dir=os.path.join(tree.basedir, '..')) as tempdir:
                if last_version is not None:
                    if not db.pristine_upstream_source.has_version(
                            changelog.package, last_version.upstream_version):
                        raise BzrCommandError(gettext(
                            "Unable to find the tag "
                            "for the previous upstream version (%(version)s) "
                            "in the branch. Consider importing it via "
                            "import-upstream. If it is already present in the "
                            "branch please make sure it is tagged as %(tag)r.")
                            % {"version": last_version,
                               "tag": db.pristine_upstream_source.tag_name(
                                   last_version.upstream_version)})
                    upstream_tips = db.pristine_upstream_source\
                        .version_as_revisions(
                                changelog.package,
                                last_version.upstream_version)
                    db.extract_upstream_tree(upstream_tips, tempdir)
                else:
                    db.create_empty_upstream_tree(tempdir)
                self.import_many(db, files_list, orig_target)


class cmd_import_upstream(Command):
    """Imports an upstream tarball.

    This will import an upstream tarball in to your branch, but not modify the
    working tree. Use merge-upstream if you wish to directly merge the new
    upstream version in to your tree.

    The imported revision can be accessed using the tag name that will be
    reported at the end of a successful operation. The revision will include
    the pristine-tar data that will allow other commands to recreate the
    tarball when needed.

    For instance::

        $ bzr import-upstream 1.2.3 ../package_1.2.3.orig.tar.gz

    If upstream is packaged in bzr, you should provide the upstream branch
    whose tip commit is the closest match to the tarball::

        $ bzr import-upstream 1.2.3 ../package_1.2.3.orig.tar.gz ../upstream

    After doing this, commands that assume there is an upstream tarball, like
    'bzr builddeb' will be able to recreate the one provided at import-upstream
    time, meaning that you don't need to distribute the tarball in addition to
    the branch.

    If you want to manually merge with the imported upstream, you can do::

        $ bzr merge . -r tag:upstream-1.2.3

    The imported revision will have file ids taken from your branch, the
    upstream branch, or previous tarball imports as necessary. In addition
    the parents of the new revision will be the previous upstream tarball
    import and the tip of the upstream branch if you supply one.
    """

    takes_options = [
        'revision',
        Option(
            'force-pristine-tar',
            help=('Force creation of a new '
                  'pristine-tar branch, even if one does not exist.'))]

    takes_args = ['version', 'location', 'upstream_branch?']

    def run(self, version, location, upstream_branch=None, revision=None,
            force_pristine_tar=False):
        from debian.changelog import Version
        from .import_dsc import (
            DistributionBranch,
            DistributionBranchSet,
            )
        from .util import (
            md5sum_filename,
            )
        # TODO: search for similarity etc.
        branch, _ = Branch.open_containing('.')
        if upstream_branch is None:
            upstream = None
        else:
            upstream = Branch.open(upstream_branch)
        self.add_cleanup(branch.lock_write().unlock)
        tempdir = self.enter_context(tempfile.TemporaryDirectory(
            dir=branch.controldir.root_transport.clone('..')
            .local_abspath('.')))
        db = DistributionBranch(branch, pristine_upstream_branch=branch)
        if db.pristine_upstream_source.has_version(None, version):
            raise BzrCommandError(
                gettext("Version %s is already present.") % version)
        tagged_versions = {}
        for tversion, tcomponents in db.pristine_upstream_source.iter_versions():
            tagged_versions[Version(tversion)] = tcomponents
        tag_order = sorted(tagged_versions.keys())
        if tag_order:
            base_revisions = tagged_versions[tag_order[-1]]
        else:
            base_revisions = {}
        if base_revisions:
            if upstream is not None:
                # See bug lp:309682
                for parent in base_revisions.values():
                    upstream.repository.fetch(branch.repository, parent)
            db.extract_upstream_tree(base_revisions, tempdir)
            parents = {}
            for name, base_revid in base_revisions.items():
                parents[name] = [base_revid]
        else:
            parents = {}
            db.create_empty_upstream_tree(tempdir)
        tree = db.branch.basis_tree()
        tree.lock_read()
        dbs = DistributionBranchSet()
        dbs.add_branch(db)
        if revision is None:
            upstream_revid = None
        elif len(revision) == 1:
            upstream_revid = revision[0].in_history(upstream).rev_id
        else:
            raise BzrCommandError(gettext(
                'bzr import-upstream --revision takes exactly'
                ' one revision specifier.'))
        tarballs = [(location, None, md5sum_filename(location))]
        for (component, tag_name, revid,
             pristine_tar_imported) in db.import_upstream_tarballs(
                tarballs, None, version, parents, upstream_branch=upstream,
                upstream_revisions={None: upstream_revid},
                force_pristine_tar=force_pristine_tar):
            if component is None:
                self.outf.write(gettext(
                    'Imported %(location)s as tag:%(tag)s.\n') % {
                        "location": location, "tag": tag_name})
            else:
                self.outf.write(gettext(
                    'Imported %(location)s (%(component)s) as tag:%(tag)s.\n')
                    % {
                        "location": location,
                        "component": component,
                        "tag": tag_name})


class cmd_builddeb_do(Command):
    """Run a command in an exported package, copying the result back.

    For a merge mode package the full source is not available, making some
    operations difficult. This command allows you to run any command in an
    exported source directory, copying the resulting debian/ directory back
    to your branch if the command is successful.

    For instance:

      bzr builddeb-do

    will run a shell in the unpacked source. Any changes you make in the
    ``debian/`` directory (and only those made in that directory) will be
    copied back to the branch. If you exit with a non-zero exit code (e.g.
    "exit 1"), then the changes will not be copied back.

    You can also specify single commands to be run, e.g.

      bzr builddeb-do "dpatch-edit-patch 01-fix-build"

    Note that only the first argument is used as the command, and so the above
    example had to be quoted.
    """

    takes_args = ['command*']
    takes_options = [
        Option('no-preparation', help='Don\'t apply/unapply patches.'),
        ] + apt_repository_opts
    aliases = ['bd-do']

    def run(self, command_list=None, no_preparation=False,
            apt_repository=None, apt_repository_key=None):
        import subprocess
        from .source_distiller import (
            MergeModeDistiller,
            )
        from .builder import (
            BuildFailedError,
            DebBuild,
            )
        from .upstream import (
            AptSource,
            UpstreamProvider,
            )
        from .upstream.uscan import (
            UScanSource,
            NoWatchFile,
            )
        from .upstream.pristinetar import (
            get_pristine_tar_source,
            )
        from .hooks import run_hook
        from .util import (
            find_changelog,
            guess_build_type,
            tree_contains_upstream_source,
            )
        t, subpath = WorkingTree.open_containing('.')
        self.add_cleanup(t.lock_read().unlock)
        config = debuild_config(t, subpath)
        (changelog, top_level) = find_changelog(
            t, subpath, merge=False, max_blocks=2)

        contains_upstream_source = tree_contains_upstream_source(t, subpath)
        if changelog is None:
            changelog_version = None
        else:
            changelog_version = changelog.version
        build_type = config.build_type
        if build_type is None:
            build_type = guess_build_type(
                t, changelog_version, subpath, contains_upstream_source)

        if build_type != BUILD_TYPE_MERGE:
            raise BzrCommandError(gettext(
                "This command only works for merge "
                "mode packages. See /usr/share/doc/bzr-builddeb"
                "/user_manual/merge.html for more information."))

        give_instruction = False
        if command_list is None:
            try:
                command_list = [os.environ['SHELL']]
            except KeyError:
                command_list = ["/bin/sh"]
            give_instruction = True
        build_dir = config.build_dir
        if build_dir is None:
            build_dir = default_build_dir
        orig_dir = config.orig_dir
        if orig_dir is None:
            orig_dir = default_orig_dir

        if apt_repository is not None:
            from .apt_repo import RemoteApt
            apt = RemoteApt.from_string(apt_repository, apt_repository_key)
        else:
            apt = None

        upstream_provider = UpstreamProvider(
            changelog.package, changelog.version.upstream_version, orig_dir,
            [get_pristine_tar_source(t, t.branch),
             AptSource(apt=apt),
             UScanSource(t, subpath, top_level)])

        distiller = MergeModeDistiller(
                t, subpath, upstream_provider, top_level=top_level)

        build_source_dir = os.path.join(
            build_dir,
            changelog.package + "-" + changelog.version.upstream_version)

        command = " ".join(command_list)

        builder = DebBuild(distiller, build_source_dir, command)
        builder.prepare()
        run_hook(t, 'pre-export', config)
        builder.export()
        note(gettext('Running "%s" in the exported directory.') % (command))
        if give_instruction:
            note(gettext('If you want to cancel your changes then exit '
                 'with a non-zero exit code, e.g. run "exit 1".'))
        if not no_preparation:
            builder.before_build()
        try:
            builder.build()
        except BuildFailedError:
            raise BzrCommandError(gettext(
                'Not updating the working tree as the command failed.'))
        finally:
            if not no_preparation:
                try:
                    builder.after_build()
                except subprocess.CalledProcessError:
                    raise BzrCommandError(gettext(
                        'After build processing failed. Aborting.'))
        note(gettext("Copying debian/ back"))
        if top_level:
            destination = ''
        else:
            destination = 'debian/'
        destination = os.path.join(t.basedir, destination)
        source_debian = os.path.join(build_source_dir, 'debian')
        for filename in os.listdir(source_debian):
            proc = subprocess.Popen('cp -apf "%s" "%s"' % (
                 os.path.join(source_debian, filename), destination),
                 shell=True)
            proc.wait()
            if proc.returncode != 0:
                raise BzrCommandError(gettext('Copying back debian/ failed'))
        builder.clean()
        note(gettext('If any files were added or removed you should run '
                     '"bzr add" or "bzr rm" as appropriate.'))


class cmd_dep3_patch(Command):
    """Format the changes in a branch as a DEP-3 patch.

    This will generate a patch file containing as much information
    specified by DEP-3 (http://dep.debian.net/deps/dep3/) as possible.

    The patch will contain all changes that are not merged into
    the current branch (either that in the current working directory
    or specified by --directory) but are present and committed
    in the branch at the specified location.

    To generate the "Status" header, this command will check the
    upstream branch to verify if the change has made it upstream,
    unless --no-upstream-check was specified.

    examples::

        bzr dep3-patch lp:~user/project/feature-branch > \\
                debian/patches/01_feature
    """

    takes_args = ["location?"]

    directory_opt = Option('directory',
                           help='Packaging tree for which to generate patch.',
                           short_name='d', type=str)

    no_upstream_check_opt = Option(
        'no-upstream-check',
        help="Don't check whether patch has been merged upstream.")

    takes_options = [
        directory_opt, "revision", "change", no_upstream_check_opt]

    def run(self, location=".", directory=".", revision=None,
            no_upstream_check=False):
        from .dep3 import (
            determine_applied_upstream,
            determine_forwarded,
            describe_origin,
            gather_bugs_and_authors,
            write_dep3_patch,
            )
        (packaging_tree,
         packaging_branch) = ControlDir.open_containing_tree_or_branch(
            directory)[:2]
        self.add_cleanup(packaging_branch.lock_read().unlock)
        tree, branch = ControlDir.open_containing_tree_or_branch(location)[:2]
        self.add_cleanup(branch.lock_read().unlock)
        if revision is not None and len(revision) >= 1:
            revision_id = revision[-1].as_revision_id(branch)
        else:
            revision_id = None
        if revision_id is None:
            revision_id = branch.last_revision()
        graph = branch.repository.get_graph(packaging_branch.repository)
        if revision is not None and len(revision) == 2:
            base_revid = revision[0].as_revision_id(branch)
        else:
            base_revid = graph.find_unique_lca(
                revision_id, packaging_branch.last_revision())
        interesting_revision_ids = graph.find_unique_ancestors(
            revision_id, [base_revid])
        if len(interesting_revision_ids) == 0:
            raise BzrCommandError(gettext("No unmerged revisions"))
        (bugs, authors, last_update) = gather_bugs_and_authors(
            branch.repository, interesting_revision_ids)
        config = branch.get_config()
        description = config.get_user_option("description")
        if description is None:
            # if there's just one revision in the mainline history, use
            # that revisions commits message
            lhs_history = graph.iter_lefthand_ancestry(
                revision_id, [base_revid])
            rev = branch.repository.get_revision(next(lhs_history))
            try:
                next(lhs_history)
            except StopIteration:
                description = rev.message
        origin = describe_origin(branch, revision_id)
        if packaging_tree is None:
            packaging_tree = packaging_branch.basis_tree()
        builddeb_config = debuild_config(packaging_tree, '')
        if not no_upstream_check and builddeb_config.upstream_branch:
            upstream_branch = Branch.open(builddeb_config.upstream_branch)
            applied_upstream = determine_applied_upstream(
                upstream_branch, branch, revision_id)
            forwarded = determine_forwarded(
                upstream_branch, branch, revision_id)
        else:
            applied_upstream = None
            forwarded = None
        write_dep3_patch(
            self.outf, branch, base_revid, revision_id, bugs=bugs,
            authors=authors, origin=origin, forwarded=forwarded,
            applied_upstream=applied_upstream, description=description,
            last_update=last_update)


class LocalTree(object):

    def __init__(self, branch):
        self.branch = branch
        self._td = None

    def __enter__(self):
        try:
            return self.branch.controldir.open_workingtree()
        except (NoWorkingTree, NotLocalUrl):
            pass
        # Remote, inaccessible
        self._td = tempfile.mkdtemp()
        to_dir = self.branch.controldir.sprout(
                get_transport(self._td).base, None,
                create_tree_if_local=True,
                source_branch=self.branch)
        try:
            pristine_tar_branch = self.branch.controldir.open_branch(
                name="pristine-tar")
        except (NotBranchError, NoColocatedBranchSupport):
            pass
        else:
            pristine_tar_branch.push(to_dir.create_branch("pristine-tar"))
        return to_dir.open_workingtree()

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._td is not None:
            shutil.rmtree(self._td)
        return False


def _build_helper(
        local_tree, subpath, packaging_branch, target_dir, builder,
        guess_upstream_branch_url=False, apt=None):
    # TODO(jelmer): Integrate this with cmd_builddeb
    from .builder import (
        do_build,
        )
    from .util import (
        find_changelog,
        tree_contains_upstream_source,
        )

    (changelog, top_level) = find_changelog(
        local_tree, subpath, merge=False, max_blocks=2)

    config = debuild_config(local_tree, subpath)
    contains_upstream_source = tree_contains_upstream_source(
        local_tree, subpath)

    distiller = _get_distiller(
            local_tree, subpath, packaging_branch, build_type=None,
            config=config, changelog=changelog,
            contains_upstream_source=contains_upstream_source,
            top_level=top_level,
            guess_upstream_branch_url=guess_upstream_branch_url, apt=apt)

    return do_build(changelog.package, changelog.version, distiller,
                    local_tree, config, builder, target_dir)


DEFAULT_BUILDER = "sbuild --source --source-only-changes --no-clean-source"


class cmd_debrelease(Command):
    """Release a new version of a package.

    This will update the latest distribution in the changelog,
    build the package and upload.

    Location can be remote.
    """

    strict_opt = Option(
        'strict',
        help='Refuse to build if there are unknown files in'
        ' the working tree, --no-strict disables the check.')

    takes_args = ['location?']
    takes_options = [
        strict_opt,
        Option('skip-upload', help='Skip upload.'), builder_opt,
        ] + apt_repository_opts


    def run(self, location='.', strict=True, skip_upload=False,
            builder=DEFAULT_BUILDER, apt_repository=None,
            apt_repository_key=None):
        from .release import release
        from .util import (
            dput_changes,
            )

        branch, subpath = Branch.open_containing(location)

        if apt_repository is not None:
            from .apt_repo import RemoteApt
            apt = RemoteApt.from_string(apt_repository, apt_repository_key)
        else:
            apt = None

        # preserve whatever source format we have.
        # TODO(jelmer): Use the local tree if there is one, but check it's
        # clean.
        with LocalTree(branch) as local_tree:
            _check_tree(local_tree, subpath, strict)
            release(local_tree, subpath)

            with tempfile.TemporaryDirectory() as td:
                changes_files = _build_helper(
                        local_tree, subpath, local_tree.branch,
                        target_dir=(td if not skip_upload else None),
                        builder=builder)
                if not skip_upload:
                    try:
                        source_path = changes_files['source']
                    except KeyError:
                        raise BzrCommandError(
                            'No source package was created by build command')
                    dput_changes(source_path)
            local_tree.branch.push(branch)
