# Copyright (C) 2006 by Canonical Ltd
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

"""Launchpad.net branch registration plugin for bzr

This adds commands that tell launchpad about newly-created branches, etc.

To install this file, put the 'bzr_lp' directory, or a symlink to it,
in your ~/.bazaar/plugins/ directory.
"""

from bzrlib.commands import Command, Option, register_command



class cmd_register_branch(Command):
    """Register a branch with launchpad.net.

    This command lists a bzr branch in the directory of branches on
    launchpad.net.  Registration allows the bug to be associated with
    bugs or specifications.
    
    Before using this command you must register the project to which the
    branch belongs, and create an account for yourself on launchpad.net.

    arguments:
        branch_url: The publicly visible url for the branch.
                    This must be an http or https url, not a local file
                    path.

    example:
        bzr register-branch http://foo.com/bzr/fooproject.mine \
                --project fooproject
    """
    takes_args = ['branch_url']

    def run(self, branch_url):
        from lp_registration import BranchRegistrationRequest
        BranchRegistrationRequest(branch_url)

register_command(cmd_register_branch)

def test_suite():
    """Called by bzrlib to fetch tests for this plugin"""
    from unittest import TestSuite, TestLoader
    import test_register
    return TestLoader().loadTestsFromModule(test_register)
