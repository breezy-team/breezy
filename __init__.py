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

See DESIGN in the groupcompress osurc.e
"""
def test_suite():
    # Thunk across to load_tests for niceness with older bzr versions
    from bzrlib.tests import TestLoader
    loader = TestLoader()
    return loader.loadTestsFromModuleNames(['bzrlib.plugins.groupcompress'])


def load_tests(standard_tests, module, loader):
    standard_tests.addTests(loader.loadTestsFromModuleNames(
        ['bzrlib.plugins.groupcompress.tests']))
    return standard_tests
