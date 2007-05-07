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

"""Tests for the compiled dirstate helpers."""

from bzrlib import (
    tests,
    )
try:
    from bzrlib.compiled import dirstate_helpers
except ImportError:
    have_dirstate_helpers = False
else:
    have_dirstate_helpers = True
from bzrlib.tests import test_dirstate


class _CompiledDirstateHelpersFeature(tests.Feature):
    def _probe(self):
        return have_dirstate_helpers

    def feature_name(self):
        return 'bzrlib.compiled.dirstate_helpers'

CompiledDirstateHelpersFeature = _CompiledDirstateHelpersFeature()


class TestCCmpByDirs(test_dirstate.TestCmpByDirs):
    """Test the C implementation of cmp_by_dirs"""

    _test_needs_features = [CompiledDirstateHelpersFeature]

    def get_cmp_by_dirs(self):
        return dirstate_helpers.c_cmp_by_dirs


class TestCompiledBisectDirblock(test_dirstate.TestBisectDirblock):
    """Test that bisect_dirblock() returns the expected values.

    bisect_dirblock is intended to work like bisect.bisect_left() except it
    knows it is working on dirblocks and that dirblocks are sorted by ('path',
    'to', 'foo') chunks rather than by raw 'path/to/foo'.

    This runs all the normal tests that TestBisectDirblock did, but uses the
    compiled version.
    """

    _test_needs_features = [CompiledDirstateHelpersFeature]

    def get_bisect_dirblock(self):
        return dirstate_helpers.c_bisect_dirblock
