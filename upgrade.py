#!/usr/bin/env python2.4
#
# Copyright (C) 2006 by Jelmer Vernooij
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
#

from bzrlib.config import Config
from bzrlib.errors import BzrError
from bzrlib.ui import ui_factory

from repository import MAPPING_VERSION

# Takes an existing Bazaar branch and replaces all old-version mapped revisions 
# with new-style revisions mappings. 
# 
# It checks the sha1s of the contents to make sure that the revision hasn't 
# changed. This behaviour can be turned off by specifying --allow-change.
#
# Usage: svn-upgrade [--allow-change] PATH REPOSITORY

class UpgradeChangesContent(BzrError):
    _fmt = """Upgrade will change contents in revision %(revid)s."""

    def __init__(self, revid):
        super(UpgradeChangesContent, self).__init__()
        self.revid = revid


# Change the parent of a revision
def change_revision_parent(repository, oldrevid, new_parents):
    assert isinstance(new_parents, list)
    suffix = "-svn%d-upgrade" % MAPPING_VERSION
    if oldrevid.endswith("-upgrade"):
        # FIXME: 
        newrevid = oldrevid
    else:
        newrevid = oldrevid + suffix

    oldrev = repository.get_revision(oldrevid)

    builder = repository.get_commit_builder(branch=None, parents=new_parents, 
                                  config=Config(),
                                  committer=oldrev.committer,
                                  timestamp=oldrev.timestamp,
                                  timezone=oldrev.timezone,
                                  revprops=oldrev.properties,
                                  revision_id=newrevid)

    # FIXME: Populate the inventory
    for path, ie in repository.get_revision_inventory(oldrevid).iter_entries():
        new_ie = ie.copy()
        if new_ie.revision == oldrevid:
            new_ie.revision = None
        builder.record_entry_contents(new_ie, 
               map(repository.get_revision_inventory, new_parents), 
               path, repository.revision_tree(oldrevid))

    builder.finish_inventory()
    return builder.commit(oldrev.message)


def upgrade_branch(branch, svn_repository, allow_change=False):
    needed_revs = []
    needs_upgrading = {}
    # FIXME: Find revisions that need to be upgraded, create
    # dictionary with revision ids in key, new parents in value

    # Make sure all the required current version revisions are present
    pb = ui_factory.nested_progress_bar()
    i = 0
    for revid in needed_revs:
        pb.update('fetching new revisions', i, len(needed_revs))
        branch.repository.fetch(svn_repository, revid)
        i+=1
    pb.finished()

    pb = ui_factory.nested_progress_bar()
    i = 0
    for revid in needs_upgrading:
        pb.update('upgrading revisions', i, len(needed_revs))
        change_revision_parent(branch, revid, needs_upgrading[revid])
        i+=1
    pb.finished()
