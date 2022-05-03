#    upstream/branch.py -- Upstream branch source provider
#    Copyright (C) 2010-2011 Canonical Ltd.
#    Copyright (C) 2009 Jelmer Vernooij
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

from contextlib import ExitStack
from datetime import date
import os
import re
import subprocess
import tempfile
from typing import Optional, Tuple, Iterable

from debian.changelog import Version
from debmutate.versions import (
    git_snapshot_data_from_version,
    get_snapshot_revision as _get_snapshot_revision,
    debianize_upstream_version,
    upstream_version_add_revision as _upstream_version_add_revision,
    )

from .... import osutils
from ....branch import (
    Branch,
    BranchWriteLockResult,
    )
from ....errors import (
    BzrError,
    GhostRevisionsHaveNoRevno,
    InvalidRevisionId,
    NoSuchRevision,
    NoSuchTag,
    NotBranchError,
    RevisionNotPresent,
    UnsupportedOperation,
    )
from ....memorybranch import MemoryBranch
from ..repack_tarball import get_filetype, repack_tarball
from ....revision import NULL_REVISION
from ....revisionspec import RevisionSpec
from ....trace import note, mutter, warning
from ....tree import Tree

from ....revisionspec import InvalidRevisionSpec

from ..errors import (
    MultipleUpstreamTarballsNotSupported,
    )
from .. import gettext
from ..util import export_with_nested
from . import (
    UpstreamSource,
    PackageVersionNotPresent,
    new_tarball_name,
    )
from ....workingtree import (
    WorkingTree,
    )


class PreviousVersionTagMissing(BzrError):

    _fmt = ("Unable to find the tag for the "
            "previous upstream version (%(version)s) in the upstream branch: "
            "%(tag_name)s")

    def __init__(self, version, tag_name):
        super(PreviousVersionTagMissing, self).__init__(
            version=version, tag_name=tag_name)


def upstream_tag_to_version(tag_name, package=None):
    """Take a tag name and return the upstream version, or None."""
    if tag_name.endswith('-release'):
        tag_name = tag_name[:-len('-release')]
    if tag_name.startswith("release-"):
        tag_name = tag_name[len("release-"):]
    if tag_name.startswith('version-'):
        tag_name = tag_name[len("version-"):]
    if (package is not None and (
          tag_name.startswith("%s-" % package) or
          tag_name.startswith("%s_" % package))):
        tag_name = tag_name[len(package)+1:]
    if package is None and '-' in tag_name:
        (before, version) = tag_name.split('-', 1)
        if before.isalpha() and not version[0].isalpha():
            return version
    if len(tag_name) >= 2 and tag_name[0] == "v" and tag_name[1].isdigit():
        tag_name = tag_name[1:]
    if len(tag_name) >= 3 and tag_name[0] == "v" and tag_name[1] in ('/', '.') and tag_name[2].isdigit():
        tag_name = tag_name[2:]
    if all([c.isdigit() or c in (".", "~", "_") for c in tag_name]):
        return tag_name
    parts = tag_name.split('.')
    if len(parts) > 1 and all(p.isdigit() for p in parts[:-1]) and parts[-1].isalnum():
        return tag_name
    return None


def _upstream_branch_version(
        revhistory, upstream_revision, reverse_tag_dict, package,
        previous_version, add_rev):
    """Determine the version string of an upstream branch.

    The upstream version is determined from the most recent tag
    in the upstream branch. If that tag does not point at the last revision,
    the revision number is added to it (<version>+bzr<revno>).

    If there are no tags set on the upstream branch, the previous Debian
    version is used and combined with the bzr revision number
    (usually <version>+bzr<revno>).

    :param revhistory: Reverse branch revision history.
    :param reverse_tag_dict: Reverse tag dictionary (revid -> list of tags)
    :param package: Name of package.
    :param previous_version: Previous upstream version in debian changelog.
    :param add_rev: Function that can add a revision suffix to a version
        string.
    :return: Tuple with vesion of the upstream revision, and mangled
    """
    if upstream_revision == NULL_REVISION:
        # No new version to merge
        return previous_version, previous_version
    last_upstream: Optional[Tuple[Version, str, str]] = None
    try:
        for r in revhistory:
            if r in reverse_tag_dict:
                # If there is a newer version tagged in branch,
                # convert to upstream version
                # return <upstream_version>+bzr<revno>
                for tag in reverse_tag_dict[r]:
                    upstream_version = upstream_tag_to_version(
                            tag, package=package)
                    if upstream_version is not None:
                        mangled_version = debianize_upstream_version(upstream_version, package)
                        if r == upstream_revision:
                            # Well, that's simple
                            return upstream_version, mangled_version
                        if last_upstream is None or Version(last_upstream[1]) < Version(mangled_version):
                            last_upstream = (upstream_version, mangled_version, '+')
            if r == upstream_revision and last_upstream:
                # The last upstream release was after us
                last_upstream = (last_upstream[0], last_upstream[1], '~')
    except RevisionNotPresent:
        # Ghost revision somewhere on mainline.
        pass
    if last_upstream is None:
        # Well, we didn't find any releases
        if previous_version is None:
            last_upstream = ('0', '0', '+')
        else:
            # Assume we were just somewhere after the last release
            last_upstream = (previous_version, previous_version, '+')
    else:
        if previous_version is not None and Version(last_upstream[1]) < Version(previous_version):
            if '~' not in previous_version:
                warning(
                    'last found upstream version %s (%s) is lower than '
                    'previous packaged upstream version (%s)',
                    last_upstream[1], last_upstream[0], previous_version)
                last_upstream = (previous_version, previous_version, '+')
            else:
                last_upstream = (previous_version, previous_version, '~')
    upstream_version = add_rev(last_upstream[0], upstream_revision, last_upstream[2])
    mangled_upstream_version = add_rev(last_upstream[1], upstream_revision, last_upstream[2])
    return upstream_version, mangled_upstream_version


def extract_gitid(rev):
    """Extract the git SHA of a revision from a Revision object.

    :param rev: Revision object
    :return: 40 character Git SHA as bytes,
        None if this was not a git revision or
         if the git sha could not be determined (dulwich not available).
    """
    try:
        from ....git import extract_git_foreign_revid
    except ImportError:
        # No git support
        return None
    else:
        try:
            return extract_git_foreign_revid(rev)
        except InvalidRevisionId:
            return None


def extract_svn_revno(rev):
    """Extract the Subversion number of a revision from a Revision object.

    :param rev: Revision object
    :return: Revision number, None if this was not a Subversion revision or
         if the revision number could not be determined
         (bzr-svn not available).
    """
    try:
        from ...svn import extract_svn_foreign_revid
    except ImportError:
        # No svn support
        return None
    else:
        try:
            (svn_uuid, branch_path, svn_revno) = extract_svn_foreign_revid(rev)
        except InvalidRevisionId:
            return None
        else:
            return svn_revno


def upstream_version_add_revision(
        upstream_branch, version_string, revid, sep='+'):
    """Update the revision in a upstream version string.

    :param branch: Branch in which the revision can be found
    :param version_string: Original version string
    :param revid: Revision id of the revision
    :param sep: Separator to use when adding snapshot
    """
    try:
        revno = upstream_branch.revision_id_to_dotted_revno(revid)
    except GhostRevisionsHaveNoRevno:
        bzr_revno = None
    else:
        bzr_revno = '.'.join(map(str, revno))

    rev = upstream_branch.repository.get_revision(revid)
    gitid = extract_gitid(rev)
    if gitid:
        gitdate = date.fromisoformat(osutils.format_date(
            rev.timestamp, rev.timezone, date_fmt='%Y-%m-%d',
            show_offset=False))
    else:
        gitdate = None

    svn_revno = extract_svn_revno(rev)

    return _upstream_version_add_revision(
        version_string, gitid=gitid, gitdate=gitdate, bzr_revno=bzr_revno,
        svn_revno=svn_revno)


def get_snapshot_revision(upstream_version):
    """Return the upstream revision specifier if specified in the upstream
    version.

    When packaging an upstream snapshot some people use +vcsnn or ~vcsnn to
    indicate what revision number of the upstream VCS was taken for the
    snapshot. This given an upstream version number this function will return
    an identifier of the upstream revision if it appears to be a snapshot. The
    identifier is a string containing a bzr revision spec, so it can be
    transformed in to a revision.

    :param upstream_version: a string containing the upstream version number.
    :return: a string containing a revision specifier for the revision of the
        upstream branch that the snapshot was taken from, or None if it
        doesn't appear to be a snapshot.
    """
    ret = _get_snapshot_revision(upstream_version)
    if ret is None:
        return None
    (kind, rev) = ret
    if kind == 'svn':
        return "svn:%s" % rev
    elif kind == 'git':
        return "git:%s" % rev
    elif kind == 'date':
        return 'date:%s' % rev
    elif kind == 'bzr':
        return str(rev)
    else:
        raise ValueError(kind)
    return None


def upstream_branch_version(upstream_branch, upstream_revision, package,
                            previous_version=None):
    """Determine the version string for a revision in an upstream branch.

    :param upstream_branch: The upstream branch object
    :param upstream_revision: The revision id of the upstream revision
    :param package: The name of the package
    :param previous_version: The previous upstream version string (optional)
    :return: Upstream version string for `upstream_revision`.
    """
    graph = upstream_branch.repository.get_graph()
    if previous_version is not None:
        previous_revision = get_snapshot_revision(previous_version)
    else:
        previous_revision = None
    stop_revids = None
    if previous_revision is not None:
        previous_revspec = RevisionSpec.from_string(previous_revision)
        try:
            previous_revno, previous_revid = previous_revspec.in_history(
                upstream_branch)
        except InvalidRevisionSpec as e:
            # Odd - the revision mentioned in the old version doesn't exist.
            mutter('Unable to find old upstream version %s (%s): %s',
                   previous_version, previous_revision, e)
        else:
            # Trim revision history - we don't care about any revisions
            # before the revision of the previous version
            stop_revids = [previous_revid]
    revhistory = graph.iter_lefthand_ancestry(upstream_revision, stop_revids)
    return _upstream_branch_version(
            revhistory, upstream_revision,
            upstream_branch.tags.get_reverse_tag_dict(), package,
            previous_version,
            lambda version, revision, sep: upstream_version_add_revision(
                upstream_branch, version, revision, sep))


def get_export_upstream_revision(config=None, version=None):
    """Find the revision to use when exporting the upstream source.

    :param config: Config object
    :param version: Optional upstream version to find revision for, if not the
        latest.
    :return: Revision id
    """
    rev = None
    if version is not None:
        rev = get_snapshot_revision(version)
    if rev is None and config is not None:
        rev = config._get_best_opt('export-upstream-revision')
        if rev is not None and version is not None:
            rev = rev.replace('$UPSTREAM_VERSION', version)
    return rev


def guess_upstream_tag(package, version, is_snapshot: bool = False) -> Iterable[str]:
    yield version
    if package:
        for prefix in ['rust-']:
            if package.startswith(prefix):
                yield '%s-%s' % (package[len(prefix):], version)
        yield '%s-%s' % (package, version)
    if not is_snapshot:
        yield 'v%s' % version
        yield 'v.%s' % version
        yield 'release-%s' % version
        yield '%s_release' % version.replace('.', '_')
        yield '%s' % version.replace('.', '_')
        yield 'version-%s' % version
        if package:
            yield '%s-%s-release' % (package, version.replace('.', '_'))
            yield '%s-v%s' % (package, version)


def guess_upstream_revspec(package, version):
    """Guess revspecs matching an upstream version string."""
    if version.endswith('+ds'):
        version = str(version)[:-len('+ds')]
    if version.endswith('~ds'):
        version = str(version)[:-len('~ds')]
    if version.endswith('+dfsg'):
        version = str(version)[:-len('+dfsg')]
    if version.endswith('+repack'):
        version = str(version)[:-len('+repack')]
    is_snapshot = False
    if "+bzr" in version or "~bzr" in version:
        is_snapshot = True
        m = re.match(r".*[~+]bzr(\.?)(\d+).*", version)
        if m:
            yield "revno:%s" % m.group(2)
    (git_id, git_date) = git_snapshot_data_from_version(version)
    if git_id:
        is_snapshot = True
        yield "git:%s" % git_id
    if git_date:
        is_snapshot = True
        yield "date:%s" % git_date
    for tag in guess_upstream_tag(package, version, is_snapshot):
        yield 'tag:%s' % tag


class UpstreamBranchSource(UpstreamSource):
    """Upstream source that uses the upstream branch.

    :ivar upstream_branch: Branch with upstream sources
    :ivar upstream_version_map: Map from version strings to revspecs
    """

    def __init__(self, upstream_branch, upstream_revision_map=None,
                 config=None, actual_branch=None, create_dist=None,
                 other_repository=None, version_kind="auto"):
        self.upstream_branch = upstream_branch
        self._actual_branch = actual_branch or upstream_branch
        self.create_dist = create_dist
        self.config = config
        self.version_kind = version_kind
        self.other_repository = other_repository
        self.upstream_revision_map = {}
        if upstream_revision_map is not None:
            self.upstream_revision_map.update(upstream_revision_map.items())

    @classmethod
    def from_branch(cls, upstream_branch, upstream_revision_map=None,
                    config=None, local_dir=None, create_dist=None,
                    version_kind="auto"):
        """Create a new upstream branch source from a branch.

        This will optionally fetch into a local directory.
        """
        actual_branch = upstream_branch
        if local_dir is not None and not getattr(
                upstream_branch.repository, 'supports_random_access', True):
            local_repository = local_dir.find_repository()
            try:
                (last_revno,
                 last_revision) = upstream_branch.last_revision_info()
            except UnsupportedOperation:
                last_revno = None
                last_revision = upstream_branch.last_revision()
            local_repository.fetch(
                upstream_branch.repository, revision_id=last_revision)
            upstream_branch = MemoryBranch(
                local_repository, (last_revno, last_revision),
                upstream_branch.tags.get_tag_dict())
        return cls(
            upstream_branch=upstream_branch,
            upstream_revision_map=upstream_revision_map, config=config,
            actual_branch=actual_branch, create_dist=create_dist,
            version_kind=version_kind)

    def version_as_revision(self, package, version, tarballs=None):
        if version in self.upstream_revision_map:
            revspec = self.upstream_revision_map[version]
        else:
            revspec = get_export_upstream_revision(
                self.config, version=version)
        if revspec is not None:
            try:
                return RevisionSpec.from_string(
                    revspec).as_revision_id(self.upstream_branch)
            except (InvalidRevisionSpec, NoSuchTag):
                raise PackageVersionNotPresent(package, version, self)
        else:
            for revspec in guess_upstream_revspec(package, version):
                note(gettext('No upstream upstream-revision format '
                             'specified, trying %s') % revspec)
                try:
                    return RevisionSpec.from_string(
                        revspec).as_revision_id(self.upstream_branch)
                except (InvalidRevisionSpec, NoSuchTag):
                    pass
            else:
                raise PackageVersionNotPresent(package, version, self)
        raise PackageVersionNotPresent(package, version, self)

    def revision_tree(self, package, version):
        revid = self.version_as_revision(package, version)
        return self.upstream_branch.repository.revision_tree(revid)

    def version_as_revisions(self, package, version, tarballs=None):
        # FIXME: Support multiple upstream locations if there are multiple
        # components
        if tarballs is not None and tarballs.keys() != [None]:
            raise MultipleUpstreamTarballsNotSupported()
        return {None: self.version_as_revision(package, version, tarballs)}

    def has_version(self, package, version, tarballs=None):
        try:
            self.version_as_revision(package, version, tarballs)
        except PackageVersionNotPresent:
            return False
        else:
            return True

    def get_latest_snapshot_version(self, package, current_version):
        revid = self.upstream_branch.last_revision()
        version, mangled_version = self.get_version(package, current_version, revid)
        if mangled_version is not None:
            self.upstream_revision_map[mangled_version] = 'revid:%s' % revid.decode('utf-8')
        return version, mangled_version

    def get_latest_release_version(self, package, current_version):
        versions = list(self.get_recent_versions(package, current_version))
        if not versions:
            return None
        return versions[-1]

    def get_latest_version(self, package, current_version):
        if self.version_kind == "snapshot":
            return self.get_latest_snapshot_version(package, current_version)
        elif self.version_kind == "release":
            version = self.get_latest_release_version(package, current_version)
            if version is None:
                # TODO(jelmer): De-debianize current_version ?
                return current_version, current_version
            return version
        elif self.version_kind == "auto":
            version = self.get_latest_release_version(package, current_version)
            if version is None:
                note(gettext('No upstream releases found, falling back to snapshot.'))
                version = self.get_latest_snapshot_version(package, current_version)
            return version
        else:
            raise ValueError(self.version_kind)

    def get_recent_versions(
            self, package: str, since_version: Optional[Version] = None):
        versions = []
        tags = self.upstream_branch.tags.get_tag_dict()
        with self.upstream_branch.repository.lock_read():
            graph = self.upstream_branch.repository.get_graph()
            if since_version is not None:
                try:
                    since_revision = self.version_as_revision(
                        package, since_version)
                except PackageVersionNotPresent:
                    raise PreviousVersionTagMissing(package, since_version)
            else:
                since_revision = None
            for tag, revision in tags.items():
                version = upstream_tag_to_version(tag, package)
                if version is None:
                    continue
                mangled_version = debianize_upstream_version(version, package)
                self.upstream_revision_map[mangled_version] = 'tag:%s' % tag
                if since_version is not None and mangled_version <= since_version:
                    continue
                if since_revision and not graph.is_ancestor(
                        since_revision, revision):
                    continue
                versions.append((version, mangled_version))
        return sorted(versions, key=lambda v: Version(v[1]))

    def get_version(self, package, current_version, revision):
        with self.upstream_branch.lock_read():
            return upstream_branch_version(
                self.upstream_branch, revision, package, current_version)

    def fetch_tarballs(
            self, package: str, version,
            target_dir, components=None, revisions=None):
        if components is not None and components != [None]:
            # Multiple components are not supported
            raise PackageVersionNotPresent(package, version, self)
        note("Looking for upstream %s in upstream branch %s.",
             version,
             getattr(self, '_actual_branch', self.upstream_branch).user_url)
        with self.upstream_branch.lock_read():
            if revisions is not None:
                revid = revisions[None]
            else:
                revid = self.version_as_revision(package, version)
                if revid is None:
                    raise PackageVersionNotPresent(package, version, self)
            if self.other_repository is not None:
                try:
                    rev_tree = self.other_repository.revision_tree(revid)
                except NoSuchRevision:
                    rev_tree = None
            else:
                rev_tree = None
            if rev_tree is None:
                rev_tree = self.upstream_branch.repository.revision_tree(revid)
            if self.create_dist is not None:
                with tempfile.TemporaryDirectory() as td:
                    fn = self.create_dist(rev_tree, package, version, td)
                    if fn:
                        nfn = new_tarball_name(package, version, fn)
                        repack_tarball(os.path.join(td, fn), nfn, target_dir)
                        return [os.path.join(target_dir, nfn)]
            tarball_base = "%s-%s" % (package, version)
            target_filename = self._tarball_path(
                package, version, None, target_dir)
            try:
                export_with_nested(
                    rev_tree, target_filename, format='tgz', root=tarball_base)
            except UnsupportedOperation as e:
                note('Not exporting revision from upstream branch: %s', e)
                raise PackageVersionNotPresent(package, version, self)
            else:
                mutter(
                    "Exporting upstream branch revision %s to create "
                    "the tarball", revid)
        return [target_filename]

    def __repr__(self):
        return "<%s for %r>" % (
            self.__class__.__name__, self._actual_branch.base)


class LazyUpstreamBranchSource(UpstreamBranchSource):
    """Upstream branch source that defers loading the branch until it is used.
    """

    def __init__(self, upstream_branch_url, upstream_revision_map=None,
                 config=None, create_dist=None, other_repository=None,
                 version_kind="snapshot"):
        self.upstream_branch_url = upstream_branch_url
        self.version_kind = version_kind
        self._upstream_branch = None
        self.config = config
        self.create_dist = create_dist
        self.other_repository = other_repository
        if upstream_revision_map is None:
            self.upstream_revision_map = {}
        else:
            self.upstream_revision_map = upstream_revision_map

    @property
    def upstream_branch(self):
        if self._upstream_branch is None:
            if callable(self.upstream_branch_url):
                self.upstream_branch_url = self.upstream_branch_url()
            self._upstream_branch = Branch.open(self.upstream_branch_url)
        return self._upstream_branch

    def __repr__(self):
        return "<%s for %r>" % (
            self.__class__.__name__, self.upstream_branch_url)


class DistCommandFailed(BzrError):

    _fmt = "Dist command failed to produce a tarball: %(error)s"

    def __init__(self, error, kind=None):
        super(DistCommandFailed, self).__init__(error=error, kind=kind)


def _dupe_vcs_tree(tree, directory):
    with tree.lock_read():
        if isinstance(tree, WorkingTree):
            tree = tree.basis_tree()
    result = tree._repository.controldir.sprout(
        directory, create_tree_if_local=True,
        revision_id=tree.get_revision_id()
    )
    if not result.has_workingtree():
        raise AssertionError
    # Copy parent location - some scripts need this
    if isinstance(tree, WorkingTree):
        parent = tree.branch.get_parent()
    else:
        try:
            parent = tree._repository.controldir.open_branch().get_parent()
        except NotBranchError:
            parent = None
    if parent:
        result.open_branch().set_parent(parent)


def run_dist_command(
        rev_tree: Tree, package: Optional[str], version: Version, target_dir: str,
        dist_command: str, include_controldir: bool = False) -> bool:

    def _run_and_interpret(command, env, dir):
        try:
            subprocess.check_call(command, env=env, cwd=dir, shell=True)
        except subprocess.CalledProcessError as e:
            if e.returncode == 2:
                raise NotImplementedError
            if e.returncode == 137:
                raise MemoryError(str(e))
            try:
                import json
                with open(env['DIST_RESULT'], 'r') as f:
                    result = json.load(f)
                raise DistCommandFailed(
                    result['description'], result['result_code'])
            except FileNotFoundError:
                raise DistCommandFailed(str(e))

    with ExitStack() as es:
        td = es.enter_context(tempfile.TemporaryDirectory())
        if package:
            package_dir = os.path.join(td, package)
        else:
            package_dir = os.path.join(td, 'package')
        env = dict(os.environ.items())
        if package:
            env['PACKAGE'] = package
        env['VERSION'] = version
        env['DIST_RESULT'] = os.path.join(td, 'dist.json')
        note('Running dist command: %s', dist_command)
        if include_controldir:
            _dupe_vcs_tree(rev_tree, package_dir)
        else:
            export_with_nested(rev_tree, package_dir, format='dir')
        existing_files = os.listdir(package_dir)
        try:
            _run_and_interpret(dist_command, env, package_dir)
        except NotImplementedError:
            return None
        except DistCommandFailed as e:
            # Retry with the control directory
            if (e.kind == 'vcs-control-directory-needed' and
                    not include_controldir):
                osutils.rmtree(package_dir)
                _dupe_vcs_tree(rev_tree, package_dir)
                existing_files = os.listdir(package_dir)
                _run_and_interpret(dist_command, env, package_dir)
            else:
                raise
        new_files = os.listdir(package_dir)
        diff_files = set(new_files) - set(existing_files)
        diff = [n for n in diff_files if get_filetype(n) is not None]
        if len(diff) == 1:
            note('Found tarball %s in package directory.', diff[0])
            os.rename(
                os.path.join(package_dir, diff[0]),
                os.path.join(target_dir, diff[0]))
            return diff[0]
        if 'dist' in diff_files:
            for entry in os.scandir(os.path.join(package_dir, 'dist')):
                if get_filetype(entry.name) is not None:
                    note('Found tarball %s in dist directory.', entry.name)
                    os.rename(entry.path, os.path.join(target_dir, entry.name))
                    return entry.name
            note('No tarballs found in dist directory.')
        diff = set(os.listdir(td)) - set([os.path.basename(package_dir)])
        if len(diff) == 1:
            fn = diff.pop()
            note('Found tarball %s in parent directory.', fn)
            os.rename(
                os.path.join(td, fn),
                os.path.join(target_dir, fn))
            return fn
    raise DistCommandFailed('no tarball created')
