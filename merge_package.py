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

import os
import re
import sys
import tempfile

from debian_bundle.changelog import Version

from bzrlib import builtins, errors, merge, trace
from bzrlib.branch import Branch

from bzrlib.plugins.builddeb.import_dsc import DistributionBranch


class WrongBranchType(errors.BzrError):
    _fmt = "The merge target is not a packaging branch."


class InvalidChangelogFormat(errors.BzrError):
    _fmt = "The debian/changelog is empty or not in valid format."

class SourceUpstreamConflictsWithTargetPackaging(errors.BzrError):
    _fmt = (
        "The source upstream branch conflicts with "
        "the target packaging branch")


def _debug(lines):
    """Write lines of debug output and flush stdout if in verbose mode.

    :param lines: A sequence of strings, the debug output to write.
    """
    if not trace.is_verbose():
        return
    for line in lines:
        print line
    sys.stdout.flush()


def _read_file(branch, path):
    """Get content of file for given `branch` and `path.
    
    :param branch: A Branch object containing the file of interest.
    :param path: The path of the file to read.
    """
    try:
        tree = branch.basis_tree()
        tree.lock_read()
        content = tree.get_file_text(tree.path2id(path))
        tree.unlock()
    except errors.NoSuchId:
        raise WrongBranchType()

    return content


def _latest_version(branch):
    """Version of the most recent source package upload in the given `branch`.
    
    :param branch: A Branch object containing the source upload of interest.
    """
    upload_version = ''
    changelog = _read_file(branch, "debian/changelog")

    for line in changelog.splitlines():
        # Look for the top-level changelog stanza, extract the
        # upload version from it and break on success.
        match = re.search('^.+\(([^)]+)\).*$', line)
        if match is not None:
            (upload_version,) = match.groups(1)
            break

    upload_version = upload_version.strip()
    if len(upload_version) <= 0:
        raise InvalidChangelogFormat()

    return Version(upload_version)


def _upstream_version_data(source, target):
    """Most recent upstream versions/revision IDs of the merge source/target.

    Please note: both packaing branches must have been read-locked beforehand.

    :param source: The merge source branch.
    :param target: The merge target branch.
    """
    _debug(['\n>> get_upstream_revids()\n'])
    results = list()
    for branch in (source, target):
        db = DistributionBranch(branch, branch)
        uver = _latest_version(branch).upstream_version
        results.append((uver, db.revid_of_upstream_version_from_branch(uver)))

    _debug(['upstream revids: %s' % results, '\n<< get_upstream_revids()\n'])
    return results


def _upstreams_diverged(source, target, upstream_revids):
    """Did the upstream branches of the merge source and target diverge?

    :param source: The merge source (packaging) branch.
    :param target: The merge target (packaging) branch.
    :param upstream_revids: The source/target branch upstream revision IDs.
    """
    graph = source.repository.get_graph(target.repository)
    # Get the number of heads for the combined upstream branches graph.
    heads = graph.heads(upstream_revids)
    return (len(heads) > 1)


def fix_ancestry_if_needed(tree, source, upstream_revids):
    """Manipulate the merge target's ancestry to avoid upstream conflicts.

    Merging J->I given the following ancestry tree is likely to result in
    upstream merge conflicts:

    debian-upstream                 ,------------------H
                       A-----------B                    \
    ubuntu-upstream     \           \`-------G           \
                         \           \        \           \
    debian-packaging      \ ,---------D--------\-----------J
                           C           \        \
    ubuntu-packaging        `----E------F--------I

    Here there was a new upstream release (G) that Ubuntu packaged (I), and
    then another one that Debian packaged, skipping G, at H and J.

    Now, the way to solve this is to introduce the missing link.

    debian-upstream                 ,------------------H------.
                       A-----------B                    \      \
    ubuntu-upstream     \           \`-------G-----------\------K
                         \           \        \           \
    debian-packaging      \ ,---------D--------\-----------J
                           C           \        \
    ubuntu-packaging        `----E------F--------I

    at K, which isn't a real merge, as we just use the tree from H, but add
    G as a parent and then we merge that in to Ubuntu.

    debian-upstream                 ,------------------H------.
                       A-----------B                    \      \
    ubuntu-upstream     \           \`-------G-----------\------K
                         \           \        \           \      \
    debian-packaging      \ ,---------D--------\-----------J      \
                           C           \        \                  \
    ubuntu-packaging        `----E------F--------I------------------L

    At this point we can merge J->L to merge the Debian and Ubuntu changes.

    :param tree: The `WorkingTree` of the merge target branch.
    :param source: The merge source (packaging) branch.
    :param upstream_revids: A dict with the source/target branch upstream
        versions and revision IDs.
    """
    _debug(['\n>> fix_ancestry_if_needed()\n', '!! Upstream branches diverged'])

    upstreams_diverged = False
    target = tree.branch

    try:
        source.lock_read()
        target.lock_read()
        upstream_vdata = _upstream_version_data(source, target)
        revids = [vdata[1] for vdata in upstream_vdata]
        upstreams_diverged = _upstreams_diverged(source, target, revids)
    finally:
        source.unlock()
        target.unlock()

    if not upstreams_diverged:
        return upstreams_diverged

    # "Unpack" the upstream versions and revision ids for the merge source and
    # target branch respectively.
    [(usource_v, usource_revid), (utarget_v, utarget_revid)] = upstream_vdata

    # Instantiate a `DistributionBranch` object for the merge target
    # (packaging) branch.
    db = DistributionBranch(tree.branch, tree.branch)
    tempdir = tempfile.mkdtemp(dir=os.path.join(tree.basedir, '..'))

    # Extract the merge target's upstream tree into a temporary directory.
    db._extract_upstream_tree(utarget_revid, tempdir)
    tmp_target_upstream_tree = db.upstream_tree

    # TODO: fix comment below.
    # Merge upstream branch tips to obtain a shared upstream parent. This will
    # add revision K (see graph above) to a temporary merge target upstream
    # tree.
    _debug(["\n--> Merge upstream branch tips.\n"])
    try:
        tmp_target_upstream_tree.lock_write()

        if usource_v > utarget_v:
            # The source upstream tree is more recent and the temporary
            # target tree needs to be reshaped to match it.
            _debug(["\n--> Reverting upstream target tree.\n"])
            tmp_target_upstream_tree.revert(
                None, source.repository.revision_tree(usource_revid))

        _debug(["--> Setting parent IDs on temporary upstream tree.\n"])
        tmp_target_upstream_tree.set_parent_ids(
            (utarget_revid, usource_revid))

        _debug(["--> Committing temporary upstream tree.\n"])
        tmp_target_upstream_tree.commit(
            'Consolidated upstream tree for merging into target branch')
    finally:
        tmp_target_upstream_tree.unlock()

    # Merge shared upstream parent into the target merge branch. This creates
    # revison L in the digram above.
    _debug(["\n--> Merge shared upstream into target merge branch.\n"])
    try:
        tree.lock_write()
        try:
            tree.merge_from_branch(tmp_target_upstream_tree.branch)
            tree.commit('Merging source packaging branch in to target.')
        except ConflictsInTree:
            raise SourceUpstreamConflictsWithTargetPackaging()
    finally:
        tree.unlock()

    _debug(['merge conflicts: %s' % conflicts,
            '\n<< fix_ancestry_if_needed()\n'])

    return upstreams_diverged
