# Copyright (C) 2007-2020 Jelmer Vernoij <jelmer@jelmer.uk>
# Copyright (C) 2006, 2007 Canonical Ltd
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

"""The basic test suite for bzr."""

from __future__ import absolute_import

from io import BytesIO

import time

from ... import (
    errors as bzr_errors,
    tests,
    )
from ...tests.features import (
    Feature,
    ModuleAvailableFeature,
    )

TestCase = tests.TestCase
TestCaseInTempDir = tests.TestCaseInTempDir
TestCaseWithTransport = tests.TestCaseWithTransport
TestCaseWithMemoryTransport = tests.TestCaseWithMemoryTransport


def test_suite():
    loader = tests.TestUtil.TestLoader()

    suite = tests.TestUtil.TestSuite()

    testmod_names = [
        'test_dirstate',
        'per_bzrdir',
        'per_inventory',
        'per_pack_repository',
        'per_repository_chk',
        'per_repository_vf',
        'per_versionedfile',
        'test__btree_serializer',
        'test__chk_map',
        'test__dirstate_helpers',
        'test__groupcompress',
        'test_btree_index',
        'test_chk_map',
        'test_chk_serializer',
        'test_groupcompress',
        'test_knit',
        'test_matchers',
        'test_pack',
        'test_remote',
        'test_smart',
        'test_smart_request',
        'test_smart_signals',
        'test_smart_transport',
        'test_tags',
        'test_versionedfile',
        'test_weave',
        'test_xml',
        ]
    testmod_names = ['%s.%s' % (__name__, t) for t in testmod_names]
    suite.addTests(loader.loadTestsFromModuleNames(testmod_names))

    return suite
