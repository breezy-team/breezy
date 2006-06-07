# Copyright (C) 2006 Jelmer Vernooij <jelmer@samba.org>
# cmd_submit() based on cmd_commit() from bzrlib.builtins

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from bzrlib.commands import Command, register_command
from bzrlib.builtins import tree_files
from bzrlib.bzrdir import BzrDir
from bzrlib.branch import Branch

class cmd_submit(Command):
    """Submit a revision to another (related) branch.
    
    This is basically a push to a Subversion repository, 
    without the guarantee that a pull from that same repository 
    is a no-op.
    """

    takes_args = ["location?"]
    takes_options = ["revision", "verbose"]
    
    def run(self, revid=None, verbose=True, location=None):
        (branch, _) = Branch.open_containing(".")

        if location is None:
            location = branch.get_parent()

        if location is None:
            raise BzrError("No location specified and no default location set on branch")

        parent_branch = Branch.open(location)

        if revid is None:
            revid = branch.last_revision()

        parent_branch.submit(branch, revid)

register_command(cmd_submit)
