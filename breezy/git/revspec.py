# Copyright (C) 2009-2018 Jelmer Vernooij <jelmer@jelmer.uk>

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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Custom revision specifier for Subversion."""

# Please note that imports are delayed as much as possible here since
# if DWIM revspecs are supported this module is imported by __init__.py.

from ..errors import InvalidRevisionId
from ..revision import NULL_REVISION
from ..revisionspec import InvalidRevisionSpec, RevisionInfo, RevisionSpec


def valid_git_sha1(hex):
    """Check if `hex` is a validly formatted Git SHA1.

    :param hex: Hex string to validate
    :return: Boolean
    """
    try:
        int(hex, 16)
    except ValueError:
        return False
    else:
        return True


class RevisionSpec_git(RevisionSpec):
    """Selects a revision using a Git commit SHA1."""

    help_txt = """Selects a revision using a Git commit SHA1.

    Selects a revision using a Git commit SHA1, short or long.

    This works for both native Git repositories and Git revisions
    imported into Bazaar repositories.
    """

    prefix = "git:"
    wants_revision_history = False

    def _lookup_git_sha1(self, branch, sha1):
        from .errors import GitSmartRemoteNotSupported
        from .mapping import default_mapping

        bzr_revid = getattr(
            branch.repository,
            "lookup_foreign_revision_id",
            default_mapping.revision_id_foreign_to_bzr,
        )(sha1)
        try:
            if branch.repository.has_revision(bzr_revid):
                return bzr_revid
        except GitSmartRemoteNotSupported:
            return bzr_revid
        raise InvalidRevisionSpec(self.user_spec, branch)

    def __nonzero__(self):
        """Check if this revision spec resolves to a valid revision.

        Returns:
            bool: True if the revision spec is valid and not null, False otherwise.
        """
        # The default implementation uses branch.repository.has_revision()
        if self.rev_id is None:
            return False
        return self.rev_id != NULL_REVISION

    def _find_short_git_sha1(self, branch, sha1):
        from .mapping import ForeignGit, mapping_registry

        parse_revid = getattr(
            branch.repository,
            "lookup_bzr_revision_id",
            mapping_registry.parse_revision_id,
        )

        def matches_revid(revid):
            if revid == NULL_REVISION:
                return False
            try:
                foreign_revid, mapping = parse_revid(revid)
            except InvalidRevisionId:
                return False
            if not isinstance(mapping.vcs, ForeignGit):
                return False
            return foreign_revid.startswith(sha1)

        with branch.repository.lock_read():
            graph = branch.repository.get_graph()
            last_revid = branch.last_revision()
            if matches_revid(last_revid):
                return last_revid
            for revid, _ in graph.iter_ancestry([last_revid]):
                if matches_revid(revid):
                    return revid
            raise InvalidRevisionSpec(self.user_spec, branch)

    def _as_revision_id(self, context_branch):
        loc = self.spec.find(":")
        git_sha1 = self.spec[loc + 1 :].encode("utf-8")
        if len(git_sha1) > 40 or len(git_sha1) < 4 or not valid_git_sha1(git_sha1):
            raise InvalidRevisionSpec(self.user_spec, context_branch)
        from . import lazy_check_versions

        lazy_check_versions()
        if len(git_sha1) == 40:
            return self._lookup_git_sha1(context_branch, git_sha1)
        else:
            return self._find_short_git_sha1(context_branch, git_sha1)

    def _match_on(self, branch, revs):
        revid = self._as_revision_id(branch)
        return RevisionInfo.from_revision_id(branch, revid)

    def needs_branch(self):
        """Check if this revision spec requires a branch.

        Returns:
            bool: Always returns True as Git SHA1 lookups require a branch.
        """
        return True

    def get_branch(self):
        """Get the branch associated with this revision spec.

        Returns:
            None: Git revision specs don't specify a branch.
        """
        return None
