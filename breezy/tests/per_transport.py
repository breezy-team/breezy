# Copyright (C) 2005-2011, 2015, 2016 Canonical Ltd
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

"""Tests for Transport implementations.

Transport implementations tested here are supplied by
TransportTestProviderAdapter.
"""

from io import BytesIO
import os
import stat
import sys

from .. import (
    errors,
    osutils,
    pyutils,
    tests,
    transport as _mod_transport,
    urlutils,
    )
from ..errors import (ConnectionError,
                      PathError,
                      TransportNotPossible,
                      )
from ..osutils import getcwd
from . import (
    TestSkipped,
    TestNotApplicable,
    multiply_tests,
    )
from . import test_server
from .test_transport import TestTransportImplementation
from ..transport import (
    ConnectedTransport,
    NoSuchFile,
    FileExists,
    Transport,
    _get_transport_modules,
    )
from ..transport.memory import MemoryTransport
from ..transport.remote import RemoteTransport


def get_transport_test_permutations(module):
    """Get the permutations module wants to have tested."""
    if getattr(module, 'get_test_permutations', None) is None:
        raise AssertionError(
            "transport module %s doesn't provide get_test_permutations()"
            % module.__name__)
        return []
    return module.get_test_permutations()


def transport_test_permutations():
    """Return a list of the klass, server_factory pairs to test."""
    result = []
    for module in _get_transport_modules():
        try:
            permutations = get_transport_test_permutations(
                pyutils.get_named_object(module))
            for (klass, server_factory) in permutations:
                scenario = ('%s,%s' % (klass.__name__, server_factory.__name__),
                            {"transport_class": klass,
                             "transport_server": server_factory})
                result.append(scenario)
        except errors.DependencyNotPresent as e:
            # Continue even if a dependency prevents us
            # from adding this test
            pass
    return result


def load_tests(loader, standard_tests, pattern):
    """Multiply tests for tranport implementations."""
    result = loader.suiteClass()
    scenarios = transport_test_permutations()
    return multiply_tests(standard_tests, scenarios, result)


class TransportTests(TestTransportImplementation):

    def setUp(self):
        super(TransportTests, self).setUp()
        self.overrideEnv('BRZ_NO_SMART_VFS', None)

    def check_transport_contents(self, content, transport, relpath):
        """Check that transport.get_bytes(relpath) == content."""
        self.assertEqualDiff(content, transport.get_bytes(relpath))

    def test_ensure_base_missing(self):
        """.ensure_base() should create the directory if it doesn't exist"""
        t = self.get_transport()
        t_a = t.clone('a')
        if t_a.is_readonly():
            self.assertRaises(TransportNotPossible,
                              t_a.ensure_base)
            return
        self.assertTrue(t_a.ensure_base())
        self.assertTrue(t.has('a'))

    def test_ensure_base_exists(self):
        """.ensure_base() should just be happy if it already exists"""
        t = self.get_transport()
        if t.is_readonly():
            return

        t.mkdir('a')
        t_a = t.clone('a')
        # ensure_base returns False if it didn't create the base
        self.assertFalse(t_a.ensure_base())

    def test_ensure_base_missing_parent(self):
        """.ensure_base() will fail if the parent dir doesn't exist"""
        t = self.get_transport()
        if t.is_readonly():
            return

        t_a = t.clone('a')
        t_b = t_a.clone('b')
        self.assertRaises(NoSuchFile, t_b.ensure_base)

    def test_external_url(self):
        """.external_url either works or raises InProcessTransport."""
        t = self.get_transport()
        try:
            t.external_url()
        except errors.InProcessTransport:
            pass

    def test_has(self):
        t = self.get_transport()

        files = ['a', 'b', 'e', 'g', '%']
        self.build_tree(files, transport=t)
        self.assertEqual(True, t.has('a'))
        self.assertEqual(False, t.has('c'))
        self.assertEqual(True, t.has(urlutils.escape('%')))
        self.assertEqual(True, t.has_any(['a', 'b', 'c']))
        self.assertEqual(False, t.has_any(['c', 'd', 'f',
                                           urlutils.escape('%%')]))
        self.assertEqual(False, t.has_any(['c', 'c', 'c']))
        self.assertEqual(True, t.has_any(['b', 'b', 'b']))

    def test_has_root_works(self):
        if self.transport_server is test_server.SmartTCPServer_for_testing:
            raise TestNotApplicable(
                "SmartTCPServer_for_testing intentionally does not allow "
                "access to /.")
        current_transport = self.get_transport()
        self.assertTrue(current_transport.has('/'))
        root = current_transport.clone('/')
        self.assertTrue(root.has(''))

    def test_get(self):
        t = self.get_transport()

        files = ['a']
        content = b'contents of a\n'
        self.build_tree(['a'], transport=t, line_endings='binary')
        self.check_transport_contents(b'contents of a\n', t, 'a')
        f = t.get('a')
        self.assertEqual(content, f.read())

    def test_get_unknown_file(self):
        t = self.get_transport()
        files = ['a', 'b']
        contents = [b'contents of a\n',
                    b'contents of b\n',
                    ]
        self.build_tree(files, transport=t, line_endings='binary')
        self.assertRaises(NoSuchFile, t.get, 'c')

        def iterate_and_close(func, *args):
            for f in func(*args):
                # We call f.read() here because things like paramiko actually
                # spawn a thread to prefetch the content, which we want to
                # consume before we close the handle.
                content = f.read()
                f.close()

    def test_get_directory_read_gives_ReadError(self):
        """consistent errors for read() on a file returned by get()."""
        t = self.get_transport()
        if t.is_readonly():
            self.build_tree(['a directory/'])
        else:
            t.mkdir('a%20directory')
        # getting the file must either work or fail with a PathError
        try:
            a_file = t.get('a%20directory')
        except (errors.PathError, errors.RedirectRequested):
            # early failure return immediately.
            return
        # having got a file, read() must either work (i.e. http reading a dir
        # listing) or fail with ReadError
        try:
            a_file.read()
        except errors.ReadError:
            pass

    def test_get_bytes(self):
        t = self.get_transport()

        files = ['a', 'b', 'e', 'g']
        contents = [b'contents of a\n',
                    b'contents of b\n',
                    b'contents of e\n',
                    b'contents of g\n',
                    ]
        self.build_tree(files, transport=t, line_endings='binary')
        self.check_transport_contents(b'contents of a\n', t, 'a')

        for content, fname in zip(contents, files):
            self.assertEqual(content, t.get_bytes(fname))

    def test_get_bytes_unknown_file(self):
        t = self.get_transport()
        self.assertRaises(NoSuchFile, t.get_bytes, 'c')

    def test_get_with_open_write_stream_sees_all_content(self):
        t = self.get_transport()
        if t.is_readonly():
            return
        with t.open_write_stream('foo') as handle:
            handle.write(b'b')
            self.assertEqual(b'b', t.get_bytes('foo'))

    def test_get_bytes_with_open_write_stream_sees_all_content(self):
        t = self.get_transport()
        if t.is_readonly():
            return
        with t.open_write_stream('foo') as handle:
            handle.write(b'b')
            self.assertEqual(b'b', t.get_bytes('foo'))
            with t.get('foo') as f:
                self.assertEqual(b'b', f.read())

    def test_put_bytes(self):
        t = self.get_transport()

        if t.is_readonly():
            self.assertRaises(TransportNotPossible,
                              t.put_bytes, 'a', b'some text for a\n')
            return

        t.put_bytes('a', b'some text for a\n')
        self.assertTrue(t.has('a'))
        self.check_transport_contents(b'some text for a\n', t, 'a')

        # The contents should be overwritten
        t.put_bytes('a', b'new text for a\n')
        self.check_transport_contents(b'new text for a\n', t, 'a')

        self.assertRaises(NoSuchFile,
                          t.put_bytes, 'path/doesnt/exist/c', b'contents')

    def test_put_bytes_non_atomic(self):
        t = self.get_transport()

        if t.is_readonly():
            self.assertRaises(TransportNotPossible,
                              t.put_bytes_non_atomic, 'a', b'some text for a\n')
            return

        self.assertFalse(t.has('a'))
        t.put_bytes_non_atomic('a', b'some text for a\n')
        self.assertTrue(t.has('a'))
        self.check_transport_contents(b'some text for a\n', t, 'a')
        # Put also replaces contents
        t.put_bytes_non_atomic('a', b'new\ncontents for\na\n')
        self.check_transport_contents(b'new\ncontents for\na\n', t, 'a')

        # Make sure we can create another file
        t.put_bytes_non_atomic('d', b'contents for\nd\n')
        # And overwrite 'a' with empty contents
        t.put_bytes_non_atomic('a', b'')
        self.check_transport_contents(b'contents for\nd\n', t, 'd')
        self.check_transport_contents(b'', t, 'a')

        self.assertRaises(NoSuchFile, t.put_bytes_non_atomic, 'no/such/path',
                          b'contents\n')
        # Now test the create_parent flag
        self.assertRaises(NoSuchFile, t.put_bytes_non_atomic, 'dir/a',
                          b'contents\n')
        self.assertFalse(t.has('dir/a'))
        t.put_bytes_non_atomic('dir/a', b'contents for dir/a\n',
                               create_parent_dir=True)
        self.check_transport_contents(b'contents for dir/a\n', t, 'dir/a')

        # But we still get NoSuchFile if we can't make the parent dir
        self.assertRaises(NoSuchFile, t.put_bytes_non_atomic, 'not/there/a',
                          b'contents\n',
                          create_parent_dir=True)

    def test_put_bytes_permissions(self):
        t = self.get_transport()

        if t.is_readonly():
            return
        if not t._can_roundtrip_unix_modebits():
            # Can't roundtrip, so no need to run this test
            return
        t.put_bytes('mode644', b'test text\n', mode=0o644)
        self.assertTransportMode(t, 'mode644', 0o644)
        t.put_bytes('mode666', b'test text\n', mode=0o666)
        self.assertTransportMode(t, 'mode666', 0o666)
        t.put_bytes('mode600', b'test text\n', mode=0o600)
        self.assertTransportMode(t, 'mode600', 0o600)
        # Yes, you can put_bytes a file such that it becomes readonly
        t.put_bytes('mode400', b'test text\n', mode=0o400)
        self.assertTransportMode(t, 'mode400', 0o400)

        # The default permissions should be based on the current umask
        umask = osutils.get_umask()
        t.put_bytes('nomode', b'test text\n', mode=None)
        self.assertTransportMode(t, 'nomode', 0o666 & ~umask)

    def test_put_bytes_non_atomic_permissions(self):
        t = self.get_transport()

        if t.is_readonly():
            return
        if not t._can_roundtrip_unix_modebits():
            # Can't roundtrip, so no need to run this test
            return
        t.put_bytes_non_atomic('mode644', b'test text\n', mode=0o644)
        self.assertTransportMode(t, 'mode644', 0o644)
        t.put_bytes_non_atomic('mode666', b'test text\n', mode=0o666)
        self.assertTransportMode(t, 'mode666', 0o666)
        t.put_bytes_non_atomic('mode600', b'test text\n', mode=0o600)
        self.assertTransportMode(t, 'mode600', 0o600)
        t.put_bytes_non_atomic('mode400', b'test text\n', mode=0o400)
        self.assertTransportMode(t, 'mode400', 0o400)

        # The default permissions should be based on the current umask
        umask = osutils.get_umask()
        t.put_bytes_non_atomic('nomode', b'test text\n', mode=None)
        self.assertTransportMode(t, 'nomode', 0o666 & ~umask)

        # We should also be able to set the mode for a parent directory
        # when it is created
        t.put_bytes_non_atomic('dir700/mode664', b'test text\n', mode=0o664,
                               dir_mode=0o700, create_parent_dir=True)
        self.assertTransportMode(t, 'dir700', 0o700)
        t.put_bytes_non_atomic('dir770/mode664', b'test text\n', mode=0o664,
                               dir_mode=0o770, create_parent_dir=True)
        self.assertTransportMode(t, 'dir770', 0o770)
        t.put_bytes_non_atomic('dir777/mode664', b'test text\n', mode=0o664,
                               dir_mode=0o777, create_parent_dir=True)
        self.assertTransportMode(t, 'dir777', 0o777)

    def test_put_file(self):
        t = self.get_transport()

        if t.is_readonly():
            self.assertRaises(TransportNotPossible,
                              t.put_file, 'a', BytesIO(b'some text for a\n'))
            return

        result = t.put_file('a', BytesIO(b'some text for a\n'))
        # put_file returns the length of the data written
        self.assertEqual(16, result)
        self.assertTrue(t.has('a'))
        self.check_transport_contents(b'some text for a\n', t, 'a')
        # Put also replaces contents
        result = t.put_file('a', BytesIO(b'new\ncontents for\na\n'))
        self.assertEqual(19, result)
        self.check_transport_contents(b'new\ncontents for\na\n', t, 'a')
        self.assertRaises(NoSuchFile,
                          t.put_file, 'path/doesnt/exist/c',
                          BytesIO(b'contents'))

    def test_put_file_non_atomic(self):
        t = self.get_transport()

        if t.is_readonly():
            self.assertRaises(TransportNotPossible,
                              t.put_file_non_atomic, 'a', BytesIO(b'some text for a\n'))
            return

        self.assertFalse(t.has('a'))
        t.put_file_non_atomic('a', BytesIO(b'some text for a\n'))
        self.assertTrue(t.has('a'))
        self.check_transport_contents(b'some text for a\n', t, 'a')
        # Put also replaces contents
        t.put_file_non_atomic('a', BytesIO(b'new\ncontents for\na\n'))
        self.check_transport_contents(b'new\ncontents for\na\n', t, 'a')

        # Make sure we can create another file
        t.put_file_non_atomic('d', BytesIO(b'contents for\nd\n'))
        # And overwrite 'a' with empty contents
        t.put_file_non_atomic('a', BytesIO(b''))
        self.check_transport_contents(b'contents for\nd\n', t, 'd')
        self.check_transport_contents(b'', t, 'a')

        self.assertRaises(NoSuchFile, t.put_file_non_atomic, 'no/such/path',
                          BytesIO(b'contents\n'))
        # Now test the create_parent flag
        self.assertRaises(NoSuchFile, t.put_file_non_atomic, 'dir/a',
                          BytesIO(b'contents\n'))
        self.assertFalse(t.has('dir/a'))
        t.put_file_non_atomic('dir/a', BytesIO(b'contents for dir/a\n'),
                              create_parent_dir=True)
        self.check_transport_contents(b'contents for dir/a\n', t, 'dir/a')

        # But we still get NoSuchFile if we can't make the parent dir
        self.assertRaises(NoSuchFile, t.put_file_non_atomic, 'not/there/a',
                          BytesIO(b'contents\n'),
                          create_parent_dir=True)

    def test_put_file_permissions(self):

        t = self.get_transport()

        if t.is_readonly():
            return
        if not t._can_roundtrip_unix_modebits():
            # Can't roundtrip, so no need to run this test
            return
        t.put_file('mode644', BytesIO(b'test text\n'), mode=0o644)
        self.assertTransportMode(t, 'mode644', 0o644)
        t.put_file('mode666', BytesIO(b'test text\n'), mode=0o666)
        self.assertTransportMode(t, 'mode666', 0o666)
        t.put_file('mode600', BytesIO(b'test text\n'), mode=0o600)
        self.assertTransportMode(t, 'mode600', 0o600)
        # Yes, you can put a file such that it becomes readonly
        t.put_file('mode400', BytesIO(b'test text\n'), mode=0o400)
        self.assertTransportMode(t, 'mode400', 0o400)
        # The default permissions should be based on the current umask
        umask = osutils.get_umask()
        t.put_file('nomode', BytesIO(b'test text\n'), mode=None)
        self.assertTransportMode(t, 'nomode', 0o666 & ~umask)

    def test_put_file_non_atomic_permissions(self):
        t = self.get_transport()

        if t.is_readonly():
            return
        if not t._can_roundtrip_unix_modebits():
            # Can't roundtrip, so no need to run this test
            return
        t.put_file_non_atomic('mode644', BytesIO(b'test text\n'), mode=0o644)
        self.assertTransportMode(t, 'mode644', 0o644)
        t.put_file_non_atomic('mode666', BytesIO(b'test text\n'), mode=0o666)
        self.assertTransportMode(t, 'mode666', 0o666)
        t.put_file_non_atomic('mode600', BytesIO(b'test text\n'), mode=0o600)
        self.assertTransportMode(t, 'mode600', 0o600)
        # Yes, you can put_file_non_atomic a file such that it becomes readonly
        t.put_file_non_atomic('mode400', BytesIO(b'test text\n'), mode=0o400)
        self.assertTransportMode(t, 'mode400', 0o400)

        # The default permissions should be based on the current umask
        umask = osutils.get_umask()
        t.put_file_non_atomic('nomode', BytesIO(b'test text\n'), mode=None)
        self.assertTransportMode(t, 'nomode', 0o666 & ~umask)

        # We should also be able to set the mode for a parent directory
        # when it is created
        sio = BytesIO()
        t.put_file_non_atomic('dir700/mode664', sio, mode=0o664,
                              dir_mode=0o700, create_parent_dir=True)
        self.assertTransportMode(t, 'dir700', 0o700)
        t.put_file_non_atomic('dir770/mode664', sio, mode=0o664,
                              dir_mode=0o770, create_parent_dir=True)
        self.assertTransportMode(t, 'dir770', 0o770)
        t.put_file_non_atomic('dir777/mode664', sio, mode=0o664,
                              dir_mode=0o777, create_parent_dir=True)
        self.assertTransportMode(t, 'dir777', 0o777)

    def test_put_bytes_unicode(self):
        t = self.get_transport()
        if t.is_readonly():
            return
        unicode_string = u'\u1234'
        self.assertRaises(TypeError, t.put_bytes, 'foo', unicode_string)

    def test_mkdir(self):
        t = self.get_transport()

        if t.is_readonly():
            # cannot mkdir on readonly transports. We're not testing for
            # cache coherency because cache behaviour is not currently
            # defined for the transport interface.
            self.assertRaises(TransportNotPossible, t.mkdir, '.')
            self.assertRaises(TransportNotPossible, t.mkdir, 'new_dir')
            self.assertRaises(TransportNotPossible,
                              t.mkdir, 'path/doesnt/exist')
            return
        # Test mkdir
        t.mkdir('dir_a')
        self.assertEqual(t.has('dir_a'), True)
        self.assertEqual(t.has('dir_b'), False)

        t.mkdir('dir_b')
        self.assertEqual(t.has('dir_b'), True)

        self.assertEqual([t.has(n) for n in
                          ['dir_a', 'dir_b', 'dir_q', 'dir_b']],
                         [True, True, False, True])

        # we were testing that a local mkdir followed by a transport
        # mkdir failed thusly, but given that we * in one process * do not
        # concurrently fiddle with disk dirs and then use transport to do
        # things, the win here seems marginal compared to the constraint on
        # the interface. RBC 20051227
        t.mkdir('dir_g')
        self.assertRaises(FileExists, t.mkdir, 'dir_g')

        # Test get/put in sub-directories
        t.put_bytes('dir_a/a', b'contents of dir_a/a')
        t.put_file('dir_b/b', BytesIO(b'contents of dir_b/b'))
        self.check_transport_contents(b'contents of dir_a/a', t, 'dir_a/a')
        self.check_transport_contents(b'contents of dir_b/b', t, 'dir_b/b')

        # mkdir of a dir with an absent parent
        self.assertRaises(NoSuchFile, t.mkdir, 'missing/dir')

    def test_mkdir_permissions(self):
        t = self.get_transport()
        if t.is_readonly():
            return
        if not t._can_roundtrip_unix_modebits():
            # no sense testing on this transport
            return
        # Test mkdir with a mode
        t.mkdir('dmode755', mode=0o755)
        self.assertTransportMode(t, 'dmode755', 0o755)
        t.mkdir('dmode555', mode=0o555)
        self.assertTransportMode(t, 'dmode555', 0o555)
        t.mkdir('dmode777', mode=0o777)
        self.assertTransportMode(t, 'dmode777', 0o777)
        t.mkdir('dmode700', mode=0o700)
        self.assertTransportMode(t, 'dmode700', 0o700)
        t.mkdir('mdmode755', mode=0o755)
        self.assertTransportMode(t, 'mdmode755', 0o755)

        # Default mode should be based on umask
        umask = osutils.get_umask()
        t.mkdir('dnomode', mode=None)
        self.assertTransportMode(t, 'dnomode', 0o777 & ~umask)

    def test_opening_a_file_stream_creates_file(self):
        t = self.get_transport()
        if t.is_readonly():
            return
        handle = t.open_write_stream('foo')
        try:
            self.assertEqual(b'', t.get_bytes('foo'))
        finally:
            handle.close()

    def test_opening_a_file_stream_can_set_mode(self):
        t = self.get_transport()
        if t.is_readonly():
            self.assertRaises((TransportNotPossible, NotImplementedError),
                              t.open_write_stream, 'foo')
            return
        if not t._can_roundtrip_unix_modebits():
            # Can't roundtrip, so no need to run this test
            return

        def check_mode(name, mode, expected):
            handle = t.open_write_stream(name, mode=mode)
            handle.close()
            self.assertTransportMode(t, name, expected)
        check_mode('mode644', 0o644, 0o644)
        check_mode('mode666', 0o666, 0o666)
        check_mode('mode600', 0o600, 0o600)
        # The default permissions should be based on the current umask
        check_mode('nomode', None, 0o666 & ~osutils.get_umask())

    def test_copy_to(self):
        # FIXME: test:   same server to same server (partly done)
        # same protocol two servers
        # and    different protocols (done for now except for MemoryTransport.
        # - RBC 20060122

        def simple_copy_files(transport_from, transport_to):
            files = ['a', 'b', 'c', 'd']
            self.build_tree(files, transport=transport_from)
            self.assertEqual(4, transport_from.copy_to(files, transport_to))
            for f in files:
                self.check_transport_contents(transport_to.get_bytes(f),
                                              transport_from, f)

        t = self.get_transport()
        if t.__class__.__name__ == "SFTPTransport":
            self.skipTest("SFTP copy_to currently too flakey to use")
        temp_transport = MemoryTransport('memory:///')
        simple_copy_files(t, temp_transport)
        if not t.is_readonly():
            t.mkdir('copy_to_simple')
            t2 = t.clone('copy_to_simple')
            simple_copy_files(t, t2)

        # Test that copying into a missing directory raises
        # NoSuchFile
        if t.is_readonly():
            self.build_tree(['e/', 'e/f'])
        else:
            t.mkdir('e')
            t.put_bytes('e/f', b'contents of e')
        self.assertRaises(NoSuchFile, t.copy_to, ['e/f'], temp_transport)
        temp_transport.mkdir('e')
        t.copy_to(['e/f'], temp_transport)

        del temp_transport
        temp_transport = MemoryTransport('memory:///')

        files = ['a', 'b', 'c', 'd']
        t.copy_to(iter(files), temp_transport)
        for f in files:
            self.check_transport_contents(temp_transport.get_bytes(f),
                                          t, f)
        del temp_transport

        for mode in (0o666, 0o644, 0o600, 0o400):
            temp_transport = MemoryTransport("memory:///")
            t.copy_to(files, temp_transport, mode=mode)
            for f in files:
                self.assertTransportMode(temp_transport, f, mode)

    def test_create_prefix(self):
        t = self.get_transport()
        sub = t.clone('foo').clone('bar')
        try:
            sub.create_prefix()
        except TransportNotPossible:
            self.assertTrue(t.is_readonly())
        else:
            self.assertTrue(t.has('foo/bar'))

    def test_append_file(self):
        t = self.get_transport()

        if t.is_readonly():
            self.assertRaises(TransportNotPossible,
                              t.append_file, 'a', 'add\nsome\nmore\ncontents\n')
            return
        t.put_bytes('a', b'diff\ncontents for\na\n')
        t.put_bytes('b', b'contents\nfor b\n')

        self.assertEqual(20,
                         t.append_file('a', BytesIO(b'add\nsome\nmore\ncontents\n')))

        self.check_transport_contents(
            b'diff\ncontents for\na\nadd\nsome\nmore\ncontents\n',
            t, 'a')

        # a file with no parent should fail..
        self.assertRaises(NoSuchFile,
                          t.append_file, 'missing/path', BytesIO(b'content'))

        # And we can create new files, too
        self.assertEqual(0,
                         t.append_file('c', BytesIO(b'some text\nfor a missing file\n')))
        self.check_transport_contents(b'some text\nfor a missing file\n',
                                      t, 'c')

    def test_append_bytes(self):
        t = self.get_transport()

        if t.is_readonly():
            self.assertRaises(TransportNotPossible,
                              t.append_bytes, 'a', b'add\nsome\nmore\ncontents\n')
            return

        self.assertEqual(0, t.append_bytes('a', b'diff\ncontents for\na\n'))
        self.assertEqual(0, t.append_bytes('b', b'contents\nfor b\n'))

        self.assertEqual(20,
                         t.append_bytes('a', b'add\nsome\nmore\ncontents\n'))

        self.check_transport_contents(
            b'diff\ncontents for\na\nadd\nsome\nmore\ncontents\n',
            t, 'a')

        # a file with no parent should fail..
        self.assertRaises(NoSuchFile,
                          t.append_bytes, 'missing/path', b'content')

    def test_append_file_mode(self):
        """Check that append accepts a mode parameter"""
        # check append accepts a mode
        t = self.get_transport()
        if t.is_readonly():
            self.assertRaises(TransportNotPossible,
                              t.append_file, 'f', BytesIO(b'f'), mode=None)
            return
        t.append_file('f', BytesIO(b'f'), mode=None)

    def test_append_bytes_mode(self):
        # check append_bytes accepts a mode
        t = self.get_transport()
        if t.is_readonly():
            self.assertRaises(TransportNotPossible,
                              t.append_bytes, 'f', b'f', mode=None)
            return
        t.append_bytes('f', b'f', mode=None)

    def test_delete(self):
        # TODO: Test Transport.delete
        t = self.get_transport()

        # Not much to do with a readonly transport
        if t.is_readonly():
            self.assertRaises(TransportNotPossible, t.delete, 'missing')
            return

        t.put_bytes('a', b'a little bit of text\n')
        self.assertTrue(t.has('a'))
        t.delete('a')
        self.assertFalse(t.has('a'))

        self.assertRaises(NoSuchFile, t.delete, 'a')

        t.put_bytes('a', b'a text\n')
        t.put_bytes('b', b'b text\n')
        t.put_bytes('c', b'c text\n')
        self.assertEqual([True, True, True],
                         [t.has(n) for n in ['a', 'b', 'c']])
        t.delete('a')
        t.delete('c')
        self.assertEqual([False, True, False],
                         [t.has(n) for n in ['a', 'b', 'c']])
        self.assertFalse(t.has('a'))
        self.assertTrue(t.has('b'))
        self.assertFalse(t.has('c'))

        for name in ['a', 'c', 'd']:
            self.assertRaises(NoSuchFile, t.delete, name)

        # We should have deleted everything
        # SftpServer creates control files in the
        # working directory, so we can just do a
        # plain "listdir".
        # self.assertEqual([], os.listdir('.'))

    def test_recommended_page_size(self):
        """Transports recommend a page size for partial access to files."""
        t = self.get_transport()
        self.assertIsInstance(t.recommended_page_size(), int)

    def test_rmdir(self):
        t = self.get_transport()
        # Not much to do with a readonly transport
        if t.is_readonly():
            self.assertRaises(TransportNotPossible, t.rmdir, 'missing')
            return
        t.mkdir('adir')
        t.mkdir('adir/bdir')
        t.rmdir('adir/bdir')
        # ftp may not be able to raise NoSuchFile for lack of
        # details when failing
        self.assertRaises((NoSuchFile, PathError), t.rmdir, 'adir/bdir')
        t.rmdir('adir')
        self.assertRaises((NoSuchFile, PathError), t.rmdir, 'adir')

    def test_rmdir_not_empty(self):
        """Deleting a non-empty directory raises an exception

        sftp (and possibly others) don't give us a specific "directory not
        empty" exception -- we can just see that the operation failed.
        """
        t = self.get_transport()
        if t.is_readonly():
            return
        t.mkdir('adir')
        t.mkdir('adir/bdir')
        self.assertRaises(PathError, t.rmdir, 'adir')

    def test_rmdir_empty_but_similar_prefix(self):
        """rmdir does not get confused by sibling paths.

        A naive implementation of MemoryTransport would refuse to rmdir
        ".bzr/branch" if there is a ".bzr/branch-format" directory, because it
        uses "path.startswith(dir)" on all file paths to determine if directory
        is empty.
        """
        t = self.get_transport()
        if t.is_readonly():
            return
        t.mkdir('foo')
        t.put_bytes('foo-bar', b'')
        t.mkdir('foo-baz')
        t.rmdir('foo')
        self.assertRaises((NoSuchFile, PathError), t.rmdir, 'foo')
        self.assertTrue(t.has('foo-bar'))

    def test_rename_dir_succeeds(self):
        t = self.get_transport()
        if t.is_readonly():
            self.assertRaises((TransportNotPossible, NotImplementedError),
                              t.rename, 'foo', 'bar')
            return
        t.mkdir('adir')
        t.mkdir('adir/asubdir')
        t.rename('adir', 'bdir')
        self.assertTrue(t.has('bdir/asubdir'))
        self.assertFalse(t.has('adir'))

    def test_rename_dir_nonempty(self):
        """Attempting to replace a nonemtpy directory should fail"""
        t = self.get_transport()
        if t.is_readonly():
            self.assertRaises((TransportNotPossible, NotImplementedError),
                              t.rename, 'foo', 'bar')
            return
        t.mkdir('adir')
        t.mkdir('adir/asubdir')
        t.mkdir('bdir')
        t.mkdir('bdir/bsubdir')
        # any kind of PathError would be OK, though we normally expect
        # DirectoryNotEmpty
        self.assertRaises(PathError, t.rename, 'bdir', 'adir')
        # nothing was changed so it should still be as before
        self.assertTrue(t.has('bdir/bsubdir'))
        self.assertFalse(t.has('adir/bdir'))
        self.assertFalse(t.has('adir/bsubdir'))

    def test_rename_across_subdirs(self):
        t = self.get_transport()
        if t.is_readonly():
            raise TestNotApplicable("transport is readonly")
        t.mkdir('a')
        t.mkdir('b')
        ta = t.clone('a')
        tb = t.clone('b')
        ta.put_bytes('f', b'aoeu')
        ta.rename('f', '../b/f')
        self.assertTrue(tb.has('f'))
        self.assertFalse(ta.has('f'))
        self.assertTrue(t.has('b/f'))

    def test_delete_tree(self):
        t = self.get_transport()

        # Not much to do with a readonly transport
        if t.is_readonly():
            self.assertRaises(TransportNotPossible, t.delete_tree, 'missing')
            return

        # and does it like listing ?
        t.mkdir('adir')
        try:
            t.delete_tree('adir')
        except TransportNotPossible:
            # ok, this transport does not support delete_tree
            return

        # did it delete that trivial case?
        self.assertRaises(NoSuchFile, t.stat, 'adir')

        self.build_tree(['adir/',
                         'adir/file',
                         'adir/subdir/',
                         'adir/subdir/file',
                         'adir/subdir2/',
                         'adir/subdir2/file',
                         ], transport=t)

        t.delete_tree('adir')
        # adir should be gone now.
        self.assertRaises(NoSuchFile, t.stat, 'adir')

    def test_move(self):
        t = self.get_transport()

        if t.is_readonly():
            return

        # TODO: I would like to use os.listdir() to
        # make sure there are no extra files, but SftpServer
        # creates control files in the working directory
        # perhaps all of this could be done in a subdirectory

        t.put_bytes('a', b'a first file\n')
        self.assertEqual([True, False], [t.has(n) for n in ['a', 'b']])

        t.move('a', 'b')
        self.assertTrue(t.has('b'))
        self.assertFalse(t.has('a'))

        self.check_transport_contents(b'a first file\n', t, 'b')
        self.assertEqual([False, True], [t.has(n) for n in ['a', 'b']])

        # Overwrite a file
        t.put_bytes('c', b'c this file\n')
        t.move('c', 'b')
        self.assertFalse(t.has('c'))
        self.check_transport_contents(b'c this file\n', t, 'b')

        # TODO: Try to write a test for atomicity
        # TODO: Test moving into a non-existent subdirectory

    def test_copy(self):
        t = self.get_transport()

        if t.is_readonly():
            return

        t.put_bytes('a', b'a file\n')
        t.copy('a', 'b')
        self.check_transport_contents(b'a file\n', t, 'b')

        self.assertRaises(NoSuchFile, t.copy, 'c', 'd')
        os.mkdir('c')
        # What should the assert be if you try to copy a
        # file over a directory?
        #self.assertRaises(Something, t.copy, 'a', 'c')
        t.put_bytes('d', b'text in d\n')
        t.copy('d', 'b')
        self.check_transport_contents(b'text in d\n', t, 'b')

    def test_connection_error(self):
        """ConnectionError is raised when connection is impossible.

        The error should be raised from the first operation on the transport.
        """
        try:
            url = self._server.get_bogus_url()
        except NotImplementedError:
            raise TestSkipped("Transport %s has no bogus URL support." %
                              self._server.__class__)
        t = _mod_transport.get_transport_from_url(url)
        self.assertRaises((ConnectionError, NoSuchFile), t.get, '.bzr/branch')

    def test_stat(self):
        # TODO: Test stat, just try once, and if it throws, stop testing
        from stat import S_ISDIR, S_ISREG

        t = self.get_transport()

        try:
            st = t.stat('.')
        except TransportNotPossible as e:
            # This transport cannot stat
            return

        paths = ['a', 'b/', 'b/c', 'b/d/', 'b/d/e']
        sizes = [14, 0, 16, 0, 18]
        self.build_tree(paths, transport=t, line_endings='binary')

        for path, size in zip(paths, sizes):
            st = t.stat(path)
            if path.endswith('/'):
                self.assertTrue(S_ISDIR(st.st_mode))
                # directory sizes are meaningless
            else:
                self.assertTrue(S_ISREG(st.st_mode))
                self.assertEqual(size, st.st_size)

        self.assertRaises(NoSuchFile, t.stat, 'q')
        self.assertRaises(NoSuchFile, t.stat, 'b/a')

        self.build_tree(['subdir/', 'subdir/file'], transport=t)
        subdir = t.clone('subdir')
        st = subdir.stat('./file')
        st = subdir.stat('.')

    def test_hardlink(self):
        from stat import ST_NLINK

        t = self.get_transport()

        source_name = "original_target"
        link_name = "target_link"

        self.build_tree([source_name], transport=t)

        try:
            t.hardlink(source_name, link_name)

            self.assertTrue(t.has(source_name))
            self.assertTrue(t.has(link_name))

            st = t.stat(link_name)
            self.assertEqual(st[ST_NLINK], 2)
        except TransportNotPossible:
            raise TestSkipped("Transport %s does not support hardlinks." %
                              self._server.__class__)

    def test_symlink(self):
        from stat import S_ISLNK

        t = self.get_transport()

        source_name = "original_target"
        link_name = "target_link"

        self.build_tree([source_name], transport=t)

        try:
            t.symlink(source_name, link_name)

            self.assertTrue(t.has(source_name))
            self.assertTrue(t.has(link_name))

            st = t.stat(link_name)
            self.assertTrue(S_ISLNK(st.st_mode),
                            "expected symlink, got mode %o" % st.st_mode)
        except TransportNotPossible:
            raise TestSkipped("Transport %s does not support symlinks." %
                              self._server.__class__)

        self.assertEqual(source_name, t.readlink(link_name))

    def test_readlink_nonexistent(self):
        t = self.get_transport()
        try:
            self.assertRaises(NoSuchFile, t.readlink, 'nonexistent')
        except TransportNotPossible:
            raise TestSkipped("Transport %s does not support symlinks." %
                              self._server.__class__)

    def test_list_dir(self):
        # TODO: Test list_dir, just try once, and if it throws, stop testing
        t = self.get_transport()

        if not t.listable():
            self.assertRaises(TransportNotPossible, t.list_dir, '.')
            return

        def sorted_list(d, transport):
            l = sorted(transport.list_dir(d))
            return l

        self.assertEqual([], sorted_list('.', t))
        # c2 is precisely one letter longer than c here to test that
        # suffixing is not confused.
        # a%25b checks that quoting is done consistently across transports
        tree_names = ['a', 'a%25b', 'b', 'c/', 'c/d', 'c/e', 'c2/']

        if not t.is_readonly():
            self.build_tree(tree_names, transport=t)
        else:
            self.build_tree(tree_names)

        self.assertEqual(
            ['a', 'a%2525b', 'b', 'c', 'c2'], sorted_list('', t))
        self.assertEqual(
            ['a', 'a%2525b', 'b', 'c', 'c2'], sorted_list('.', t))
        self.assertEqual(['d', 'e'], sorted_list('c', t))

        # Cloning the transport produces an equivalent listing
        self.assertEqual(['d', 'e'], sorted_list('', t.clone('c')))

        if not t.is_readonly():
            t.delete('c/d')
            t.delete('b')
        else:
            os.unlink('c/d')
            os.unlink('b')

        self.assertEqual(['a', 'a%2525b', 'c', 'c2'], sorted_list('.', t))
        self.assertEqual(['e'], sorted_list('c', t))

        self.assertListRaises(PathError, t.list_dir, 'q')
        self.assertListRaises(PathError, t.list_dir, 'c/f')
        # 'a' is a file, list_dir should raise an error
        self.assertListRaises(PathError, t.list_dir, 'a')

    def test_list_dir_result_is_url_escaped(self):
        t = self.get_transport()
        if not t.listable():
            raise TestSkipped("transport not listable")

        if not t.is_readonly():
            self.build_tree(['a/', 'a/%'], transport=t)
        else:
            self.build_tree(['a/', 'a/%'])

        names = list(t.list_dir('a'))
        self.assertEqual(['%25'], names)
        self.assertIsInstance(names[0], str)

    def test_clone_preserve_info(self):
        t1 = self.get_transport()
        if not isinstance(t1, ConnectedTransport):
            raise TestSkipped("not a connected transport")

        t2 = t1.clone('subdir')
        self.assertEqual(t1._parsed_url.scheme, t2._parsed_url.scheme)
        self.assertEqual(t1._parsed_url.user, t2._parsed_url.user)
        self.assertEqual(t1._parsed_url.password, t2._parsed_url.password)
        self.assertEqual(t1._parsed_url.host, t2._parsed_url.host)
        self.assertEqual(t1._parsed_url.port, t2._parsed_url.port)

    def test__reuse_for(self):
        t = self.get_transport()
        if not isinstance(t, ConnectedTransport):
            raise TestSkipped("not a connected transport")

        def new_url(scheme=None, user=None, password=None,
                    host=None, port=None, path=None):
            """Build a new url from t.base changing only parts of it.

            Only the parameters different from None will be changed.
            """
            if scheme is None:
                scheme = t._parsed_url.scheme
            if user is None:
                user = t._parsed_url.user
            if password is None:
                password = t._parsed_url.password
            if user is None:
                user = t._parsed_url.user
            if host is None:
                host = t._parsed_url.host
            if port is None:
                port = t._parsed_url.port
            if path is None:
                path = t._parsed_url.path
            return str(urlutils.URL(scheme, user, password, host, port, path))

        if t._parsed_url.scheme == 'ftp':
            scheme = 'sftp'
        else:
            scheme = 'ftp'
        self.assertIsNot(t, t._reuse_for(new_url(scheme=scheme)))
        if t._parsed_url.user == 'me':
            user = 'you'
        else:
            user = 'me'
        self.assertIsNot(t, t._reuse_for(new_url(user=user)))
        # passwords are not taken into account because:
        # - it makes no sense to have two different valid passwords for the
        #   same user
        # - _password in ConnectedTransport is intended to collect what the
        #   user specified from the command-line and there are cases where the
        #   new url can contain no password (if the url was built from an
        #   existing transport.base for example)
        # - password are considered part of the credentials provided at
        #   connection creation time and as such may not be present in the url
        #   (they may be typed by the user when prompted for example)
        self.assertIs(t, t._reuse_for(new_url(password='from space')))
        # We will not connect, we can use a invalid host
        self.assertIsNot(t, t._reuse_for(
            new_url(host=t._parsed_url.host + 'bar')))
        if t._parsed_url.port == 1234:
            port = 4321
        else:
            port = 1234
        self.assertIsNot(t, t._reuse_for(new_url(port=port)))
        # No point in trying to reuse a transport for a local URL
        self.assertIs(None, t._reuse_for('/valid_but_not_existing'))

    def test_connection_sharing(self):
        t = self.get_transport()
        if not isinstance(t, ConnectedTransport):
            raise TestSkipped("not a connected transport")

        c = t.clone('subdir')
        # Some transports will create the connection  only when needed
        t.has('surely_not')  # Force connection
        self.assertIs(t._get_connection(), c._get_connection())

        # Temporary failure, we need to create a new dummy connection
        new_connection = None
        t._set_connection(new_connection)
        # Check that both transports use the same connection
        self.assertIs(new_connection, t._get_connection())
        self.assertIs(new_connection, c._get_connection())

    def test_reuse_connection_for_various_paths(self):
        t = self.get_transport()
        if not isinstance(t, ConnectedTransport):
            raise TestSkipped("not a connected transport")

        t.has('surely_not')  # Force connection
        self.assertIsNot(None, t._get_connection())

        subdir = t._reuse_for(t.base + 'whatever/but/deep/down/the/path')
        self.assertIsNot(t, subdir)
        self.assertIs(t._get_connection(), subdir._get_connection())

        home = subdir._reuse_for(t.base + 'home')
        self.assertIs(t._get_connection(), home._get_connection())
        self.assertIs(subdir._get_connection(), home._get_connection())

    def test_clone(self):
        # TODO: Test that clone moves up and down the filesystem
        t1 = self.get_transport()

        self.build_tree(['a', 'b/', 'b/c'], transport=t1)

        self.assertTrue(t1.has('a'))
        self.assertTrue(t1.has('b/c'))
        self.assertFalse(t1.has('c'))

        t2 = t1.clone('b')
        self.assertEqual(t1.base + 'b/', t2.base)

        self.assertTrue(t2.has('c'))
        self.assertFalse(t2.has('a'))

        t3 = t2.clone('..')
        self.assertTrue(t3.has('a'))
        self.assertFalse(t3.has('c'))

        self.assertFalse(t1.has('b/d'))
        self.assertFalse(t2.has('d'))
        self.assertFalse(t3.has('b/d'))

        if t1.is_readonly():
            self.build_tree_contents([('b/d', b'newfile\n')])
        else:
            t2.put_bytes('d', b'newfile\n')

        self.assertTrue(t1.has('b/d'))
        self.assertTrue(t2.has('d'))
        self.assertTrue(t3.has('b/d'))

    def test_clone_to_root(self):
        orig_transport = self.get_transport()
        # Repeatedly go up to a parent directory until we're at the root
        # directory of this transport
        root_transport = orig_transport
        new_transport = root_transport.clone("..")
        # as we are walking up directories, the path must be
        # growing less, except at the top
        self.assertTrue(len(new_transport.base) < len(root_transport.base) or
                        new_transport.base == root_transport.base)
        while new_transport.base != root_transport.base:
            root_transport = new_transport
            new_transport = root_transport.clone("..")
            # as we are walking up directories, the path must be
            # growing less, except at the top
            self.assertTrue(len(new_transport.base) < len(root_transport.base) or
                            new_transport.base == root_transport.base)

        # Cloning to "/" should take us to exactly the same location.
        self.assertEqual(root_transport.base, orig_transport.clone("/").base)
        # the abspath of "/" from the original transport should be the same
        # as the base at the root:
        self.assertEqual(orig_transport.abspath("/"), root_transport.base)

        # At the root, the URL must still end with / as its a directory
        self.assertEqual(root_transport.base[-1], '/')

    def test_clone_from_root(self):
        """At the root, cloning to a simple dir should just do string append."""
        orig_transport = self.get_transport()
        root_transport = orig_transport.clone('/')
        self.assertEqual(root_transport.base + '.bzr/',
                         root_transport.clone('.bzr').base)

    def test_base_url(self):
        t = self.get_transport()
        self.assertEqual('/', t.base[-1])

    def test_relpath(self):
        t = self.get_transport()
        self.assertEqual('', t.relpath(t.base))
        # base ends with /
        self.assertEqual('', t.relpath(t.base[:-1]))
        # subdirs which don't exist should still give relpaths.
        self.assertEqual('foo', t.relpath(t.base + 'foo'))
        # trailing slash should be the same.
        self.assertEqual('foo', t.relpath(t.base + 'foo/'))

    def test_relpath_at_root(self):
        t = self.get_transport()
        # clone all the way to the top
        new_transport = t.clone('..')
        while new_transport.base != t.base:
            t = new_transport
            new_transport = t.clone('..')
        # we must be able to get a relpath below the root
        self.assertEqual('', t.relpath(t.base))
        # and a deeper one should work too
        self.assertEqual('foo/bar', t.relpath(t.base + 'foo/bar'))

    def test_abspath(self):
        # smoke test for abspath. Corner cases for backends like unix fs's
        # that have aliasing problems like symlinks should go in backend
        # specific test cases.
        transport = self.get_transport()

        self.assertEqual(transport.base + 'relpath',
                         transport.abspath('relpath'))

        # This should work without raising an error.
        transport.abspath("/")

        # the abspath of "/" and "/foo/.." should result in the same location
        self.assertEqual(transport.abspath("/"), transport.abspath("/foo/.."))

        self.assertEqual(transport.clone("/").abspath('foo'),
                         transport.abspath("/foo"))

    # GZ 2011-01-26: Test in per_transport but not using self.get_transport?
    def test_win32_abspath(self):
        # Note: we tried to set sys.platform='win32' so we could test on
        # other platforms too, but then osutils does platform specific
        # things at import time which defeated us...
        if sys.platform != 'win32':
            raise TestSkipped(
                'Testing drive letters in abspath implemented only for win32')

        # smoke test for abspath on win32.
        # a transport based on 'file:///' never fully qualifies the drive.
        transport = _mod_transport.get_transport_from_url("file:///")
        self.assertEqual(transport.abspath("/"), "file:///")

        # but a transport that starts with a drive spec must keep it.
        transport = _mod_transport.get_transport_from_url("file:///C:/")
        self.assertEqual(transport.abspath("/"), "file:///C:/")

    def test_local_abspath(self):
        transport = self.get_transport()
        try:
            p = transport.local_abspath('.')
        except (errors.NotLocalUrl, TransportNotPossible) as e:
            # should be formattable
            s = str(e)
        else:
            self.assertEqual(getcwd(), p)

    def test_abspath_at_root(self):
        t = self.get_transport()
        # clone all the way to the top
        new_transport = t.clone('..')
        while new_transport.base != t.base:
            t = new_transport
            new_transport = t.clone('..')
        # we must be able to get a abspath of the root when we ask for
        # t.abspath('..') - this due to our choice that clone('..')
        # should return the root from the root, combined with the desire that
        # the url from clone('..') and from abspath('..') should be the same.
        self.assertEqual(t.base, t.abspath('..'))
        # '' should give us the root
        self.assertEqual(t.base, t.abspath(''))
        # and a path should append to the url
        self.assertEqual(t.base + 'foo', t.abspath('foo'))

    def test_iter_files_recursive(self):
        transport = self.get_transport()
        if not transport.listable():
            self.assertRaises(TransportNotPossible,
                              transport.iter_files_recursive)
            return
        self.build_tree(['isolated/',
                         'isolated/dir/',
                         'isolated/dir/foo',
                         'isolated/dir/bar',
                         'isolated/dir/b%25z',  # make sure quoting is correct
                         'isolated/bar'],
                        transport=transport)
        paths = set(transport.iter_files_recursive())
        # nb the directories are not converted
        self.assertEqual(paths,
                         {'isolated/dir/foo',
                          'isolated/dir/bar',
                          'isolated/dir/b%2525z',
                          'isolated/bar'})
        sub_transport = transport.clone('isolated')
        paths = set(sub_transport.iter_files_recursive())
        self.assertEqual(paths,
                         {'dir/foo', 'dir/bar', 'dir/b%2525z', 'bar'})

    def test_copy_tree(self):
        # TODO: test file contents and permissions are preserved. This test was
        # added just to ensure that quoting was handled correctly.
        # -- David Allouche 2006-08-11
        transport = self.get_transport()
        if not transport.listable():
            self.assertRaises(TransportNotPossible,
                              transport.iter_files_recursive)
            return
        if transport.is_readonly():
            return
        self.build_tree(['from/',
                         'from/dir/',
                         'from/dir/foo',
                         'from/dir/bar',
                         'from/dir/b%25z',  # make sure quoting is correct
                         'from/bar'],
                        transport=transport)
        transport.copy_tree('from', 'to')
        paths = set(transport.iter_files_recursive())
        self.assertEqual(paths,
                         {'from/dir/foo',
                          'from/dir/bar',
                          'from/dir/b%2525z',
                          'from/bar',
                          'to/dir/foo',
                          'to/dir/bar',
                          'to/dir/b%2525z',
                          'to/bar', })

    def test_copy_tree_to_transport(self):
        transport = self.get_transport()
        if not transport.listable():
            self.assertRaises(TransportNotPossible,
                              transport.iter_files_recursive)
            return
        if transport.is_readonly():
            return
        self.build_tree(['from/',
                         'from/dir/',
                         'from/dir/foo',
                         'from/dir/bar',
                         'from/dir/b%25z',  # make sure quoting is correct
                         'from/bar'],
                        transport=transport)
        from_transport = transport.clone('from')
        to_transport = transport.clone('to')
        to_transport.ensure_base()
        from_transport.copy_tree_to_transport(to_transport)
        paths = set(transport.iter_files_recursive())
        self.assertEqual(paths,
                         {'from/dir/foo',
                          'from/dir/bar',
                          'from/dir/b%2525z',
                          'from/bar',
                          'to/dir/foo',
                          'to/dir/bar',
                          'to/dir/b%2525z',
                          'to/bar', })

    def test_unicode_paths(self):
        """Test that we can read/write files with Unicode names."""
        t = self.get_transport()

        # With FAT32 and certain encodings on win32
        # '\xe5' and '\xe4' actually map to the same file
        # adding a suffix kicks in the 'preserving but insensitive'
        # route, and maintains the right files
        files = [u'\xe5.1',  # a w/ circle iso-8859-1
                 u'\xe4.2',  # a w/ dots iso-8859-1
                 u'\u017d',  # Z with umlat iso-8859-2
                 u'\u062c',  # Arabic j
                 u'\u0410',  # Russian A
                 u'\u65e5',  # Kanji person
                 ]

        no_unicode_support = getattr(self._server, 'no_unicode_support', False)
        if no_unicode_support:
            self.knownFailure("test server cannot handle unicode paths")

        try:
            self.build_tree(files, transport=t, line_endings='binary')
        except UnicodeError:
            raise TestSkipped(
                "cannot handle unicode paths in current encoding")

        # A plain unicode string is not a valid url
        for fname in files:
            self.assertRaises(urlutils.InvalidURL, t.get, fname)

        for fname in files:
            fname_utf8 = fname.encode('utf-8')
            contents = b'contents of %s\n' % (fname_utf8,)
            self.check_transport_contents(contents, t, urlutils.escape(fname))

    def test_connect_twice_is_same_content(self):
        # check that our server (whatever it is) is accessible reliably
        # via get_transport and multiple connections share content.
        transport = self.get_transport()
        if transport.is_readonly():
            return
        transport.put_bytes('foo', b'bar')
        transport3 = self.get_transport()
        self.check_transport_contents(b'bar', transport3, 'foo')

        # now opening at a relative url should give use a sane result:
        transport.mkdir('newdir')
        transport5 = self.get_transport('newdir')
        transport6 = transport5.clone('..')
        self.check_transport_contents(b'bar', transport6, 'foo')

    def test_lock_write(self):
        """Test transport-level write locks.

        These are deprecated and transports may decline to support them.
        """
        transport = self.get_transport()
        if transport.is_readonly():
            self.assertRaises(TransportNotPossible,
                              transport.lock_write, 'foo')
            return
        transport.put_bytes('lock', b'')
        try:
            lock = transport.lock_write('lock')
        except TransportNotPossible:
            return
        # TODO make this consistent on all platforms:
        # self.assertRaises(LockError, transport.lock_write, 'lock')
        lock.unlock()

    def test_lock_read(self):
        """Test transport-level read locks.

        These are deprecated and transports may decline to support them.
        """
        transport = self.get_transport()
        if transport.is_readonly():
            open('lock', 'w').close()
        else:
            transport.put_bytes('lock', b'')
        try:
            lock = transport.lock_read('lock')
        except TransportNotPossible:
            return
        # TODO make this consistent on all platforms:
        # self.assertRaises(LockError, transport.lock_read, 'lock')
        lock.unlock()

    def test_readv(self):
        transport = self.get_transport()
        if transport.is_readonly():
            with open('a', 'w') as f:
                f.write('0123456789')
        else:
            transport.put_bytes('a', b'0123456789')

        d = list(transport.readv('a', ((0, 1),)))
        self.assertEqual(d[0], (0, b'0'))

        d = list(transport.readv('a', ((0, 1), (1, 1), (3, 2), (9, 1))))
        self.assertEqual(d[0], (0, b'0'))
        self.assertEqual(d[1], (1, b'1'))
        self.assertEqual(d[2], (3, b'34'))
        self.assertEqual(d[3], (9, b'9'))

    def test_readv_out_of_order(self):
        transport = self.get_transport()
        if transport.is_readonly():
            with open('a', 'w') as f:
                f.write('0123456789')
        else:
            transport.put_bytes('a', b'01234567890')

        d = list(transport.readv('a', ((1, 1), (9, 1), (0, 1), (3, 2))))
        self.assertEqual(d[0], (1, b'1'))
        self.assertEqual(d[1], (9, b'9'))
        self.assertEqual(d[2], (0, b'0'))
        self.assertEqual(d[3], (3, b'34'))

    def test_readv_with_adjust_for_latency(self):
        transport = self.get_transport()
        # the adjust for latency flag expands the data region returned
        # according to a per-transport heuristic, so testing is a little
        # tricky as we need more data than the largest combining that our
        # transports do. To accomodate this we generate random data and cross
        # reference the returned data with the random data. To avoid doing
        # multiple large random byte look ups we do several tests on the same
        # backing data.
        content = osutils.rand_bytes(200 * 1024)
        content_size = len(content)
        if transport.is_readonly():
            self.build_tree_contents([('a', content)])
        else:
            transport.put_bytes('a', content)

        def check_result_data(result_vector):
            for item in result_vector:
                data_len = len(item[1])
                self.assertEqual(content[item[0]:item[0] + data_len], item[1])

        # start corner case
        result = list(transport.readv('a', ((0, 30),),
                                      adjust_for_latency=True, upper_limit=content_size))
        # we expect 1 result, from 0, to something > 30
        self.assertEqual(1, len(result))
        self.assertEqual(0, result[0][0])
        self.assertTrue(len(result[0][1]) >= 30)
        check_result_data(result)
        # end of file corner case
        result = list(transport.readv('a', ((204700, 100),),
                                      adjust_for_latency=True, upper_limit=content_size))
        # we expect 1 result, from 204800- its length, to the end
        self.assertEqual(1, len(result))
        data_len = len(result[0][1])
        self.assertEqual(204800 - data_len, result[0][0])
        self.assertTrue(data_len >= 100)
        check_result_data(result)
        # out of order ranges are made in order
        result = list(transport.readv('a', ((204700, 100), (0, 50)),
                                      adjust_for_latency=True, upper_limit=content_size))
        # we expect 2 results, in order, start and end.
        self.assertEqual(2, len(result))
        # start
        data_len = len(result[0][1])
        self.assertEqual(0, result[0][0])
        self.assertTrue(data_len >= 30)
        # end
        data_len = len(result[1][1])
        self.assertEqual(204800 - data_len, result[1][0])
        self.assertTrue(data_len >= 100)
        check_result_data(result)
        # close ranges get combined (even if out of order)
        for request_vector in [((400, 50), (800, 234)), ((800, 234), (400, 50))]:
            result = list(transport.readv('a', request_vector,
                                          adjust_for_latency=True, upper_limit=content_size))
            self.assertEqual(1, len(result))
            data_len = len(result[0][1])
            # minimum length is from 400 to 1034 - 634
            self.assertTrue(data_len >= 634)
            # must contain the region 400 to 1034
            self.assertTrue(result[0][0] <= 400)
            self.assertTrue(result[0][0] + data_len >= 1034)
            check_result_data(result)

    def test_readv_with_adjust_for_latency_with_big_file(self):
        transport = self.get_transport()
        # test from observed failure case.
        if transport.is_readonly():
            with open('a', 'w') as f:
                f.write('a' * 1024 * 1024)
        else:
            transport.put_bytes('a', b'a' * 1024 * 1024)
        broken_vector = [(465219, 800), (225221, 800), (445548, 800),
                         (225037, 800), (221357, 800), (437077, 800), (947670, 800),
                         (465373, 800), (947422, 800)]
        results = list(transport.readv('a', broken_vector, True, 1024 * 1024))
        found_items = [False] * 9
        for pos, (start, length) in enumerate(broken_vector):
            # check the range is covered by the result
            for offset, data in results:
                if offset <= start and start + length <= offset + len(data):
                    found_items[pos] = True
        self.assertEqual([True] * 9, found_items)

    def test_get_with_open_write_stream_sees_all_content(self):
        t = self.get_transport()
        if t.is_readonly():
            return
        with t.open_write_stream('foo') as handle:
            handle.write(b'bcd')
            self.assertEqual([(0, b'b'), (2, b'd')], list(
                t.readv('foo', ((0, 1), (2, 1)))))

    def test_get_smart_medium(self):
        """All transports must either give a smart medium, or know they can't.
        """
        transport = self.get_transport()
        try:
            client_medium = transport.get_smart_medium()
        except errors.NoSmartMedium:
            # as long as we got it we're fine
            pass
        else:
            from ..bzr.smart import medium
            self.assertIsInstance(client_medium, medium.SmartClientMedium)

    def test_readv_short_read(self):
        transport = self.get_transport()
        if transport.is_readonly():
            with open('a', 'w') as f:
                f.write('0123456789')
        else:
            transport.put_bytes('a', b'01234567890')

        # This is intentionally reading off the end of the file
        # since we are sure that it cannot get there
        self.assertListRaises((errors.ShortReadvError, errors.InvalidRange,
                               # Can be raised by paramiko
                               AssertionError),
                              transport.readv, 'a', [(1, 1), (8, 10)])

        # This is trying to seek past the end of the file, it should
        # also raise a special error
        self.assertListRaises((errors.ShortReadvError, errors.InvalidRange),
                              transport.readv, 'a', [(12, 2)])

    def test_no_segment_parameters(self):
        """Segment parameters should be stripped and stored in
        transport.segment_parameters."""
        transport = self.get_transport("foo")
        self.assertEqual({}, transport.get_segment_parameters())

    def test_segment_parameters(self):
        """Segment parameters should be stripped and stored in
        transport.get_segment_parameters()."""
        base_url = self._server.get_url()
        parameters = {"key1": "val1", "key2": "val2"}
        url = urlutils.join_segment_parameters(base_url, parameters)
        transport = _mod_transport.get_transport_from_url(url)
        self.assertEqual(parameters, transport.get_segment_parameters())

    def test_set_segment_parameters(self):
        """Segment parameters can be set and show up in base."""
        transport = self.get_transport("foo")
        orig_base = transport.base
        transport.set_segment_parameter("arm", "board")
        self.assertEqual("%s,arm=board" % orig_base, transport.base)
        self.assertEqual({"arm": "board"}, transport.get_segment_parameters())
        transport.set_segment_parameter("arm", None)
        transport.set_segment_parameter("nonexistant", None)
        self.assertEqual({}, transport.get_segment_parameters())
        self.assertEqual(orig_base, transport.base)

    def test_stat_symlink(self):
        # if a transport points directly to a symlink (and supports symlinks
        # at all) you can tell this.  helps with bug 32669.
        t = self.get_transport()
        try:
            t.symlink('target', 'link')
        except TransportNotPossible:
            raise TestSkipped("symlinks not supported")
        t2 = t.clone('link')
        st = t2.stat('')
        self.assertTrue(stat.S_ISLNK(st.st_mode))

    def test_abspath_url_unquote_unreserved(self):
        """URLs from abspath should have unreserved characters unquoted

        Need consistent quoting notably for tildes, see lp:842223 for more.
        """
        t = self.get_transport()
        needlessly_escaped_dir = "%2D%2E%30%39%41%5A%5F%61%7A%7E/"
        self.assertEqual(t.base + "-.09AZ_az~",
                         t.abspath(needlessly_escaped_dir))

    def test_clone_url_unquote_unreserved(self):
        """Base URL of a cloned branch needs unreserved characters unquoted

        Cloned transports should be prefix comparable for things like the
        isolation checking of tests, see lp:842223 for more.
        """
        t1 = self.get_transport()
        needlessly_escaped_dir = "%2D%2E%30%39%41%5A%5F%61%7A%7E/"
        self.build_tree([needlessly_escaped_dir], transport=t1)
        t2 = t1.clone(needlessly_escaped_dir)
        self.assertEqual(t1.base + "-.09AZ_az~/", t2.base)

    def test_hook_post_connection_one(self):
        """Fire post_connect hook after a ConnectedTransport is first used"""
        log = []
        Transport.hooks.install_named_hook("post_connect", log.append, None)
        t = self.get_transport()
        self.assertEqual([], log)
        t.has("non-existant")
        if isinstance(t, RemoteTransport):
            self.assertEqual([t.get_smart_medium()], log)
        elif isinstance(t, ConnectedTransport):
            self.assertEqual([t], log)
        else:
            self.assertEqual([], log)

    def test_hook_post_connection_multi(self):
        """Fire post_connect hook once per unshared underlying connection"""
        log = []
        Transport.hooks.install_named_hook("post_connect", log.append, None)
        t1 = self.get_transport()
        t2 = t1.clone(".")
        t3 = self.get_transport()
        self.assertEqual([], log)
        t1.has("x")
        t2.has("x")
        t3.has("x")
        if isinstance(t1, RemoteTransport):
            self.assertEqual([t.get_smart_medium() for t in [t1, t3]], log)
        elif isinstance(t1, ConnectedTransport):
            self.assertEqual([t1, t3], log)
        else:
            self.assertEqual([], log)
