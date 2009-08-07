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
from bzrlib.commands import Command

from bzrlib.plugins.builddeb.import_dsc import DistributionBranch


class WrongBranchType(errors.BzrError):
    _fmt = "The merge target is not a packaging branch."

def _debug(lines):
    if not trace.is_verbose():
        return
    for line in lines:
        print line
    sys.stdout.flush()

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

def get_upstream_revids(source, target):
    # Please note: both branches must have been read-locked beforehand.

    # Get the revision IDs for the most recent source and target
    # upstream versions respectively.
    _debug(['\n>> get_upstream_revids()\n'])
    upstream_revids = dict()
    for branch_name, branch in dict(source=source, target=target).iteritems():
        db = DistributionBranch(branch, branch)
        version = _latest_version(branch)
        # print "Version : %s, %s\n" % (version, version.upstream_version)
        upstream_revids[branch_name] = (
            version.upstream_version,
            db.revid_of_upstream_version_from_branch(
                version.upstream_version))

    _debug(['upstream revids: %s' % upstream_revids,
            '\n<< get_upstream_revids()\n'])
    return upstream_revids

def fix_upstream_ancestry(tree, source, upstream_revids):
    _debug(['\n>> fix_upstream_ancestry()\n',
            '!! Upstream branches diverged'])

    # "Unpack" the versions and revision ids.
    source_ver = Version(upstream_revids['source'][0])
    source_revid = upstream_revids['source'][1]
    target_ver = Version(upstream_revids['target'][0])
    target_revid = upstream_revids['target'][1]

    db = DistributionBranch(tree.branch, tree.branch)
    tempdir = tempfile.mkdtemp(dir=os.path.join(tree.basedir, '..'))
    db._extract_upstream_tree(target_revid, tempdir)

    upstream_tree = db.upstream_tree

    # Merge upstream branch tips to obtain a shared upstream parent.
    _debug(["\n--> Merge upstream branch tips.\n"])
    try:
        upstream_tree.lock_write()

        if source_ver > target_ver:
            # The source upstream tree is more recent and the temporary
            # target tree needs to be reshaped to match it.
            _debug(["\n--> Reverting upstream target tree.\n"])
            upstream_tree.revert(None, source.repository.revision_tree(source_revid))
        _debug(["--> Setting parent IDs on upstream tree.\n"])
        upstream_tree.set_parent_ids((target_revid, source_revid))
        _debug(["--> Committing upstream tree.\n"])
        upstream_tree.commit('Consolidated upstream tree for merging into target branch')
    finally:
        upstream_tree.unlock()

    # Merge shared upstream parent into the target merge branch.
    _debug(["\n--> Merge shared upstream into target merge branch.\n"])
    try:
        tree.lock_write()
        conflicts = tree.merge_from_branch(upstream_tree.branch)
        tree.commit('Merging source packaging branch in to target.')
    finally:
        tree.unlock()

    _debug(['merge conflicts: %s' % conflicts,
            '\n<< fix_upstream_ancestry()\n'])
    return conflicts
