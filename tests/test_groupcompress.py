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
from bzrlib.osutils import sha_strings
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


class TestGroupCompressor(TestCaseWithTransport):
    """Tests for GroupCompressor"""

    def test_empty_delta(self):
        compressor = groupcompress.GroupCompressor(True)
        self.assertEqual([], compressor.lines)

    def test_one_nosha_delta(self):
        # diff against NUKK
        compressor = groupcompress.GroupCompressor(True)
        sha1, end_point = compressor.compress(('label',),
            ['strange\n', 'common\n'], None)
        self.assertEqual(sha_strings(['strange\n', 'common\n']), sha1)
        expected_lines = [
            'label: label\n',
            'sha1: %s\n' % sha1,
            '0,0,3\n',
            'strange\n',
            'common\n',
            '\n', # the last \n in a text is removed, which allows safe
            # serialisation of lines without trailing \n.
            ]
        self.assertEqual(expected_lines, compressor.lines)
        self.assertEqual(sum(map(len, expected_lines)), end_point)

    def test_two_nosha_delta(self):
        compressor = groupcompress.GroupCompressor(True)
        sha1_1, _ = compressor.compress(('label',),
            ['strange\n', 'common\n'], None)
        sha1_2, end_point = compressor.compress(('newlabel',),
            ['common\n', 'different\n'], None)
        self.assertEqual(sha_strings(['common\n', 'different\n']), sha1_2)
        expected_lines = [
            'label: label\n',
            'sha1: %s\n' % sha1_1,
            '0,0,3\n',
            'strange\n',
            'common\n',
            '\n',
            'label: newlabel\n',
            'sha1: %s\n' % sha1_2,
            # Delete what we don't want. Perhaps we want an implicit
            # delete all to keep from bloating with useless delete
            # instructions.
            '0,4,0\n',
            # add the new lines
            '5,5,1\n',
            'different\n',
            ]
        self.assertEqual(expected_lines, compressor.lines)
        self.assertEqual(sum(map(len, expected_lines)), end_point)

    def test_three_nosha_delta(self):
        # The first interesting test: make a change that should use lines from
        # both parents.
        compressor = groupcompress.GroupCompressor(True)
        sha1_1, end_point = compressor.compress(('label',),
            ['strange\n', 'common\n'], None)
        sha1_2, _ = compressor.compress(('newlabel',),
            ['common\n', 'different\n', 'moredifferent\n'], None)
        sha1_3, end_point = compressor.compress(('label3',),
            ['new\n', 'common\n', 'different\n', 'moredifferent\n'], None)
        self.assertEqual(
            sha_strings(['new\n', 'common\n', 'different\n', 'moredifferent\n']),
            sha1_3)
        expected_lines = [
            'label: label\n',
            'sha1: %s\n' % sha1_1,
            '0,0,3\n',
            'strange\n',
            'common\n',
            '\n',
            'label: newlabel\n',
            'sha1: %s\n' % sha1_2,
            # Delete what we don't want. Perhaps we want an implicit
            # delete all to keep from bloating with useless delete
            # instructions.
            '0,4,0\n',
            # add the new lines
            '5,5,2\n',
            'different\n',
            'moredifferent\n',
            'label: label3\n',
            'sha1: %s\n' % sha1_3,
            # Delete what we don't want. Perhaps we want an implicit
            # delete all to keep from bloating with useless delete
            # instructions.
            # replace 'strange' with 'new'
            '0,4,1\n',
            'new\n',
            # delete from after common up to differnet
            '5,10,0\n',
            # add new \n
            '12,12,1\n',
            '\n',
            ]
        self.assertEqualDiff(''.join(expected_lines), ''.join(compressor.lines))
        self.assertEqual(sum(map(len, expected_lines)), end_point)

    def test_stats(self):
        compressor = groupcompress.GroupCompressor(True)
        compressor.compress(('label',),
            ['strange\n', 'common\n'], None)
        compressor.compress(('newlabel',),
            ['common\n', 'different\n', 'moredifferent\n'], None)
        compressor.compress(('label3',),
            ['new\n', 'common\n', 'different\n', 'moredifferent\n'], None)
        self.assertAlmostEqual(0.3, compressor.ratio(), 1)
