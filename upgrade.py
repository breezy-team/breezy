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
from bzrlib.errors import BzrError, InvalidRevisionId
from bzrlib.ui import ui_factory

from repository import MAPPING_VERSION, parse_svn_revision_id, unescape_svn_path

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
        self.revid = revid


# Change the parent of a revision
def change_revision_parent(repository, oldrevid, newrevid, new_parents):
    assert isinstance(new_parents, list)
    oldrev = repository.get_revision(oldrevid)

    builder = repository.get_commit_builder(branch=None, parents=new_parents, 
                                  config=Config(),
                                  committer=oldrev.committer,
                                  timestamp=oldrev.timestamp,
                                  timezone=oldrev.timezone,
                                  revprops=oldrev.properties,
                                  revision_id=newrevid)

    for path, ie in repository.get_revision_inventory(oldrevid).iter_entries():
        new_ie = ie.copy()
        if new_ie.revision == oldrevid:
            new_ie.revision = None
        builder.record_entry_contents(new_ie, 
               map(repository.get_revision_inventory, new_parents), 
               path, repository.revision_tree(oldrevid))

    builder.finish_inventory()
    return builder.commit(oldrev.message)


def parse_legacy_revision_id(revid):
    if revid.startswith("svn-v1:"):
        revid = revid[len("svn-v1:"):]
        at = revid.index("@")
        fash = revid.rindex("-")
        uuid = revid[at+1:fash]
        branch_path = unescape_svn_path(revid[fash+1:])
        revnum = int(revid[0:at])
        assert revnum >= 0
        return (uuid, branch_path, revnum, 1)
    elif revid.startswith("svn-v2:"):
        (uuid, bp, rev) = parse_svn_revision_id(revid)
        return (uuid, bp, rev, 2)

    raise InvalidRevisionId(revid, None)


def create_upgraded_revid(revid):
    suffix = "-svn%d-upgrade" % MAPPING_VERSION
    if revid.endswith("-upgrade"):
        return revid[0:revid.rfind("-svn")] + suffix
    else:
        return revid + suffix


def upgrade_repository(repository, svn_repository, revision_id=None, 
                       allow_change=False):

    needed_revs = []
    needs_upgrading = []
    new_parents = {}
    rename_map = {}

    # Find revisions that need to be upgraded, create
    # dictionary with revision ids in key, new parents in value
    graph = repository.get_revision_graph()
    for revid in graph:
        try:
            uuid = parse_legacy_revision_id(revid)[0]
            if uuid == svn_repository.uuid:
                continue
        except InvalidRevisionId:
            pass
        new_parents[revid] = []
        for parent in graph[revid]:
            try:
                (uuid, bp, rev, version) = parse_legacy_revision_id(parent)
                new_parent = svn_repository.generate_revision_id(rev, bp)
                if new_parent != parent:
                    needed_revs.append(new_parent)
                    needs_upgrading.append(revid)
                new_parents[revid].append(new_parent)
            except InvalidRevisionId:
                new_parents[revid].append(parent)

    # Make sure all the required current version revisions are present
    pb = ui_factory.nested_progress_bar()
    i = 0
    for revid in needed_revs:
        pb.update('fetching new revisions', i, len(needed_revs))
        repository.fetch(svn_repository, revid)
        i+=1
    pb.finished()

    pb = ui_factory.nested_progress_bar()
    i = 0
    while len(needs_upgrading) > 0:
        revid = needs_upgrading.pop()
        pb.update('upgrading revisions', i, len(needs_upgrading))
        i+=1
        newrevid = create_upgraded_revid(revid)
        if repository.has_revision(newrevid):
            continue
        change_revision_parent(repository, revid, newrevid, new_parents[revid])
        # FIXME: also upgrade children of newrevid
    pb.finished()
