# Copyright (C) 2007 by Jelmer Vernooij
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

from bzrlib.commands import Command, Option, display_command, register_command
from bzrlib.errors import BzrCommandError, UnrelatedBranches, ConflictsInTree, NoSuchFile
from bzrlib.trace import info

class cmd_rebase(Command):
    """Re-base a branch.

    """
    takes_args = ['upstream_location?']
    takes_options = ['revision', Option('onto', help='Different revision to replay onto')]
    
    @display_command
    def run(self, upstream_location=None, onto=None, revision=None):
        from bzrlib.branch import Branch
        from bzrlib.revisionspec import RevisionSpec
        from bzrlib.workingtree import WorkingTree
        from rebase import (generate_simple_plan, rebase, 
                            rebase_plan_exists, write_rebase_plan, 
                            read_rebase_plan, workingtree_replay, remove_rebase_plan)
        wt = WorkingTree.open('.')
        wt.lock_write()
        if upstream_location is None:
            upstream_location = wt.branch.get_parent()
        upstream = Branch.open(upstream_location)
        upstream_repository = upstream.repository
        upstream_revision = upstream.last_revision()
        try:
            # Abort if there already is a plan file
            if rebase_plan_exists(wt):
                raise BzrCommandError("A rebase operation was interrupted. Continue using 'bzr rebase-continue' or abort using 'bzr rebase-abort'")

            # Pull required revisions
            wt.branch.repository.fetch(upstream_repository, 
                                       upstream_revision)
            if onto is None:
                onto = upstream.last_revision()
            else:
                onto = RevisionSpec.from_string(onto)

            wt.branch.repository.fetch(upstream_repository, onto)

            start_revid = None
            revhistory = wt.branch.revision_history()
            revhistory.reverse()
            for revid in revhistory:
                if revid in upstream.revision_history():
                    start_revid = wt.branch.get_rev_id(wt.branch.revision_id_to_revno(revid)+1)
                    break

            if start_revid is None:
                raise UnrelatedBranches()

            # Create plan
            replace_map = generate_simple_plan(
                    wt.branch.repository, 
                    wt.branch.revision_history(), start_revid, onto)

            # Write plan file
            write_rebase_plan(wt, replace_map)

            # Start executing plan
            try:
                rebase(wt.branch.repository, replace_map, workingtree_replay(wt))
            except ConflictsInTree:
                raise BzrCommandError("A conflict occurred replaying a commit. Resolve the conflict and run 'bzr rebase-continue' or run 'bzr rebase-abort'.")
            # Remove plan file
            remove_rebase_plan(wt)
        finally:
            wt.unlock()

class cmd_rebase_abort(Command):
    """Abort an interrupted rebase

    """
    
    @display_command
    def run(self):
        from rebase import read_rebase_plan, remove_rebase_plan
        from bzrlib.workingtree import WorkingTree
        wt = WorkingTree.open('.')
        wt.lock_write()
        try:
            # Read plan file and set last revision
            try:
                last_rev_info = read_rebase_plan(wt)[0]
            except NoSuchFile:
                raise BzrCommandError("No rebase to abort")
            wt.branch.set_last_revision_info(last_rev_info[0], last_rev_info[1])
            wt.set_last_revision(last_rev_info[1])
            wt.revert([], backups=False)
            remove_rebase_plan(wt)
        finally:
            wt.unlock()


class cmd_rebase_continue(Command):
    """Continue an interrupted rebase after resolving conflicts

    """
    
    @display_command
    def run(self):
        from rebase import read_rebase_plan, rebase_plan_exists, workingtree_replay, rebase, remove_rebase_plan, commit_rebase, read_active_rebase_revid
        from bzrlib.workingtree import WorkingTree
        wt = WorkingTree.open('.')
        wt.lock_write()
        try:
            # Abort if there are any conflicts
            if len(wt.conflicts()) != 0:
                raise BzrCommandError("There are still conflicts present")
            # Read plan file
            try:
                replace_map = read_rebase_plan(wt)[1]
            except NoSuchFile:
                raise BzrCommandError("No rebase to continue")
            oldrevid = read_active_rebase_revid(wt)
            if oldrevid is not None:
                oldrev = wt.branch.repository.get_revision(oldrevid)
                commit_rebase(wt, oldrev, replace_map[oldrevid][0])
            try:
                # Start executing plan from current Branch.last_revision()
                rebase(wt.branch.repository, replace_map, workingtree_replay(wt))
            except ConflictsInTree:
                raise BzrCommandError("A conflict occurred replaying a commit. Resolve the conflict and run 'bzr rebase-continue' or run 'bzr rebase-abort'.")
            # Remove plan file  
            remove_rebase_plan(wt)
        finally:
            wt.unlock()


class cmd_rebase_todo(Command):
    """Print list of revisions that still need to be replayed as part of the current rebase operation.

    """
    
    def run(self):
        from rebase import read_rebase_plan, rebase_todo, read_active_rebase_revid
        from bzrlib.workingtree import WorkingTree
        wt = WorkingTree.open('.')
        wt.lock_read()
        try:
            try:
                replace_map = read_rebase_plan(wt)[1]
            except NoSuchFile:
                raise BzrCommandError("No rebase to view")
            currentrevid = read_active_rebase_revid(wt)
            if currentrevid is not None:
                info("Currently replaying: %s" % currentrevid)
            for revid in rebase_todo(wt.branch.repository, replace_map):
                info("%s -> %s" % (revid, replace_map[revid][0]))
        finally:
            wt.unlock()

register_command(cmd_rebase)
register_command(cmd_rebase_abort)
register_command(cmd_rebase_continue)
register_command(cmd_rebase_todo)

def test_suite():
    from unittest import TestSuite
    from bzrlib.tests import TestUtil

    loader = TestUtil.TestLoader()
    suite = TestSuite()
    testmod_names = [
            'test_rebase']
    suite.addTest(loader.loadTestsFromModuleNames(["%s.%s" % (__name__, i) for i in testmod_names]))

    return suite

