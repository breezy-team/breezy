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
from bzrlib.repository import format_registry as repo_registry
format_registry.register_metadir('gc-no-rich-root',
    'bzrlib.plugins.groupcompress.repofmt.RepositoryFormatPackGCPlain',
    help='pack-1.9 with xml inv, group compress '
        'Please read '
        'http://doc.bazaar-vcs.org/latest/developers/development-repo.html '
        'before use.',
    branch_format='bzrlib.branch.BzrBranchFormat7',
    tree_format='bzrlib.workingtree.WorkingTreeFormat5',
    hidden=False,
    experimental=True,
    )

from bzrlib.repository import format_registry as repo_registry

# if we have chk support in bzrlib, use it. Otherwise don't register cause 'bzr
# info' will die horribly.
try:
    from bzrlib.repofmt.pack_repo import (
    RepositoryFormatPackDevelopment5,
    RepositoryFormatPackDevelopment5Hash16,
    RepositoryFormatPackDevelopment5Hash255,
    )
    format_registry.register_metadir('gc-chk16',
        'bzrlib.plugins.groupcompress.repofmt.RepositoryFormatPackGCCHK16',
        help='pack-1.9 with 16-way hashed CHK inv, group compress, rich roots. '
            'Please read '
            'http://doc.bazaar-vcs.org/latest/developers/development-repo.html '
            'before use.',
        branch_format='bzrlib.branch.BzrBranchFormat7',
        tree_format='bzrlib.workingtree.WorkingTreeFormat5',
        hidden=False,
        experimental=True,
        )
    repo_registry.register_lazy(
        'Bazaar development format - hash16chk+gc rich-root (needs bzr.dev from 1.13)\n',
        'bzrlib.plugins.groupcompres.repofmt',
        'RepositoryFormatPackGCCHK16',
        )
    format_registry.register_metadir('gc-chk255',
        'bzrlib.plugins.groupcompress.repofmt.RepositoryFormatPackGCCHK255',
        help='pack-1.9 with 255-way hashed CHK inv, group compress, rich roots '
            'Please read '
            'http://doc.bazaar-vcs.org/latest/developers/development-repo.html '
            'before use.',
        branch_format='bzrlib.branch.BzrBranchFormat7',
        tree_format='bzrlib.workingtree.WorkingTreeFormat5',
        hidden=False,
        experimental=True,
        )
    repo_registry.register_lazy(
        'Bazaar development format - hash255chk+gc rich-root (needs bzr.dev from 1.13)\n',
        'bzrlib.plugins.groupcompress.repofmt',
        'RepositoryFormatPackGCCHK255',
        )
except ImportError:
    pass

repo_registry.register_lazy(
    'Bazaar development format - btree+gc (needs bzr.dev from 1.13)\n',
    'bzrlib.plugins.groupcompress.repofmt',
    'RepositoryFormatPackGCPlain',
    )


def load_tests(standard_tests, module, loader):
    standard_tests.addTests(loader.loadTestsFromModuleNames(
        ['bzrlib.plugins.groupcompress.tests']))
    return standard_tests
