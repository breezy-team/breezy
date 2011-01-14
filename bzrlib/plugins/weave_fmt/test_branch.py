# Copyright (C) 2006-2011 Canonical Ltd
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

"""Tests for weave-era Branch implementations.

For interface tests see tests/per_branch/*.py.
"""

from bzrlib import tests
from bzrlib.tests.per_branch import (
    make_scenarios,
    per_branch_tests,
    )

from bzrlib.plugins.weave_fmt.branch import BzrBranchFormat4


def load_tests(basic_tests, module, loader):
    legacy_formats = [BzrBranchFormat4()]
    return tests.multiply_tests(per_branch_tests(loader), make_scenarios(None,
        None, [(format, format._matchingbzrdir) for format in legacy_formats]),
        basic_tests)
