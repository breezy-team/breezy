# groupcompress, a bzr plugin providing new compression logic.
# Copyright (C) 2008 Canonical Limited.
# 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as published
# by the Free Software Foundation.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301 USA
# 

"""groupcompress will provide smaller bzr repositories.

groupcompress
+++++++++++++

bzr repositories are larger than we want them to be; this tries to implement
some of the things we have been considering. The primary logic is deep in the
VersionedFiles abstraction, and at this point there is no user visible 
facilities.

Documentation
=============

See DESIGN in the groupcompress source.
"""



from bzrlib.bzrdir import format_registry
format_registry.register_metadir('gc-plain',
    'bzrlib.plugins.groupcompress.repofmt.RepositoryFormatPackGCPlain',
    help='pack-0.92 with btree index and group compress. '
        'Please read '
        'http://doc.bazaar-vcs.org/latest/developers/development-repo.html '
        'before use.',
    branch_format='bzrlib.branch.BzrBranchFormat6',
    tree_format='bzrlib.workingtree.WorkingTreeFormat4',
    hidden=False,
    experimental=True,
    )

format_registry.register_metadir('gc-rich-root',
    'bzrlib.plugins.groupcompress.repofmt.RepositoryFormatPackGCRichRoot',
    help='rich-root-pack with btree index and group compress. '
        'Please read '
        'http://doc.bazaar-vcs.org/latest/developers/development-repo.html '
        'before use.',
    branch_format='bzrlib.branch.BzrBranchFormat6',
    tree_format='bzrlib.workingtree.WorkingTreeFormat4',
    hidden=False,
    experimental=True,
    )

format_registry.register_metadir('gc-subtrees',
    'bzrlib.plugins.groupcompress.repofmt.RepositoryFormatPackGCSubtrees',
    help='pack-0.92-subtress with btree index and group compress. '
        'Please read '
        'http://doc.bazaar-vcs.org/latest/developers/development-repo.html '
        'before use.',
    branch_format='bzrlib.branch.BzrBranchFormat6',
    tree_format='bzrlib.workingtree.WorkingTreeFormat4',
    hidden=False,
    experimental=True,
    )

from bzrlib.repository import format_registry as repo_registry
repo_registry.register_lazy(
    'Bazaar development format - btree+gc (needs bzr.dev from 1.6)\n',
    'bzrlib.plugins.groupcompress.repofmt',
    'RepositoryFormatPackGCPlain',
    )
from bzrlib.repository import format_registry as repo_registry
repo_registry.register_lazy(
    'Bazaar development format - btree+gc-rich-root (needs bzr.dev from 1.6)\n',
    'bzrlib.plugins.groupcompress.repofmt',
    'RepositoryFormatPackGCRichRoot',
    )

from bzrlib.repository import format_registry as repo_registry
repo_registry.register_lazy(
    'Bazaar development format - btree+gc-subtrees (needs bzr.dev from 1.6)\n',
    'bzrlib.plugins.groupcompress.repofmt',
    'RepositoryFormatPackGCSubtrees',
    )



def test_suite():
    # Thunk across to load_tests for niceness with older bzr versions
    from bzrlib.tests import TestLoader
    loader = TestLoader()
    return loader.loadTestsFromModuleNames(['bzrlib.plugins.groupcompress'])


def load_tests(standard_tests, module, loader):
    standard_tests.addTests(loader.loadTestsFromModuleNames(
        ['bzrlib.plugins.groupcompress.tests']))
    return standard_tests
