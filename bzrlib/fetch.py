# Copyright (C) 2005 by Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import sys
import os

import bzrlib.errors
from bzrlib.trace import mutter, note
from bzrlib.branch import Branch
from bzrlib.progress import ProgressBar

def has_revision(branch, revision_id):
    try:
        branch.get_revision_xml(revision_id)
        return True
    except bzrlib.errors.NoSuchRevision:
        return False


def greedy_fetch(to_branch, from_branch, revision=None, pb=None):
    """Copy a revision and all available ancestors from one branch to another
    If no revision is specified, uses the last revision in the source branch's
    revision history.
    """
    from_history = from_branch.revision_history()
    required_revisions = set(from_history)
    all_failed = set()
    if revision is not None:
        required_revisions.add(revision)
        try:
            rev_index = from_history.index(revision)
        except ValueError:
            rev_index = None
        if rev_index is not None:
            from_history = from_history[:rev_index + 1]
        else:
            from_history = [revision]
    to_history = to_branch.revision_history()
    missing = []
    for rev_id in from_history:
        if not has_revision(to_branch, rev_id):
            missing.append(rev_id)
    
    count = 0
    while len(missing) > 0:
        installed, failed = to_branch.install_revisions(from_branch, 
                                                        revision_ids=missing,
                                                        pb=pb)
        count += installed
        required_failed = failed.intersection(required_revisions)
        if len(required_failed) > 0:
            raise bzrlib.errors.InstallFailed(required_failed)
        for rev_id in failed:
            note("Failed to install %s" % rev_id)
        all_failed.update(failed)
        new_missing = set() 
        for rev_id in missing:
            try:
                revision = from_branch.get_revision(rev_id)
            except bzrlib.errors.NoSuchRevision:
                if revision in from_history:
                    raise
                else:
                    continue
            for parent in [p.revision_id for p in revision.parents]:
                if not has_revision(to_branch, parent):
                    new_missing.add(parent)
        missing = new_missing
    return count, all_failed


