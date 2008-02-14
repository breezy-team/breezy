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

"""Test the Import errors"""

from bzrlib import tests

from bzrlib.plugins.fastimport import (
    errors,
    )


class TestErrors(tests.TestCase):

    def test_MissingBytes(self):
        e = errors.MissingBytes(99, 10, 8)
        self.assertEqual("line 99: Unexpected EOF - expected 10 bytes, found 8",
            str(e))

    def test_MissingTerminator(self):
        e = errors.MissingTerminator(99, '---')
        self.assertEqual("line 99: Unexpected EOF - expected '---' terminator",
            str(e))

    def test_InvalidCommand(self):
        e = errors.InvalidCommand(99, 'foo')
        self.assertEqual("line 99: Invalid command 'foo'",
            str(e))

    def test_MissingSection(self):
        e = errors.MissingSection(99, 'foo', 'bar')
        self.assertEqual("line 99: Command foo is missing section bar",
            str(e))

    def test_BadFormat(self):
        e = errors.BadFormat(99, 'foo', 'bar', 'xyz')
        self.assertEqual("line 99: Bad format for section bar in "
            "command foo: found 'xyz'",
            str(e))

    def test_InvalidTimezone(self):
        e = errors.InvalidTimezone(99, 'aa:bb')
        self.assertEqual('aa:bb', e.timezone)
        self.assertEqual('', e.reason)
        self.assertEqual("line 99: Timezone 'aa:bb' could not be converted.",
            str(e))
        e = errors.InvalidTimezone(99, 'aa:bb', 'Non-numeric hours')
        self.assertEqual('aa:bb', e.timezone)
        self.assertEqual(' Non-numeric hours', e.reason)
        self.assertEqual("line 99: Timezone 'aa:bb' could not be converted."
             " Non-numeric hours",
             str(e))

    def test_UnknownDateFormat(self):
        e = errors.UnknownDateFormat('aaa')
        self.assertEqual("Unknown date format 'aaa'", str(e))

    def test_MissingHandler(self):
        e = errors.MissingHandler('foo')
        self.assertEqual("Missing handler for command foo", str(e))
