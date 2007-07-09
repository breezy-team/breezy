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
from bzrlib.errors import (BzrCommandError, ConflictsInTree, NoSuchFile, 
                           UnrelatedBranches)
from bzrlib.trace import info

class cmd_rebase(Command):
    """Re-base a branch.

    """
    takes_args = ['upstream_location?']
    takes_options = ['revision', 'merge-type', 
                     Option('onto', help='Different revision to replay onto')]
    
    @display_command
    def run(self, upstream_location=None, onto=None, revision=None, 
            merge_type=None):
        from bzrlib.branch import Branch
        from bzrlib.revisionspec import RevisionSpec
        from bzrlib.workingtree import WorkingTree
        from rebase import (generate_simple_plan, rebase, rebase_plan_exists, 
                            read_rebase_plan, remove_rebase_plan, 
                            workingtree_replay, write_rebase_plan)
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

            revhistory = wt.branch.revision_history()
            revhistory.reverse()
            common_revid = None
            for revid in revhistory:
                if revid in upstream.revision_history():
                    common_revid = revid
                    break

            if common_revid is None:
                raise UnrelatedBranches()

            if common_revid == upstream.last_revision():
                raise BzrCommandError("Already rebased on %s" % upstream)

            start_revid = wt.branch.get_rev_id(
                    wt.branch.revision_id_to_revno(common_revid)+1)

            # Create plan
            replace_map = generate_simple_plan(
                    wt.branch.repository, 
                    wt.branch.revision_history(), start_revid, onto)

            # Write plan file
            write_rebase_plan(wt, replace_map)

            # Start executing plan
            try:
                rebase(wt.branch.repository, replace_map, workingtree_replay(wt, merge_type=merge_type))
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
        from rebase import read_rebase_plan, remove_rebase_plan, complete_revert
        from bzrlib.workingtree import WorkingTree
        wt = WorkingTree.open('.')
        wt.lock_write()
        try:
            # Read plan file and set last revision
            try:
                last_rev_info = read_rebase_plan(wt)[0]
            except NoSuchFile:
                raise BzrCommandError("No rebase to abort")
            complete_revert(wt, [last_rev_info[1]])
            remove_rebase_plan(wt)
        finally:
            wt.unlock()


class cmd_rebase_continue(Command):
    """Continue an interrupted rebase after resolving conflicts

    """
    takes_options = ['merge-type']
    
    @display_command
    def run(self, merge_type=None):
        from rebase import (commit_rebase, rebase, rebase_plan_exists, 
                            read_rebase_plan, read_active_rebase_revid, 
                            remove_rebase_plan, workingtree_replay)
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
                rebase(wt.branch.repository, replace_map, 
                        workingtree_replay(wt, merge_type=merge_type))
            except ConflictsInTree:
                raise BzrCommandError("A conflict occurred replaying a commit. Resolve the conflict and run 'bzr rebase-continue' or run 'bzr rebase-abort'.")
            # Remove plan file  
            remove_rebase_plan(wt)
        finally:
            wt.unlock()


class cmd_rebase_todo(Command):
    """Print list of revisions that still need to be replayed as part of the 
    current rebase operation.

    """
    
    def run(self):
        from rebase import (rebase_todo, read_rebase_plan, 
                            read_active_rebase_revid)
        from bzrlib.workingtree import WorkingTree
        wt = WorkingTree.open('.')
        wt.lock_read()
        try:
            try:
                replace_map = read_rebase_plan(wt)[1]
            except NoSuchFile:
                raise BzrCommandError("No rebase in progress")
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
    testmod_names = ['test_rebase', 'test_maptree']
    suite.addTest(loader.loadTestsFromModuleNames(
                              ["%s.%s" % (__name__, i) for i in testmod_names]))

    return suite

