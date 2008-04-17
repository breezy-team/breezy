# Copyright (C) 2008 Canonical Ltd
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

import StringIO
from bzrlib.filters import (
    ContentFilter,
    filtered_input_file,
    filtered_output_lines,
    )
from bzrlib.tests import TestCase


# test filter stacks
_swapcase = lambda(lines): [s.swapcase() for s in lines]
_addjunk = lambda(lines): ['q'+s for s in lines]
_deljunk = lambda(lines): [s[1:] for s in lines]
_stack_1 = [
    ContentFilter(_swapcase, _swapcase),
    ]
_stack_2 = [
    ContentFilter(_swapcase, _swapcase),
    ContentFilter(_addjunk, _deljunk),
    ]

# test data
_sample_external = ['Hello\n', 'World\n']
_internal_1 = ['hELLO\n', 'wORLD\n']
_internal_2 = ['qhELLO\n', 'qwORLD\n']


class TestFilteredInput(TestCase):

    def test_filtered_input_file(self):
        # test an empty stack returns the same result
        external = ''.join(_sample_external)
        f = StringIO.StringIO(external)
        self.assertEqual(external, filtered_input_file(f, None).read())
        # test a single item filter stack
        f = StringIO.StringIO(external)
        expected = ''.join(_internal_1)
        self.assertEqual(expected, filtered_input_file(f, _stack_1).read())
        # test a multi item filter stack
        f = StringIO.StringIO(external)
        expected = ''.join(_internal_2)
        self.assertEqual(expected, filtered_input_file(f, _stack_2).read())


class TestFilteredOutput(TestCase):

    def test_filtered_output_lines(self):
        # test an empty stack returns the same result
        self.assertEqual(_sample_external, list(filtered_output_lines(
            _sample_external, None)))
        # test a single item filter stack
        self.assertEqual(_sample_external, list(filtered_output_lines(
            _internal_1, _stack_1)))
        # test a multi item filter stack
        self.assertEqual(_sample_external, list(filtered_output_lines(
            _internal_2, _stack_2)))
