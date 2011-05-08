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

from bzrlib import diff

import time


def write_dep3_bug_line(f, bug_url, status):
    """Write a DEP-3 compatible line with a bug link.

    :param f: File-like object to write to
    :param bug_url: Bug URL
    :param status: Bug status (e.g. "fixed")
    """
    # For the moment, we only care about fixed bugs
    if status != "fixed":
        return
    if bug_url.startswith("http://bugs.debian.org/"):
        f.write("Bug-Debian: %s\n" % bug_url)
    else:
        # FIXME: Filter out Ubuntu bugs on Launchpad
        f.write("Bug: %s\n" % bug_url)


def write_dep3_patch_header(f, description=None, origin=None, forwarded=None,
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
    if origin is not None:
        f.write("Origin: %s\n" % origin)
    if forwarded is not None:
        f.write("Forwarded: %s\n" % forwarded)
    if authors is not None:
        for author in authors:
            f.write("Author: %s\n" % author)
    if bugs is not None:
        for bug_url, status in bugs:
            write_dep3_bug_line(f, bug_url, status)
    if last_update is not None:
        f.write("Last-Update: %s\n" % time.strftime("%Y-%m-%d",
            time.gmtime(last_update)))
    if applied_upstream is not None:
        f.write("Applied-Upstream: %s\n" % applied_upstream)
    if revision_id is not None:
        f.write("X-Bzr-Revision-Id: %s\n" % revision_id)
    if description is not None:
        f.write("Description: %s\n" % description)
    f.write("\n")


def gather_bugs_and_authors(repository, interesting_revision_ids):
    """Gather bug and author information from revisions.

    :param interesting_revision_ids: Iterable of revision ids to check
    :return: Tuple of bugs, authors and highest found commit timestamp
    """
    authors = set()
    bugs = set()
    last_update = None
    for rev in repository.get_revisions(interesting_revision_ids):
        last_update = max(rev.timestamp, last_update)
        authors.update(rev.get_apparent_authors())
        bugs.update(rev.iter_bugs())
    return (bugs, authors, last_update)


def write_dep3_patch(f, branch, base_revid, target_revid, description=None):
    """Write a DEP-3 compliant patch.

    :param f: File-like object to write to
    :param repository: Repository to retrieve revisions from
    :param base_revid: Base revision id
    :param target_revid: Target revisoin id
    :param description: Optional description
    """
    graph = branch.repository.get_graph()
    interesting_revision_ids = graph.find_unique_ancestors(target_revid, [base_revid])
    (bugs, authors, last_update) = gather_bugs_and_authors(branch.repository,
        interesting_revision_ids)
    if description is None:
        config = branch.get_config()
        description = config.get_user_option("description")
    if description is None and len(interesting_revision_ids) == 1:
        # if there's just one revision, use that revisions commits message
        rev = branch.repository.get_revision(iter(interesting_revision_ids).next())
        description = rev.message
    write_dep3_patch_header(f, bugs=bugs, authors=authors, last_update=last_update,
            description=description, revision_id=target_revid)
    old_tree = branch.repository.revision_tree(base_revid)
    new_tree = branch.repository.revision_tree(target_revid)
    # FIXME: Check if patch was merged upstream
    diff.show_diff_trees(old_tree, new_tree, f, old_label='old/', new_label='new/')
