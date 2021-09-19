#    dep3.py -- DEP-3 compatible patch formatting
#    Copyright (C) 2011 Canonical Ltd.
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

"""DEP-3 style patch formatting."""

from email.message import Message

from ... import (
    diff,
    errors,
    )
from breezy.foreign import foreign_vcs_registry

from io import BytesIO

import time


def write_dep3_bug_line(message, bug_url, status):
    """Write a DEP-3 compatible line with a bug link.

    :param message: Message object to udpate
    :param bug_url: Bug URL
    :param status: Bug status (e.g. "fixed")
    """
    # For the moment, we only care about fixed bugs
    if status != "fixed":
        return
    if bug_url.startswith("http://bugs.debian.org/"):
        message.add_header("Bug-Debian", bug_url)
    else:
        # FIXME: Filter out Ubuntu bugs on Launchpad
        message.add_header("Bug", bug_url)


def write_dep3_patch_header(
        f, description=None, origin=None, forwarded=None,
        bugs=None, authors=None, revision_id=None, last_update=None,
        applied_upstream=None):
    """Write a DEP3 patch header.

    :param f: File-like object to write to
    :param description: Description of the patch
    :param origin: Single line describing the origin of the patch
    :param forwarded: Single line describing whether and how the patch was
        forwarded
    :param bugs: Set of bugs fixed in this patch
    :param authors: Authors of the patch
    :param revision_id: Relevant bzr revision id
    :param last_update: Last update timestamp
    :param applied_upstream: If the patch is applied upstream,
        an informal string describing where it was merged
    """
    header = Message()
    if description is not None:
        description = description.strip("\n")
        description = description.replace("\n\n", "\n.\n")
        description = description.replace("\n", "\n ")
        header["Description"] = description
    if origin is not None:
        header.add_header("Origin", origin)
    if forwarded is not None:
        header.add_header("Forwarded", forwarded)
    if authors is not None:
        for author in authors:
            header.add_header("Author", author)
    if bugs is not None:
        for bug_url, status in bugs:
            write_dep3_bug_line(header, bug_url, status)
    if last_update is not None:
        header.add_header(
            "Last-Update",
            time.strftime("%Y-%m-%d", time.gmtime(last_update)))
    if applied_upstream is not None:
        header.add_header("Applied-Upstream", applied_upstream)
    if revision_id is not None:
        try:
            (foreign_revid, mapping) = foreign_vcs_registry.parse_revision_id(
                    revision_id)
        except errors.InvalidRevisionId:
            header.add_header("X-Bzr-Revision-Id", revision_id.decode('utf-8'))
        else:
            if mapping.vcs.abbreviation == "git":
                header.add_header("X-Git-Commit", foreign_revid.decode('utf-8'))
    f.write(str(header))


def gather_bugs_and_authors(repository, interesting_revision_ids):
    """Gather bug and author information from revisions.

    :param interesting_revision_ids: Iterable of revision ids to check
    :return: Tuple of bugs, authors and highest found commit timestamp
    """
    authors = set()
    bugs = set()
    last_update = -0.0
    for rev in repository.get_revisions(interesting_revision_ids):
        last_update = max(rev.timestamp, last_update)
        authors.update(rev.get_apparent_authors())
        bugs.update(rev.iter_bugs())
    if last_update == -0.0:
        last_update = None
    return (bugs, authors, last_update)


def determine_applied_upstream(
        upstream_branch, feature_branch, feature_revid=None):
    """Check if a particular revision has been merged upstream.

    :param upstream_branch: Upstream branch object
    :param feature_branch: Feature branch
    :param feature_revid: Revision id in feature branch to check,
        defaults to feature_branch tip.
    :return: String that can be used for Applied-Upstream field
    """
    if feature_revid is None:
        feature_revid = feature_branch.last_revision()
    upstream_graph = feature_branch.repository.get_graph(
        upstream_branch.repository)
    merger = upstream_graph.find_lefthand_merger(
        feature_revid, upstream_branch.last_revision())
    if merger is not None:
        try:
            (foreign_revid, mapping) = foreign_vcs_registry.parse_revision_id(
                merger)
        except errors.InvalidRevisionId:
            pass
        else:
            if mapping.vcs.abbreviation == 'git':
                return "merged in commit %s" % (
                    foreign_revid.decode('ascii')[:7], )
        return "merged in revision %s" % (".".join(
            str(x)
            for x in upstream_branch.revision_id_to_dotted_revno(merger)), )
    else:
        return "no"


def determine_forwarded(upstream_branch, feature_branch, feature_revid):
    """See if a branch has been forwarded to upstream.

    :param upstream_branch: Upstream branch object
    :param feature_branch: Feature branch
    :param feature_revid: Revision id in feature branch to check
    :return: String that can be used for Applied-Upstream field
    """
    # FIXME: Check for Launchpad merge proposals from feature_branch (or its
    # public_branch) to upstream_branch

    # Are there any other ways to see that a patch has been forwarded upstream?
    return None


def describe_origin(branch, revid):
    """Describe a tree for use in the origin field.

    :param branch: Branch to retrieve the revision from
    :param revid: Revision id
    """
    public_branch_url = branch.get_public_branch()
    if public_branch_url is not None:
        try:
            (foreign_revid, mapping) = foreign_vcs_registry.parse_revision_id(
                revid)
        except errors.InvalidRevisionId:
            pass
        else:
            if mapping.vcs.abbreviation == 'git':
                return "commit, %s, commit: %s" % (
                    public_branch_url, foreign_revid.decode('ascii')[:7], )
        return "commit, %s, revision: %s" % (
            public_branch_url, ".".join(
                str(x) for x in branch.revision_id_to_dotted_revno(revid)), )
    else:
        try:
            (foreign_revid, mapping) = foreign_vcs_registry.parse_revision_id(
                revid)
        except errors.InvalidRevisionId:
            pass
        else:
            if mapping.vcs.abbreviation == 'git':
                return "commit: %s" % (foreign_revid.decode('ascii')[:7], )
        return "commit, revision id: %s" % revid.decode('utf-8')


def write_dep3_patch(f, branch, base_revid, target_revid, description=None,
                     origin=None, forwarded=None, applied_upstream=None,
                     bugs=None, authors=None, last_update=None):
    """Write a DEP-3 compliant patch.

    :param f: File-like object to write to
    :param repository: Repository to retrieve revisions from
    :param base_revid: Base revision id
    :param target_revid: Target revision id
    :param description: Optional description
    :param forwarded: Optional information on if/how the patch was forwarded
    :param applied_upstream: Optional information on how whether the patch
        was merged upstream
    :param bugs: Sequence of bug reports related to this patch
    :param authors: Sequence of authors of this patch
    :param last_update: Timestamp for last time this patch was updated
    """
    write_dep3_patch_header(
        f, bugs=bugs, authors=authors,
        last_update=last_update, description=description,
        revision_id=target_revid, origin=origin,
        applied_upstream=applied_upstream, forwarded=forwarded)
    old_tree = branch.repository.revision_tree(base_revid)
    new_tree = branch.repository.revision_tree(target_revid)
    bf = BytesIO()
    diff.show_diff_trees(old_tree, new_tree, bf, old_label='old/',
                         new_label='new/')
    # TODO(jelmer)
    f.write(bf.getvalue().decode('utf-8'))
