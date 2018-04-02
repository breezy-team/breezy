# Copyright (C) 2010, 2016 Canonical Ltd
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

"""Blacbox tests for the test-script command."""

import os

from breezy import (
    tests,
    )
from breezy.tests import (
    script,
    )


class TestTestScript(tests.TestCaseInTempDir):

    def test_unknnown_file(self):
        self.run_bzr(['test-script', 'I-do-not-exist'], retcode=3)

    def test_empty_file(self):
        self.build_tree_contents([('script', b'')])
        out, err = self.run_bzr(['test-script', 'script'])
        out_lines = out.splitlines()
        self.assertStartsWith(out_lines[-3], 'Ran 1 test in ')
        self.assertEqual('OK', out_lines[-1])
        self.assertEqual('', err)

    def test_simple_file(self):
        self.build_tree_contents([('script', b'''
$ echo hello world
hello world
''')])
        out, err = self.run_bzr(['test-script', 'script'])
        out_lines = out.splitlines()
        self.assertStartsWith(out_lines[-3], 'Ran 1 test in ')
        self.assertEqual('OK', out_lines[-1])
        self.assertEqual('', err)

    def test_null_output(self):
        self.build_tree_contents([('script', b'''
$ echo hello world
''')])
        out, err = self.run_bzr(['test-script', 'script', '--null-output'])
        out_lines = out.splitlines()
        self.assertStartsWith(out_lines[-3], 'Ran 1 test in ')
        self.assertEqual('OK', out_lines[-1])
        self.assertEqual('', err)

    def test_failing_script(self):
        self.build_tree_contents([('script', b'''
$ echo hello foo
hello bar
''')])
        out, err = self.run_bzr(['test-script', 'script'], retcode=1)
        out_lines = out.splitlines()
        self.assertStartsWith(out_lines[-3], 'Ran 1 test in ')
        self.assertEqual('FAILED (failures=1)', out_lines[-1])
        self.assertEqual('', err)
