# Copyright (C) 2008-2011, 2016 Canonical Ltd
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


"""Tests for log+ transport decorator."""

from breezy import transport
from breezy.tests import TestCaseWithMemoryTransport

from ..trace import mutter
from ..transport.log import TransportLogDecorator


class TestTransportLog(TestCaseWithMemoryTransport):
    def test_log_transport(self):
        base_transport = self.get_transport("")
        logging_transport = transport.get_transport("log+" + base_transport.base)

        # operations such as mkdir are logged
        mutter("where are you?")
        logging_transport.mkdir("subdir")
        log = self.get_log()
        # GZ 2017-05-24: Used to expect abspath logged, logger needs fixing.
        self.assertContainsRe(log, r"mkdir subdir")
        self.assertContainsRe(log, "  --> None")
        # they have the expected effect
        self.assertTrue(logging_transport.has("subdir"))
        # and they operate on the underlying transport
        self.assertTrue(base_transport.has("subdir"))

    def test_log_readv(self):
        # see <https://bugs.launchpad.net/bzr/+bug/340347>

        # transports are not required to return a generator, but we
        # specifically want to check that those that do cause it to be passed
        # through, for the sake of minimum interference
        base_transport = DummyReadvTransport()
        # construct it directly to avoid needing the dummy transport to be
        # registered etc
        logging_transport = TransportLogDecorator(
            "log+dummy:///", _decorated=base_transport
        )

        result = base_transport.readv("foo", [(0, 10)])
        # sadly there's no types.IteratorType, and GeneratorType is too
        # specific
        next(result)

        result = logging_transport.readv("foo", [(0, 10)])
        self.assertEqual(list(result), [(0, "abcdefghij")])


class DummyReadvTransport:
    base = "dummy:///"

    def readv(self, filename, offset_length_pairs):
        yield (0, "abcdefghij")

    def abspath(self, path):
        return self.base + path
