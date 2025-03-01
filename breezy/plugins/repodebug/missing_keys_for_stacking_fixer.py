# Copyright (C) 2009-2011 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

from ... import errors
from ...bzr.vf_search import PendingAncestryResult
from ...commands import Command
from ...controldir import ControlDir
from ...option import Option
from ...repository import WriteGroup
from ...revision import NULL_REVISION


class cmd_fix_missing_keys_for_stacking(Command):
    """Fix missing keys for stacking.

    This is the fixer script for <https://bugs.launchpad.net/bzr/+bug/354036>.
    """

    hidden = True
    takes_args = ["branch_url"]
    takes_options = [
        Option(
            "dry-run", help="Show what would be done, but don't actually do anything."
        ),
    ]

    def run(self, branch_url, dry_run=False):
        try:
            bd = ControlDir.open(branch_url)
            b = bd.open_branch(ignore_fallbacks=True)
        except (errors.NotBranchError, errors.InvalidURL):
            raise errors.CommandError("Not a branch or invalid URL: {}".format(branch_url))
        b.lock_read()
        try:
            b.get_stacked_on_url()
        except (
            errors.UnstackableRepositoryFormat,
            errors.NotStacked,
            errors.UnstackableBranchFormat,
        ):
            b.unlock()
            raise errors.CommandError("Not stacked: {}".format(branch_url))
        raw_r = b.repository.controldir.open_repository()
        if dry_run:
            raw_r.lock_read()
        else:
            b.unlock()
            b = b.controldir.open_branch()
            b.lock_read()
            raw_r.lock_write()
        try:
            revs = raw_r.all_revision_ids()
            rev_parents = raw_r.get_graph().get_parent_map(revs)
            needed = set()
            map(needed.update, rev_parents.values())
            needed.discard(NULL_REVISION)
            needed = {(rev,) for rev in needed}
            needed = needed - raw_r.inventories.keys()
            if not needed:
                # Nothing to see here.
                return
            self.outf.write("Missing inventories: {!r}\n".format(needed))
            if dry_run:
                return
            assert raw_r._format.network_name() == b.repository._format.network_name()
            stream = b.repository.inventories.get_record_stream(
                needed, "topological", True
            )
            with WriteGroup(raw_r):
                raw_r.inventories.insert_record_stream(stream)
        finally:
            raw_r.unlock()
        b.unlock()
        self.outf.write("Fixed: {}\n".format(branch_url))


class cmd_mirror_revs_into(Command):
    """Mirror all revs from one repo into another."""

    hidden = True
    takes_args = ["source", "destination"]

    _see_also = ["fetch-all-records"]

    def run(self, source, destination):
        bd = ControlDir.open(source)
        source_r = bd.open_branch().repository
        bd = ControlDir.open(destination)
        target_r = bd.open_branch().repository
        with source_r.lock_read(), target_r.lock_write():
            revs = [k[-1] for k in source_r.revisions.keys()]
            target_r.fetch(source_r, fetch_spec=PendingAncestryResult(revs, source_r))
