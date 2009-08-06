#    merge_package.py -- The plugin for bzr
#    Copyright (C) 2009 Canonical Ltd.
#
#    :Author: Muharem Hrnjadovic <muharem@ubuntu.com>
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

import re

from debian_bundle.changelog import Version

from bzrlib import builtins, errors, merge
from bzrlib.branch import Branch
from bzrlib.commands import Command

from bzrlib.plugins.builddeb.import_dsc import DistributionBranch


class WrongBranchType(errors.BzrError):
    _fmt = "The merge target is not a packaging branch."


def _read_file(branch, path):
    """Get content of file for given `branch` and `path."""
    try:
        tree = branch.basis_tree()
        tree.lock_read()
        content = tree.get_file_text(tree.path2id(path))
        tree.unlock()
    except errors.NoSuchId:
        raise WrongBranchType()

    return content

def _latest_version(branch):
    """Version the most recent source package upload in given `branch`."""
    upload_version = None
    changelog = _read_file(branch, "debian/changelog")

    for line in changelog.splitlines():
        # Look for the top-level changelog stanza, extract the
        # upload version from it and break on success.
        match = re.search('^.+\(([^)]+)\).*$', line)
        if match is not None:
            (upload_version,) = match.groups(1)
            break

    return Version(upload_version)

def upstream_branches_diverged(source, target):
    """Do the upstream branches of the merge source and target diverge?

    The upstream branches will not have diverged if
        * they are identical
        * one is a proper subtree of the other
    """
    try:
        # print "Source : %s\n" % source
        # print "Target : %s\n" % target
        source.lock_read()
        target.lock_read()

        # Get the revision IDs for the most recent source and target
        # upstream versions respectively.
        upstream_revs = []
        for branch in (source, target):
            db = DistributionBranch(branch, branch)
            version = _latest_version(branch)
            # print "Version : %s, %s\n" % (version, version.upstream_version)
            upstream_revs.append(
                db.revid_of_upstream_version_from_branch(
                    version.upstream_version))

        graph = source.repository.get_graph(target.repository)
        # Get the number of heads for the combined upstream branches
        # graph.
        # print upstream_revs
        heads = graph.heads(upstream_revs)
    finally:
        source.unlock()
        target.unlock()

    # A single head means the upstream branches have not diverged.
    # print heads
    return (len(heads) > 1)
