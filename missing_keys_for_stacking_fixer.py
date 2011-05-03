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


from bzrlib.bzrdir import BzrDir
from bzrlib.commands import Command, Option
from bzrlib import errors
from bzrlib.graph import PendingAncestryResult
from bzrlib.revision import NULL_REVISION


class cmd_fix_missing_keys_for_stacking(Command):
    """Fix missing keys for stacking.
    
    This is the fixer script for <https://bugs.launchpad.net/bzr/+bug/354036>.
    """

    takes_args = ['branch_url']
    takes_options = [
        Option('dry-run',
               help="Show what would be done, but don't actually do anything."),
        ]

    def run(self, branch_url, dry_run=False):
        try:
            bd = BzrDir.open(branch_url)
            b = bd.open_branch(ignore_fallbacks=True)
        except (errors.NotBranchError, errors.InvalidURL):
            print >>self.outf, "Not a branch or invalid URL: %s" % branch_url
            return
        b.lock_read()
        try:
            url = b.get_stacked_on_url()
        except (errors.UnstackableRepositoryFormat, errors.NotStacked,
            errors.UnstackableBranchFormat):
            print >>self.outf, "Not stacked: %s" % branch_url
            b.unlock()
            return
        raw_r = b.repository.bzrdir.open_repository()
        if dry_run:
            raw_r.lock_read()
        else:
            b.unlock()
            b = b.bzrdir.open_branch()
            b.lock_read()
            raw_r.lock_write()
        try:
          revs = raw_r.all_revision_ids()
          rev_parents = raw_r.get_graph().get_parent_map(revs)
          needed = set()
          map(needed.update, rev_parents.itervalues())
          needed.discard(NULL_REVISION)
          needed = set((rev,) for rev in needed)
          needed = needed - raw_r.inventories.keys()
          if not needed:
            # Nothing to see here.
            return
          print >>self.outf, "Missing inventories: %r" % needed
          if dry_run:
            return
          assert raw_r._format.network_name() == b.repository._format.network_name()
          stream = b.repository.inventories.get_record_stream(needed, 'topological', True)
          raw_r.start_write_group()
          try:
            raw_r.inventories.insert_record_stream(stream)
          except:
            raw_r.abort_write_group()
            raise
          else:
            raw_r.commit_write_group()
        finally:
          raw_r.unlock()
        b.unlock()
        print >>self.outf, "Fixed: %s" % branch_url



class cmd_mirror_revs_into(Command):
    """Mirror all revs from one repo into another."""

    takes_args = ['source', 'destination']

    _see_also = ['fetch-all-records']

    def run(self, source, destination):
        bd = BzrDir.open(source)
        source_r = bd.open_branch().repository
        bd = BzrDir.open(destination)
        target_r = bd.open_branch().repository
        source_r.lock_read()
        target_r.lock_write()
        try:
            revs = [k[-1] for k in source_r.revisions.keys()]
            target_r.fetch(
                source_r, fetch_spec=PendingAncestryResult(revs, source_r))
        finally:
            target_r.unlock()
            source_r.unlock()

