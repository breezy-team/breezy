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

"""A grouping of Exceptions for bzr-git"""

from bzrlib import errors as bzr_errors


class BzrGitError(bzr_errors.BzrError):
    """The base-level exception for bzr-git errors."""


class GitCommandError(BzrGitError):
    """Raised when spawning 'git' does not return normally."""

    _fmt = 'Command failed (%(returncode)s): command %(command)s\n%(stderr)s'

    def __init__(self, command, returncode, stderr):
        self.command = command
        self.returncode = returncode
        self.stderr = stderr
