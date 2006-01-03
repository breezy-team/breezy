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
                           TransportNotPossible, ConnectionError)
from bzrlib.tests import TestCase, TestCaseInTempDir
from bzrlib.tests.HTTPTestUtil import TestCaseWithWebserver
from bzrlib.transport import memory, urlescape
from bzrlib.osutils import pathjoin


def _append(fn, txt):
    """Append the given text (file-like object) to the supplied filename."""
    f = open(fn, 'ab')
    f.write(txt)
    f.flush()
    f.close()
    del f


if sys.platform != 'win32':
    def check_mode(test, path, mode):
        """Check that a particular path has the correct mode."""
        actual_mode = stat.S_IMODE(os.stat(path).st_mode)
        test.assertEqual(mode, actual_mode,
            'mode of %r incorrect (%o != %o)' % (path, mode, actual_mode))
else:
    def check_mode(test, path, mode):
        """On win32 chmod doesn't have any effect, 
        so don't actually check anything
        """
        return


class TestTransport(TestCase):
    """Test the non transport-concrete class functionality."""

    def test_urlescape(self):
        self.assertEqual('%25', urlescape('%'))


class TestTransportMixIn(object):
    """Subclass this, and it will provide a series of tests for a Transport.
    It assumes that the Transport object is connected to the 
    current working directory.  So that whatever is done 
    through the transport, should show up in the working 
    directory, and vice-versa.

    This also tests to make sure that the functions work with both
    generators and lists (assuming iter(list) is effectively a generator)
    """
    readonly = False
    def get_transport(self):
        """Children should override this to return the Transport object.
        """
        raise NotImplementedError

    def test_put(self):
        t = self.get_transport()

        if not self.readonly:
            t.put('mode644', 'test text\n', mode=0644)
            check_mode(self, 'mode644', 0644)

            t.put('mode666', 'test text\n', mode=0666)
            check_mode(self, 'mode666', 0666)

            t.put('mode600', 'test text\n', mode=0600)
            check_mode(self, 'mode600', 0600)

            # Yes, you can put a file such that it becomes readonly
            t.put('mode400', 'test text\n', mode=0400)
            check_mode(self, 'mode400', 0400)

            t.put_multi([('mmode644', 'text\n')], mode=0644)
            check_mode(self, 'mmode644', 0644)

        # TODO: jam 20051215 test put_multi with a mode. I didn't bother because
        #                    it seems most people don't like the _multi functions


    def test_mkdir(self):
        t = self.get_transport()

        if not self.readonly:
            # Test mkdir with a mode
            t.mkdir('dmode755', mode=0755)
            check_mode(self, 'dmode755', 0755)

            t.mkdir('dmode555', mode=0555)
            check_mode(self, 'dmode555', 0555)

            t.mkdir('dmode777', mode=0777)
            check_mode(self, 'dmode777', 0777)

            t.mkdir('dmode700', mode=0700)
            check_mode(self, 'dmode700', 0700)

            # TODO: jam 20051215 test mkdir_multi with a mode
            t.mkdir_multi(['mdmode755'], mode=0755)
            check_mode(self, 'mdmode755', 0755)

    def test_copy_to(self):
        import tempfile
        from bzrlib.transport.local import LocalTransport

        t = self.get_transport()
        for mode in (0666, 0644, 0600, 0400):
            dtmp_base, local_t = get_temp_local()
            t.copy_to(files, local_t, mode=mode)
            for f in files:
                check_mode(self, os.path.join(dtmp_base, f), mode)



class MemoryTransportTest(TestCase):
    """Memory transport specific tests."""

    def test_parameters(self):
        import bzrlib.transport.memory as memory
        transport = memory.MemoryTransport()
        self.assertEqual(True, transport.listable())
        self.assertEqual(False, transport.should_cache())
        self.assertEqual(False, transport.is_readonly())
