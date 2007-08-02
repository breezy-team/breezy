# Copyright (C) 2007 by Jelmer Vernooij <jelmer@samba.org>
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
"""Rebase support.

The Bazaar rebase plugin adds support for rebasing branches to Bazaar.
It adds the command 'rebase' to Bazaar. When conflicts occur when replaying
patches, the user can resolve the conflict and continue the rebase using the
'rebase-continue' command or abort using the 'rebase-abort' command.
"""

from bzrlib.commands import Command, Option, display_command, register_command
from bzrlib.errors import (BzrCommandError, ConflictsInTree, NoSuchFile, 
                           UnrelatedBranches)
from bzrlib.trace import info

__version__ = '0.1'
__author__ = 'Jelmer Vernooij <jelmer@samba.org>'

class cmd_rebase(Command):
    """Re-base a branch.

    Rebasing is the process of taking a branch and modifying the history so
    that it appears to start from a different point. This can be useful
    to clean up the history before submitting your changes. The tree at the
    end of the process will be the same as if you had merged the other branch,
    but the history will be different.

    The command takes the location of another branch on to which the branch in
    the current working directory will be rebased. If a branch is not specified
    then the parent branch is used, and this is usually the desired result.

    The first step identifies the revisions that are in the current branch that
    are not in the parent branch. The current branch is then set to be at the
    same revision as the target branch, and each revision is replayed on top
    of the branch. At the end of the process it will appear as though your
    current branch was branched off the current last revision of the target.

    Each revision that is replayed may cause conflicts in the tree. If this
    happens the command will stop and allow you to fix them up. Resolve the
    commits as you would for a merge, and then run 'bzr resolve' to marked
    them as resolved. Once you have resolved all the conflicts you should
    run 'bzr rebase-continue' to continue the rebase operation.

    If conflicts are encountered and you decide that you do not wish to continue
    you can run 'bzr rebase-abort'.

    The '--onto' option allows you to specify a different revision in the
    target branch to start at when replaying the revisions. This means that
    you can change the point at which the current branch will appear to be
    branched from when the operation completes.
    """
    takes_args = ['upstream_location?']
    takes_options = ['revision', 'merge-type', 'verbose',
        Option('dry-run',
               help="Show what would be done, but don't actually do anything."),
        Option('onto', help='Different revision to replay onto.',
               type=str)]
    
    @display_command
    def run(self, upstream_location=None, onto=None, revision=None, 
            merge_type=None, verbose=False, dry_run=False):
        from bzrlib.branch import Branch
        from bzrlib.revisionspec import RevisionSpec
        from bzrlib.workingtree import WorkingTree
        from rebase import (generate_simple_plan, rebase, rebase_plan_exists, 
                            read_rebase_plan, remove_rebase_plan, 
                            workingtree_replay, write_rebase_plan,
                            regenerate_default_revid,
                            rebase_todo)
        wt = WorkingTree.open('.')
        wt.lock_write()
        if upstream_location is None:
            upstream_location = wt.branch.get_parent()
            info("Rebasing on %s" % upstream_location)
        upstream = Branch.open(upstream_location)
        upstream_repository = upstream.repository
        upstream_revision = upstream.last_revision()
        try:
            # Abort if there already is a plan file
            if rebase_plan_exists(wt):
                raise BzrCommandError("A rebase operation was interrupted. Continue using 'bzr rebase-continue' or abort using 'bzr rebase-abort'")

            # Pull required revisions
            wt.branch.repository.fetch(upstream_repository, upstream_revision)
            if onto is None:
                onto = upstream.last_revision()
            else:
                rev_spec = RevisionSpec.from_string(onto)
                onto = rev_spec.in_history(upstream).rev_id

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
            stop_revid = wt.branch.last_revision()

            # Create plan
            replace_map = generate_simple_plan(
                    wt.branch.revision_history(), start_revid, stop_revid, onto,
                    wt.branch.repository.get_ancestry(onto),
                    wt.branch.repository.revision_parents,
                    lambda revid: regenerate_default_revid(wt.branch.repository, revid)
                    )

            if verbose:
                todo = list(rebase_todo(wt.branch.repository, replace_map))
                info('%d revisions will be rebased:' % len(todo))
                for revid in todo:
                    info("%s" % revid)

            if not dry_run:
                # Write plan file
                write_rebase_plan(wt, replace_map)

                # Start executing plan
                try:
                    rebase(wt.branch.repository, replace_map, 
                           workingtree_replay(wt, merge_type=merge_type))
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
                raise BzrCommandError("There are still conflicts present. "
                                      "Resolve the conflicts and then run "
                                      "'bzr resolve' and try again.")
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
    testmod_names = ['test_blackbox', 'test_rebase', 'test_maptree']
    suite.addTest(loader.loadTestsFromModuleNames(
                              ["%s.%s" % (__name__, i) for i in testmod_names]))

    return suite

