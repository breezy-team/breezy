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

import re

from .... import osutils
from ....branch import (
    Branch,
    BranchWriteLockResult,
    )
from ....bzr import branch as bzr_branch
from ....errors import (
    InvalidRevisionId,
    InvalidRevisionSpec,
    NoSuchRevision,
    NoSuchTag,
    UnsupportedOperation,
    )
from ....lock import _RelockDebugMixin, LogicalLockResult
from ....revision import NULL_REVISION
from ....revisionspec import RevisionSpec
from ....sixish import text_type
from ....trace import note

from ..errors import (
    MultipleUpstreamTarballsNotSupported,
    PackageVersionNotPresent,
    )
from .. import gettext
from . import UpstreamSource
from ....export import (
    export,
    )


def upstream_tag_to_version(tag_name, package=None):
    """Take a tag name and return the upstream version, or None."""
    assert isinstance(tag_name, text_type)
    if (package is not None and (
          tag_name.startswith("%s-" % package) or
          tag_name.startswith("%s_" % package))):
        return tag_name[len(package)+1:]
    if tag_name.startswith("release-"):
        return tag_name[len("release-"):]
    if tag_name[0] == "v" and tag_name[1].isdigit():
        return tag_name[1:]
    if all([c.isdigit() or c in (".", "~") for c in tag_name]):
        return tag_name
    return None


def _upstream_branch_version(revhistory, upstream_revision, reverse_tag_dict, package,
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
    :param add_rev: Function that can add a revision suffix to a version string.
    :return: Name of the upstream revision.
    """
    if upstream_revision == NULL_REVISION:
        # No new version to merge
        return previous_version
    for r in revhistory:
        if r in reverse_tag_dict:
            # If there is a newer version tagged in branch,
            # convert to upstream version
            # return <upstream_version>+bzr<revno>
            for tag in reverse_tag_dict[r]:
                upstream_version = upstream_tag_to_version(
                        tag, package=package)
                if upstream_version is not None:
                    if r != upstream_revision:
                        upstream_version = add_rev(
                            str(upstream_version), upstream_revision)
                    return upstream_version
    return add_rev(str(previous_version), upstream_revision)


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
         if the revision number could not be determined (bzr-svn not available).
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


def upstream_version_add_revision(upstream_branch, version_string, revid):
    """Update the revision in a upstream version string.

    :param branch: Branch in which the revision can be found
    :param version_string: Original version string
    :param revid: Revision id of the revision
    """
    revno = upstream_branch.revision_id_to_dotted_revno(revid)
    revno_str = '.'.join(map(str, revno))

    m = re.match(r"^(.*)([\+~])bzr(\d+)$", version_string)
    if m:
        return "%s%sbzr%s" % (m.group(1), m.group(2), revno_str)

    rev = upstream_branch.repository.get_revision(revid)
    gitid = extract_gitid(rev)
    if gitid:
        gitid = gitid[:7].decode('ascii')
        gitdate = osutils.format_date(
            rev.timestamp, rev.timezone, date_fmt='%Y%m%d', show_offset=False)

    m = re.match(r"^(.*)([\+~])git(\d{8})\.([a-f0-9]{7})$", version_string)
    if m and gitid:
        return "%s%sgit%s.%s" % (m.group(1), m.group(2), gitdate, gitid)

    m = re.match(r"^(.*)([\+~])git(\d{8})\.(\d+)\.([a-f0-9]{7})$", version_string)
    if m and gitid:
        if gitdate == m.group(3):
            snapshot = int(m.group(4)) + 1
        else:
            snapshot = 0
        return "%s%sgit%s.%d.%s" % (
            m.group(1), m.group(2), gitdate, snapshot, gitid)

    m = re.match(r"^(.*)([\+~])git(\d{8})$", version_string)
    if m and gitid:
        return "%s%sgit%s" % (m.group(1), m.group(2), gitdate)

    svn_revno = extract_svn_revno(rev)

    m = re.match(r"^(.*)([\+~])svn(\d+)$", version_string)
    # FIXME: Raise error if +svn/~svn is present and svn_revno is not set?
    if m and svn_revno:
        return "%s%ssvn%d" % (m.group(1), m.group(2), svn_revno)

    if svn_revno:
        return "%s+svn%d" % (version_string, svn_revno)
    elif gitid:
        return "%s+git%s.%s" % (version_string, gitdate, gitid)
    else:
        return "%s+bzr%s" % (version_string, revno_str)


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
    match = re.search("(?:~|\\+)bzr([0-9]+)$", upstream_version)
    if match is not None:
        return match.groups()[0]
    match = re.search("(?:~|\\+)svn([0-9]+)$", upstream_version)
    if match is not None:
        return "svn:%s" % match.groups()[0]
    return None


def upstream_branch_version(upstream_branch, upstream_revision, package,
        previous_version):
    """Determine the version string for a revision in an upstream branch.

    :param upstream_branch: The upstream branch object
    :param upstream_revision: The revision id of the upstream revision
    :param package: The name of the package
    :param previous_version: The previous upstream version string
    :return: Upstream version string for `upstream_revision`.
    """
    graph = upstream_branch.repository.get_graph()
    previous_revision = get_snapshot_revision(previous_version)
    if previous_revision is not None:
        previous_revspec = RevisionSpec.from_string(previous_revision)
        previous_revno, previous_revid = previous_revspec.in_history(upstream_branch)
        # Trim revision history - we don't care about any revisions
        # before the revision of the previous version
        stop_revids = [previous_revid]
    else:
        stop_revids = None
    revhistory = graph.iter_lefthand_ancestry(upstream_revision, stop_revids)
    return _upstream_branch_version(
            revhistory, upstream_revision,
            upstream_branch.tags.get_reverse_tag_dict(), package,
            previous_version,
            lambda version, revision: upstream_version_add_revision(
                upstream_branch, version, revision))


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


def guess_upstream_revspec(package, version):
    """Guess revspecs matching an upstream version string."""
    if "+bzr" in version or "~bzr" in version:
        yield "revno:%s" % re.match(".*[~+]bzr(\\d+).*", version).group(1)
    if "+git" in version or "~git" in version:
        m = re.match(".*[~+]git([0-9]{8})\\.([0-9a-f]{7}).*", version)
        if m:
            yield "git:%s" % m.group(2)
        else:
            m = re.match(".*[~+]git([0-9]{4})([0-9]{2})([0-9]{2}).*", version)
            if m:
                yield "date:%s-%s-%s" % (m.group(1), m.group(2), m.group(3))

    yield 'tag:%s' % version
    yield 'tag:%s-%s' % (package, version)
    yield 'tag:v%s' % version


# TODO(jelmer): Move this into breezy.
class MinimalMemoryBranch(bzr_branch.Branch, _RelockDebugMixin):

    def __init__(self, repository, last_revision_info, tags):
        from ....tag import DisabledTags, MemoryTags
        self.repository = repository
        self._last_revision_info = last_revision_info
        self._revision_history_cache = None
        if tags is not None:
            self.tags = MemoryTags(tags)
        else:
            self.tags = DisabledTags(self)
        self._partial_revision_history_cache = []
        self._last_revision_info_cache = None
        self._revision_id_to_revno_cache = None
        self._partial_revision_id_to_revno_cache = {}
        self._partial_revision_history_cache = []

    def lock_read(self):
        self.repository.lock_read()
        return LogicalLockResult(self.unlock)

    def lock_write(self, token=None):
        self.repository.lock_write()
        return BranchWriteLockResult(self.unlock, None)

    def unlock(self):
        self.repository.unlock()

    def last_revision_info(self):
        return self._last_revision_info

    def _gen_revision_history(self):
        """Generate the revision history from last revision
        """
        last_revno, last_revision = self.last_revision_info()
        self._extend_partial_history()
        return list(reversed(self._partial_revision_history_cache))

    def get_rev_id(self, revno, history=None):
        """Find the revision id of the specified revno."""
        with self.lock_read():
            if revno == 0:
                return NULL_REVISION
            last_revno, last_revid = self.last_revision_info()
            if revno == last_revno:
                return last_revid
            if last_revno is None:
                self._extend_partial_history()
                return self._partial_revision_history_cache[
                        len(self._partial_revision_history_cache) - revno]
            else:
                if revno <= 0 or revno > last_revno:
                    raise NoSuchRevision(self, revno)
                distance_from_last = last_revno - revno
                if len(self._partial_revision_history_cache) <= distance_from_last:
                    self._extend_partial_history(distance_from_last)
                return self._partial_revision_history_cache[distance_from_last]


class UpstreamBranchSource(UpstreamSource):
    """Upstream source that uses the upstream branch.

    :ivar upstream_branch: Branch with upstream sources
    :ivar upstream_version_map: Map from version strings to revspecs
    """

    def __init__(self, upstream_branch, upstream_revision_map=None,
                 config=None, actual_branch=None):
        self.upstream_branch = upstream_branch
        self._actual_branch = actual_branch or upstream_branch
        self.config = config
        if upstream_revision_map is None:
            self.upstream_revision_map = {}
        else:
            self.upstream_revision_map = upstream_revision_map

    @classmethod
    def from_branch(cls, upstream_branch, upstream_revision_map=None,
                    config=None, local_dir=None):
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
            upstream_branch = MinimalMemoryBranch(
                local_repository, (last_revno, last_revision),
                upstream_branch.tags.get_tag_dict())
        return cls(
            upstream_branch=upstream_branch,
            upstream_revision_map=upstream_revision_map, config=config,
            actual_branch=actual_branch)

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

    def version_as_revisions(self, package, version, tarballs=None):
        # FIXME: Support multiple upstream locations if there are multiple
        # components
        if tarballs is not None and tarballs.keys() != [None]:
            raise MultipleUpstreamTarballsNotSupported()
        return {None: self.version_as_revision(package, version, tarballs)}

    def get_latest_version(self, package, current_version):
        return self.get_version(
            package, current_version, self.upstream_branch.last_revision())

    def get_version(self, package, current_version, revision):
        with self.upstream_branch.lock_read():
            return upstream_branch_version(
                self.upstream_branch, revision, package, current_version)

    def fetch_tarballs(self, package, version, target_dir, components=None,
                       revisions=None):
        if components is not None and components != [None]:
            # Multiple components are not supported
            raise PackageVersionNotPresent(package, version, self)
        with self.upstream_branch.lock_read():
            if revisions is not None:
                revid = revisions[None]
            else:
                revid = self.version_as_revision(package, version)
                if revid is None:
                    raise PackageVersionNotPresent(package, version, self)
            note("Exporting upstream branch revision %s to create the tarball",
                 revid)
            target_filename = self._tarball_path(
                package, version, None, target_dir)
            tarball_base = "%s-%s" % (package, version)
            rev_tree = self.upstream_branch.repository.revision_tree(revid)
            export(rev_tree, target_filename, 'tgz', tarball_base)
        return [target_filename]

    def __repr__(self):
        return "<%s for %r>" % (
            self.__class__.__name__, self._actual_branch.base)


class LazyUpstreamBranchSource(UpstreamBranchSource):
    """Upstream branch source that defers loading the branch until it is used.
    """

    def __init__(self, upstream_branch_url, upstream_revision_map=None,
                 config=None):
        self.upstream_branch_url = upstream_branch_url
        self._upstream_branch = None
        self.config = config
        if upstream_revision_map is None:
            self.upstream_revision_map = {}
        else:
            self.upstream_revision_map = upstream_revision_map

    @property
    def upstream_branch(self):
        if self._upstream_branch is None:
            self._upstream_branch = Branch.open(self.upstream_branch_url)
        return self._upstream_branch

    def __repr__(self):
        return "<%s for %r>" % (
            self.__class__.__name__, self.upstream_branch_url)
