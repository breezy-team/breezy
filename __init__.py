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

from bzrlib.branch import Branch
from bzrlib.commands import Command, Option, display_command, register_command
from bzrlib.errors import BzrCommandError
from bzrlib.workingtree import WorkingTree

class cmd_rebase(Command):
    """Re-base a branch.

    """
    takes_args = ['upstream_location']
    takes_options = [Option('onto', help='Different revision to replay onto')]
    
    @display_command
    def run(self, upstream_location, onto=None):
        from rebase import (generate_simple_plan, rebase, 
                            rebase_plan_exists, write_rebase_plan, 
                            read_rebase_plan)
        upstream = Branch.open(upstream_location)
        wt = WorkingTree.open('.')
        wt.write_lock()
        try:
            # Abort if there already is a plan file
            if rebase_plan_exists(wt):
                raise BzrCommandError("A rebase operation was interrupted. Continue using 'bzr rebase-continue' or abort using 'bzr rebase-abort'")

            # Pull required revisions
            wt.branch.repository.fetch(upstream.repository, 
                                       upstream.last_revision())
            if onto is None:
                onto = upstream.last_revision()

            wt.branch.repository.fetch(upstream.repository, onto)

            # Create plan
            replace_map = generate_simple_plan(
                    wt.branch, upstream.last_revision(), onto)

            # Write plan file
            write_rebase_plan(wt, replace_map)

            # Set last-revision back to start revision
            wt.set_last_revision(onto)

            # Start executing plan
            try:
                rebase(wt, replace_map)
            except Conflict:
                raise BzrCommandError("A conflict occurred applying a patch. Resolve the conflict and run 'bzr rebase-continue' or run 'bzr rebase-abort'.")
            # Remove plan file
            remove_rebase_plan(wt)
        finally:
            wt.unlock()

class cmd_rebase_abort(Command):
    """Abort an interrupted rebase

    """
    
    @display_command
    def run(self):
        from rebase import read_rebase_plan
        wt = WorkingTree.open('.')
        wt.write_lock()
        try:
            # Read plan file and set last revision
            wt.set_last_revision_info(read_rebase_plan(wt)[0])
        finally:
            wt.unlock()


class cmd_rebase_continue(Command):
    """Continue an interrupted rebase after resolving conflicts

    """
    
    @display_command
    def run(self):
        from rebase import read_rebase_plan, rebase_plan_exists
        wt = WorkingTree.open('.')
        wt.write_lock()
        try:
            # Abort if there are any conflicts
            if len(wt.conflicts()) != 0:
                raise BzrCommandError("There are still conflicts present")
            # Read plan file
            replace_map = read_rebase_plan(wt)[1]

            try:
                # Start executing plan from current Branch.last_revision()
                rebase(wt, replace_map)
            except Conflict:
                raise BzrCommandError("A conflict occurred applying a patch. Resolve the conflict and run 'bzr rebase-continue' or run 'bzr rebase-abort'.")
            # Remove plan file  
            remove_rebase_plan(wt)
        finally:
            wt.unlock()


register_command(cmd_rebase)
register_command(cmd_rebase_abort)
register_command(cmd_rebase_continue)

def test_suite():
    from unittest import TestSuite
    from bzrlib.tests import TestUtil

    loader = TestUtil.TestLoader()
    suite = TestSuite()
    testmod_names = [
            'test_rebase']
    suite.addTest(loader.loadTestsFromModuleNames(["%s.%s" % (__name__, i) for i in testmod_names]))

    return suite

