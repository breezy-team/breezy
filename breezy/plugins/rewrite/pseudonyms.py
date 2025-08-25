# Copyright (C) 2009 by Jelmer Vernooij <jelmer@samba.org>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Revision pseudonyms."""

from collections import defaultdict

from breezy import errors, foreign, ui, urlutils


def parse_git_svn_id(text):
    """Parse a git svn id string.

    :param text: git svn id
    :return: URL, revision number, uuid
    """
    (head, uuid) = text.rsplit(" ", 1)
    (full_url, rev) = head.rsplit("@", 1)
    return (full_url.encode("utf-8"), int(rev), uuid.encode("utf-8"))


class SubversionBranchUrlFinder:
    """Helper class for finding Subversion branch paths from URLs.

    This class maintains a cache of Subversion repository roots to avoid
    repeated network requests when determining branch paths.
    """

    def __init__(self):
        """Initialize the URL finder with an empty cache."""
        self._roots = defaultdict(set)

    def find_root(self, uuid, url):
        """Find the root URL of a Subversion repository.

        Args:
            uuid: The UUID of the Subversion repository.
            url: A URL within the repository.

        Returns:
            str or None: The repository root URL, or None if subvertpy
                is not available.
        """
        for root in self._roots[uuid]:
            if url.startswith(root):
                return root
        try:
            from subvertpy.ra import RemoteAccess
        except ModuleNotFoundError:
            return None
        c = RemoteAccess(url)
        root = c.get_repos_root()
        self._roots[uuid].add(root)
        return root

    def find_branch_path(self, uuid, url):
        """Find the branch path within a Subversion repository.

        Args:
            uuid: The UUID of the Subversion repository.
            url: A URL within the repository.

        Returns:
            str or None: The branch path relative to the repository root,
                or None if the root cannot be determined.

        Raises:
            AssertionError: If the URL doesn't start with the repository root.
        """
        root = self.find_root(uuid, url)
        if root is None:
            return None
        if not url.startswith(root):
            raise AssertionError(f"URL {url} does not start with root {root}")
        return url[len(root) :].strip("/")


svn_branch_path_finder = SubversionBranchUrlFinder()


def _extract_converted_from_revid(rev):
    """Extract foreign revision IDs from the 'converted-from' property.

    Args:
        rev: Revision object to extract from.

    Yields:
        tuple: (kind, serialized_foreign_revid) pairs for each conversion.
    """
    if "converted-from" not in rev.properties:
        return

    for line in rev.properties.get("converted-from", "").splitlines():
        (kind, serialized_foreign_revid) = line.split(" ", 1)
        yield (kind, serialized_foreign_revid)


def _extract_cscvs(rev):
    """Extract Subversion revision ID from older-style launchpad-cscvs import.

    Args:
        rev: Revision object to extract from.

    Yields:
        tuple: ('svn', serialized_foreign_revid) for cscvs conversions.
    """
    if "cscvs-svn-branch-path" not in rev.properties:
        return
    yield (
        "svn",
        "{}:{}:{}".format(
            rev.properties["cscvs-svn-repository-uuid"],
            rev.properties["cscvs-svn-revision-number"],
            urlutils.quote(rev.properties["cscvs-svn-branch-path"].strip("/")),
        ),
    )


def _extract_git_svn_id(rev):
    """Extract Subversion revision ID from git-svn-id property.

    Args:
        rev: Revision object to extract from.

    Yields:
        tuple: ('svn', serialized_foreign_revid) for git-svn conversions.
    """
    if "git-svn-id" not in rev.properties:
        return
    (full_url, revnum, uuid) = parse_git_svn_id(rev.properties["git-svn-id"])
    branch_path = svn_branch_path_finder.find_branch_path(uuid, full_url)
    if branch_path is not None:
        yield ("svn", f"{uuid}:{revnum}:{urlutils.quote(branch_path)}")


def _extract_foreign_revision(rev):
    """Extract foreign revision ID from a foreign revision object.

    Args:
        rev: Revision object to extract from.

    Yields:
        tuple: (vcs_abbreviation, serialized_foreign_revid) for foreign revisions.
    """
    # Perhaps 'rev' is a foreign revision ?
    if getattr(rev, "foreign_revid", None) is not None:
        yield ("svn", rev.mapping.vcs.serialize_foreign_revid(rev.foreign_revid))


def _extract_foreign_revid(rev):
    """Extract foreign revision ID by parsing the revision ID.

    Args:
        rev: Revision object to extract from.

    Yields:
        tuple: (vcs_abbreviation, serialized_foreign_revid) for foreign revision IDs.
    """
    # Try parsing the revision id
    try:
        foreign_revid, mapping = foreign.foreign_vcs_registry.parse_revision_id(
            rev.revision_id
        )
    except errors.InvalidRevisionId:
        pass
    else:
        yield (
            mapping.vcs.abbreviation,
            mapping.vcs.serialize_foreign_revid(foreign_revid),
        )


def _extract_debian_md5sum(rev):
    """Extract Debian MD5 sum from revision properties.

    Args:
        rev: Revision object to extract from.

    Yields:
        tuple: ('debian-md5sum', md5sum) for Debian package revisions.
    """
    if "deb-md5" in rev.properties:
        yield ("debian-md5sum", rev.properties["deb-md5"])


_foreign_revid_extractors = [
    _extract_converted_from_revid,
    _extract_cscvs,
    _extract_git_svn_id,
    _extract_foreign_revision,
    _extract_foreign_revid,
    _extract_debian_md5sum,
]


def extract_foreign_revids(rev):
    """Find ids of semi-equivalent revisions in foreign VCS'es.

    :param: Bazaar revision object
    :return: Set with semi-equivalent revisions.
    """
    ret = set()
    for extractor in _foreign_revid_extractors:
        ret.update(extractor(rev))
    return ret


def find_pseudonyms(repository, revids):
    """Find revisions that are pseudonyms of each other.

    :param repository: Repository object
    :param revids: Sequence of revision ids to check
    :return: Iterable over sets of pseudonyms
    """
    # Where have foreign revids ended up?
    conversions = defaultdict(set)
    # What are native revids conversions of?
    conversion_of = defaultdict(set)
    revs = repository.get_revisions(revids)
    pb = ui.ui_factory.nested_progress_bar()
    try:
        for i, rev in enumerate(revs):
            pb.update("finding pseudonyms", i, len(revs))
            for foreign_revid in extract_foreign_revids(rev):
                conversion_of[rev.revision_id].add(foreign_revid)
                conversions[foreign_revid].add(rev.revision_id)
    finally:
        pb.finished()
    for foreign_revid in conversions.keys():
        ret = set()
        check = set(conversions[foreign_revid])
        while check:
            x = check.pop()
            extra = set()
            for frevid in conversion_of[x]:
                extra.update(conversions[frevid])
                del conversions[frevid]
            del conversion_of[x]
            check.update(extra)
            ret.add(x)
        if len(ret) > 1:
            yield ret


def pseudonyms_as_dict(l):
    """Convert an iterable over pseudonyms to a dictionary.

    :param l: Iterable over sets of pseudonyms
    :return: Dictionary with pseudonyms for each revid.
    """
    ret = {}
    for pns in l:
        for pn in pns:
            ret[pn] = pns - {pn}
    return ret


def generate_rebase_map_from_pseudonyms(pseudonym_dict, existing, desired):
    """Create a rebase map from pseudonyms and existing/desired ancestry.

    :param pseudonym_dict: Dictionary with pseudonym as returned by
        pseudonyms_as_dict()
    :param existing: Existing ancestry, might need to be rebased
    :param desired: Desired ancestry
    :return: rebase map, as dictionary
    """
    rebase_map = {}
    for revid in existing:
        for pn in pseudonym_dict.get(revid, []):
            if pn in desired:
                rebase_map[revid] = pn
    return rebase_map
