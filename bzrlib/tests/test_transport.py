# Copyright (C) 2004, 2005 by Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


import os
import sys
import stat
from cStringIO import StringIO

from bzrlib.errors import (NoSuchFile, FileExists,
                           TransportNotPossible, ConnectionError,
                           InvalidURL)
from bzrlib.tests import TestCase
from bzrlib.transport import (_get_protocol_handlers,
                              _get_transport_modules,
                              register_lazy_transport,
                              _set_protocol_handlers,
                              urlescape, urlunescape
                              )


class TestTransport(TestCase):
    """Test the non transport-concrete class functionality."""

    def test_urlescape(self):
        self.assertEqual('%25', urlescape('%'))
        self.assertEqual('%C3%A5', urlescape(u'\xe5'))

    def test_urlunescape(self):
        self.assertEqual('%', urlunescape('%25'))
        self.assertEqual(u'\xe5', urlunescape('%C3%A5'))
        self.assertEqual('%', urlunescape(urlescape('%')))

        self.assertRaises(InvalidURL, urlunescape, u'\xe5')
        self.assertRaises(InvalidURL, urlunescape, '\xe5')
        self.assertRaises(InvalidURL, urlunescape, '%E5')

    def test_url_escape_unescape(self):
        self.assertEqual(u'\xe5', urlunescape(urlescape(u'\xe5')))
        self.assertEqual('%', urlunescape(urlescape('%')))

    def test__get_set_protocol_handlers(self):
        handlers = _get_protocol_handlers()
        self.assertNotEqual({}, handlers)
        try:
            _set_protocol_handlers({})
            self.assertEqual({}, _get_protocol_handlers())
        finally:
            _set_protocol_handlers(handlers)

    def test_get_transport_modules(self):
        handlers = _get_protocol_handlers()
        class SampleHandler(object):
            """I exist, isnt that enough?"""
        try:
            my_handlers = {}
            _set_protocol_handlers(my_handlers)
            register_lazy_transport('foo', 'bzrlib.tests.test_transport', 'TestTransport.SampleHandler')
            register_lazy_transport('bar', 'bzrlib.tests.test_transport', 'TestTransport.SampleHandler')
            self.assertEqual([SampleHandler.__module__],
                             _get_transport_modules())
        finally:
            _set_protocol_handlers(handlers)
            

class MemoryTransportTest(TestCase):
    """Memory transport specific tests."""

    def test_parameters(self):
        import bzrlib.transport.memory as memory
        transport = memory.MemoryTransport()
        self.assertEqual(True, transport.listable())
        self.assertEqual(False, transport.should_cache())
        self.assertEqual(False, transport.is_readonly())
