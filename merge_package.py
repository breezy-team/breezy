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


def get_upstream_revids(source, target):
    """Revision IDs for the most recent source and target upstream versions.

    Please note: both branches must have been read-locked beforehand.

    :param source: The source (packaging) branch in the merge.
    :param target: The target (packaging) branch in the merge.
    """
    _debug(['\n>> get_upstream_revids()\n'])
    results = dict()
    for branch_name, branch in dict(source=source, target=target).iteritems():
        db = DistributionBranch(branch, branch)
        uver = _latest_version(branch).upstream_version
        results[branch_name] = (
            uver, db.revid_of_upstream_version_from_branch(uver))

    _debug(['upstream revids: %s' % results, '\n<< get_upstream_revids()\n'])
    return results


def fix_upstream_ancestry(tree, source, upstream_revids):
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
    _debug(['\n>> fix_upstream_ancestry()\n', '!! Upstream branches diverged'])

    # "Unpack" the upstream versions and revision ids for the merge source and
    # target branch respectively.
    source_ver = Version(upstream_revids['source'][0])
    source_revid = upstream_revids['source'][1]
    target_ver = Version(upstream_revids['target'][0])
    target_revid = upstream_revids['target'][1]

    # Instantiate a `DistributionBranch` object for the merge target
    # (packaging) branch.
    db = DistributionBranch(tree.branch, tree.branch)
    tempdir = tempfile.mkdtemp(dir=os.path.join(tree.basedir, '..'))
    db._extract_upstream_tree(target_revid, tempdir)

    tmp_target_upstream_tree = db.upstream_tree

    # Merge upstream branch tips to obtain a shared upstream parent. This will
    # add revision K (see graph above) to a temporary merge target upstream
    # tree.
    _debug(["\n--> Merge upstream branch tips.\n"])
    try:
        tmp_target_upstream_tree.lock_write()

        if source_ver > target_ver:
            # The source upstream tree is more recent and the temporary
            # target tree needs to be reshaped to match it.
            _debug(["\n--> Reverting upstream target tree.\n"])
            tmp_target_upstream_tree.revert(
                None, source.repository.revision_tree(source_revid))
        _debug(["--> Setting parent IDs on upstream tree.\n"])
        tmp_target_upstream_tree.set_parent_ids((target_revid, source_revid))
        _debug(["--> Committing upstream tree.\n"])
        tmp_target_upstream_tree.commit(
            'Consolidated upstream tree for merging into target branch')
    finally:
        tmp_target_upstream_tree.unlock()

    # Merge shared upstream parent into the target merge branch. This creates
    # revison L in the digram above.
    _debug(["\n--> Merge shared upstream into target merge branch.\n"])
    try:
        tree.lock_write()
        conflicts = tree.merge_from_branch(tmp_target_upstream_tree.branch)
        tree.commit('Merging source packaging branch in to target.')
    finally:
        tree.unlock()

    _debug(['merge conflicts: %s' % conflicts,
            '\n<< fix_upstream_ancestry()\n'])
    return conflicts
