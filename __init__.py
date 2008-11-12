# Copyright (C) 2006 Canonical Ltd
# Authors: Robert Collins <robert.collins@canonical.com>
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


"""A GIT branch and repository format implementation for bzr."""

from bzrlib import bzrdir, log
from bzrlib.plugins.git.dir import GitBzrDirFormat

bzrdir.format_registry.register(
    'git', GitBzrDirFormat,
    help='GIT repository.', 
    native=False, experimental=True,
    )

bzrdir.BzrDirFormat.register_control_format(GitBzrDirFormat)

def show_git_properties(rev):
    from bzrlib.plugins.git.foreign import show_foreign_properties
    from bzrlib.plugins.git.mapping import mapping_registry
    return show_foreign_properties(mapping_registry, rev)

log.properties_handler_registry.register_lazy("git",
                                              "bzrlib.plugins.git",
                                              "show_git_properties")

def test_suite():
    from bzrlib.plugins.git import tests
    return tests.test_suite()
