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

from bzrlib.commands import Command, Option, display_command
from bzrlib.workingtree import WorkingTree

class cmd_rebase(Command):
    """Re-base a branch.

    """
    takes_args = ['upstream']
    takes_options = [Option('onto', help='Different revision to replay onto')]
    
    @display_command
    def run(self, upstream, onto=None):
        wt = WorkingTree.open('.')
        # TODO: Abort if there are any pending changes
        # TODO: Abort if there are any conflicts
        # TODO: Pull required revisions
        # TODO: Write plan file
        # TODO: Start executing plan
        # If any conflicts occur:
        #   TODO: Apply failed merge to the working tree
        #   TODO: Inform user about rebase-continue and rebase-abort
        #   TODO: Abort
        # TODO: Remove plan file

class cmd_rebase_abort(Command):
    """Abort an interrupted rebase

    """
    
    @display_command
    def run(self):
        wt = WorkingTree.open('.')
        # TODO: Read plan file
        # TODO: Set last revision


class cmd_rebase_continue(Command):
    """Continue an interrupted rebase after resolving conflicts

    """
    
    @display_command
    def run(self):
        wt = WorkingTree.open('.')
        # TODO: Read plan file
        # TODO: Abort if there are any conflicts
        # TODO: Start executing plan from current Branch.last_revision()
        # If conflict appears:
        #   TODO: Apply failed merge to the working tree
        #   TODO: Inform user about rebase-continue and rebase-abort
        #   TODO: Abort
        # TODO: Remove plan file  


def test_suite():
    from unittest import TestSuite
    from bzrlib.tests import TestUtil

    loader = TestUtil.TestLoader()
    suite = TestSuite()
    testmod_names = [
            'test_rebase']
    suite.addTest(loader.loadTestsFromModuleNames(["%s.%s" % (__name__, i) for i in testmod_names]))

    return suite

