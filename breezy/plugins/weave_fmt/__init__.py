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

# Since we are a built-in plugin we share the breezy version
from ... import branch as _mod_branch
from ... import (
    controldir,
    version_info,  # noqa: F401
)
from ... import repository as _mod_repository
from ... import workingtree as _mod_workingtree
from ...bzr import BzrProber, register_metadir, serializer

# Pre-0.8 formats that don't have a disk format string (because they are
# versioned by the matching control directory). We use the control directories
# disk format string as a key for the network_name because they meet the
# constraints (simple string, unique, immutable).
_mod_repository.network_format_registry.register_lazy(
    b"Bazaar-NG branch, format 5\n",
    "breezy.plugins.weave_fmt.repository",
    "RepositoryFormat5",
)
_mod_repository.network_format_registry.register_lazy(
    b"Bazaar-NG branch, format 6\n",
    "breezy.plugins.weave_fmt.repository",
    "RepositoryFormat6",
)

# weave formats which has no format string and are not discoverable or independently
# creatable on disk, so are not registered in format_registry.  They're
# all in breezy.plugins.weave_fmt.repository now.  When an instance of one of these is
# needed, it's constructed directly by the BzrDir.  Non-native formats where
# the repository is not separately opened are similar.

_mod_repository.format_registry.register_lazy(
    b"Bazaar-NG Repository format 7",
    "breezy.plugins.weave_fmt.repository",
    "RepositoryFormat7",
)

_mod_repository.format_registry.register_extra_lazy(
    "breezy.plugins.weave_fmt.repository", "RepositoryFormat4"
)
_mod_repository.format_registry.register_extra_lazy(
    "breezy.plugins.weave_fmt.repository", "RepositoryFormat5"
)
_mod_repository.format_registry.register_extra_lazy(
    "breezy.plugins.weave_fmt.repository", "RepositoryFormat6"
)


# The pre-0.8 formats have their repository format network name registered in
# repository.py. MetaDir formats have their repository format network name
# inferred from their disk format string.
controldir.format_registry.register_lazy(
    "weave",
    "breezy.plugins.weave_fmt.bzrdir",
    "BzrDirFormat6",
    "Pre-0.8 format.  Slower than knit and does not"
    " support checkouts or shared repositories.",
    hidden=True,
    deprecated=True,
)
register_metadir(
    controldir.format_registry,
    "metaweave",
    "breezy.plugins.weave_fmt.repository.RepositoryFormat7",
    "Transitional format in 0.8.  Slower than knit.",
    branch_format="breezy.bzr.fullhistory.BzrBranchFormat5",
    tree_format="breezy.bzr.workingtree_3.WorkingTreeFormat3",
    hidden=True,
    deprecated=True,
)


BzrProber.formats.register_lazy(
    b"Bazaar-NG branch, format 0.0.4\n",
    "breezy.plugins.weave_fmt.bzrdir",
    "BzrDirFormat4",
)
BzrProber.formats.register_lazy(
    b"Bazaar-NG branch, format 5\n", "breezy.plugins.weave_fmt.bzrdir", "BzrDirFormat5"
)
BzrProber.formats.register_lazy(
    b"Bazaar-NG branch, format 6\n", "breezy.plugins.weave_fmt.bzrdir", "BzrDirFormat6"
)


_mod_branch.format_registry.register_extra_lazy(
    "breezy.plugins.weave_fmt.branch", "BzrBranchFormat4"
)
_mod_branch.network_format_registry.register_lazy(
    b"Bazaar-NG branch, format 6\n",
    "breezy.plugins.weave_fmt.branch",
    "BzrBranchFormat4",
)


_mod_workingtree.format_registry.register_extra_lazy(
    "breezy.plugins.weave_fmt.workingtree", "WorkingTreeFormat2"
)

serializer.revision_format_registry.register_lazy(
    "4", "breezy.plugins.weave_fmt.xml4", "revision_serializer_v4"
)
serializer.inventory_format_registry.register_lazy(
    "4", "breezy.plugins.weave_fmt.xml4", "inventory_serializer_v4"
)


def load_tests(loader, basic_tests, pattern):
    testmod_names = [
        "test_bzrdir",
        "test_repository",
        "test_store",
        "test_workingtree",
    ]
    for tmn in testmod_names:
        basic_tests.addTest(loader.loadTestsFromName(f"{__name__}.{tmn}"))
    return basic_tests
