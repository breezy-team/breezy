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

"""Tests for group compression."""

import zlib

from bzrlib import tests
from bzrlib.plugins.groupcompress import errors, groupcompress
from bzrlib.tests import (
    TestCaseWithTransport,
    TestScenarioApplier,
    adapt_tests,
    )
from bzrlib.transport import get_transport


def load_tests(standard_tests, module, loader):
    from bzrlib.tests.test_versionedfile import TestVersionedFiles
    vf_interface_tests = loader.loadTestsFromTestCase(TestVersionedFiles)
    cleanup_pack_group = groupcompress.cleanup_pack_group
    make_pack_factory = groupcompress.make_pack_factory
    group_scenario = ('groupcompress-nograph', {
            'cleanup':cleanup_pack_group,
            'factory':make_pack_factory(False, False, 1),
            'graph': False,
            'key_length':1,
            }
        )
    applier = TestScenarioApplier()
    applier.scenarios = [group_scenario]
    adapt_tests(vf_interface_tests, applier, standard_tests)
    return standard_tests


