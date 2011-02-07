# Copyright (C) 2010 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Weave formats.

These were formats present in pre-1.0 version of Bazaar.
"""

from bzrlib import (
    branch,
    bzrdir,
    controldir,
    repository,
    workingtree,
    )

# Pre-0.8 formats that don't have a disk format string (because they are
# versioned by the matching control directory). We use the control directories
# disk format string as a key for the network_name because they meet the
# constraints (simple string, unique, immutable).
repository.network_format_registry.register_lazy(
    "Bazaar-NG branch, format 5\n",
    'bzrlib.plugins.weave_fmt.repository',
    'RepositoryFormat5',
)
repository.network_format_registry.register_lazy(
    "Bazaar-NG branch, format 6\n",
    'bzrlib.plugins.weave_fmt.repository',
    'RepositoryFormat6',
)

# weave formats which has no format string and are not discoverable or independently
# creatable on disk, so are not registered in format_registry.  They're
# all in bzrlib.plugins.weave_fmt.repository now.  When an instance of one of these is
# needed, it's constructed directly by the BzrDir.  Non-native formats where
# the repository is not separately opened are similar.

repository.format_registry.register_lazy(
    'Bazaar-NG Repository format 7',
    'bzrlib.plugins.weave_fmt.repository',
    'RepositoryFormat7'
    )


# The pre-0.8 formats have their repository format network name registered in
# repository.py. MetaDir formats have their repository format network name
# inferred from their disk format string.
controldir.format_registry.register_lazy('weave',
    "bzrlib.plugins.weave_fmt.bzrdir", "BzrDirFormat6",
    'Pre-0.8 format.  Slower than knit and does not'
    ' support checkouts or shared repositories.',
    hidden=True,
    deprecated=True)
bzrdir.register_metadir(controldir.format_registry, 'metaweave',
    'bzrlib.plugins.weave_fmt.repository.RepositoryFormat7',
    'Transitional format in 0.8.  Slower than knit.',
    branch_format='bzrlib.branch.BzrBranchFormat5',
    tree_format='bzrlib.workingtree.WorkingTreeFormat3',
    hidden=True,
    deprecated=True)


from bzrlib.plugins.weave_fmt.bzrdir import BzrDirFormat4, BzrDirFormat5, BzrDirFormat6
bzrdir.BzrDirFormat.register_format(BzrDirFormat4())
bzrdir.BzrDirFormat.register_format(BzrDirFormat5())
bzrdir.BzrDirFormat.register_format(BzrDirFormat6())

from bzrlib.plugins.weave_fmt.branch import BzrBranchFormat4
branch.BranchFormat.register_extra_format(BzrBranchFormat4())

from bzrlib.plugins.weave_fmt.workingtree import WorkingTreeFormat2
workingtree.WorkingTreeFormat.register_extra_format(WorkingTreeFormat2())

def load_tests(basic_tests, module, loader):
    testmod_names = [
        'test_bzrdir',
        'test_repository',
        'test_workingtree',
        ]
    basic_tests.addTest(loader.loadTestsFromModuleNames(
            ["%s.%s" % (__name__, tmn) for tmn in testmod_names]))
    return basic_tests
