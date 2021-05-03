# Copyright (C) 2010-2018 Jelmer Vernooij <jelmer@jelmer.uk>

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

"""Help information."""

help_git = """Using Bazaar with Git.

The bzr-git plugin provides support for using Bazaar with local and remote
Git repositories, as just another format. You can clone, pull from and
push to git repositories as you would with any native Bazaar branch.

The bzr-git plugin also adds three new bzr subcommands:

 * bzr git-objects: Extracts Git objects out of a Bazaar repository
 * bzr git-refs: Display Git refs from a Bazaar branch or repository
 * bzr git-import: Imports a local or remote Git repository to a set of Bazaar
                   branches

The 'git:' revision specifier can be used to find revisions by short or long
GIT SHA1.
"""
