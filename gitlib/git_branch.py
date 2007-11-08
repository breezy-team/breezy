# Copyright (C) 2007 Canonical Ltd
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

"""An adapter between a Git Branch and a Bazaar Branch"""

from bzrlib import (
    branch,
    config,
    )
from bzrlib.decorators import needs_read_lock


class GitBranchConfig(config.BranchConfig):
    """BranchConfig that uses locations.conf in place of branch.conf"""

    def __init__(self, branch):
        config.BranchConfig.__init__(self, branch)
        # do not provide a BranchDataConfig
        self.option_sources = self.option_sources[0], self.option_sources[2]

    def set_user_option(self, name, value, local=False):
        """Force local to True"""
        config.BranchConfig.set_user_option(self, name, value, local=True)


class GitBranchFormat(branch.BranchFormat):

    def get_branch_description(self):
        return 'Git Branch'


class GitBranch(branch.Branch):
    """An adapter to git repositories for bzr Branch objects."""

    def __init__(self, gitdir, lockfiles):
        from bzrlib.plugins.git.gitlib import git_repository
        self.bzrdir = gitdir
        self.control_files = lockfiles
        self.repository = git_repository.GitRepository(gitdir, lockfiles)
        self.base = gitdir.root_transport.base
        if '.git' not in gitdir.root_transport.list_dir('.'):
            raise errors.NotBranchError(self.base)
        self._format = GitBranchFormat()

    def lock_write(self):
        self.control_files.lock_write()

    @needs_read_lock
    def last_revision(self):
        # perhaps should escape this ?
        return bzrrevid_from_git(self.repository.git.get_head())

    @needs_read_lock
    def revision_history(self):
        node = self.last_revision()
        ancestors = self.repository.get_revision_graph(node)
        history = []
        while node is not None:
            history.append(node)
            if len(ancestors[node]) > 0:
                node = ancestors[node][0]
            else:
                node = None
        return list(reversed(history))

    def get_config(self):
        return GitBranchConfig(self)

    def lock_read(self):
        self.control_files.lock_read()

    def unlock(self):
        self.control_files.unlock()

    def get_push_location(self):
        """See Branch.get_push_location."""
        push_loc = self.get_config().get_user_option('push_location')
        return push_loc

    def set_push_location(self, location):
        """See Branch.set_push_location."""
        self.get_config().set_user_option('push_location', location, 
                                          local=True)


