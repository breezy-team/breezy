# Copyright (C) 2004, 2005, 2006 by Canonical Ltd
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

"""Tests for Transport implementations.

Transport implementations tested here are supplied by
TransportTestProviderAdapter.
"""

import os
from cStringIO import StringIO
import stat
import sys

from bzrlib import (
    errors,
    osutils,
    urlutils,
    )
from bzrlib.errors import (DirectoryNotEmpty, NoSuchFile, FileExists,
                           LockError, NoSmartServer, PathError,
                           TransportNotPossible, ConnectionError,
                           InvalidURL)
from bzrlib.osutils import getcwd
from bzrlib.symbol_versioning import zero_eleven
from bzrlib.tests import TestCaseInTempDir, TestSkipped
from bzrlib.tests.test_transport import TestTransportImplementation
from bzrlib.transport import memory, smart
import bzrlib.transport


def _append(fn, txt):
    """Append the given text (file-like object) to the supplied filename."""
    f = open(fn, 'ab')
    try:
        f.write(txt.read())
    finally:
        f.close()


class TransportTests(TestTransportImplementation):

    def check_transport_contents(self, content, transport, relpath):
        """Check that transport.get(relpath).read() == content."""
        self.assertEqualDiff(content, transport.get(relpath).read())

    def assertListRaises(self, excClass, func, *args, **kwargs):
        """Fail unless excClass is raised when the iterator from func is used.
        
        Many transport functions can return generators this makes sure
        to wrap them in a list() call to make sure the whole generator
        is run, and that the proper exception is raised.
        """
        try:
            list(func(*args, **kwargs))
        except excClass:
            return
        else:
            if getattr(excClass,'__name__', None) is not None:
                excName = excClass.__name__
            else:
                excName = str(excClass)
            raise self.failureException, "%s not raised" % excName

    def test_has(self):
        t = self.get_transport()

        files = ['a', 'b', 'e', 'g', '%']
        self.build_tree(files, transport=t)
        self.assertEqual(True, t.has('a'))
        self.assertEqual(False, t.has('c'))
        self.assertEqual(True, t.has(urlutils.escape('%')))
        self.assertEqual(list(t.has_multi(['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'])),
                [True, True, False, False, True, False, True, False])
        self.assertEqual(True, t.has_any(['a', 'b', 'c']))
        self.assertEqual(False, t.has_any(['c', 'd', 'f', urlutils.escape('%%')]))
        self.assertEqual(list(t.has_multi(iter(['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']))),
                [True, True, False, False, True, False, True, False])
        self.assertEqual(False, t.has_any(['c', 'c', 'c']))
        self.assertEqual(True, t.has_any(['b', 'b', 'b']))

    def test_has_root_works(self):
        current_transport = self.get_transport()
        # import pdb;pdb.set_trace()
        self.assertTrue(current_transport.has('/'))
        root = current_transport.clone('/')
        self.assertTrue(root.has(''))

    def test_get(self):
        t = self.get_transport()

        files = ['a', 'b', 'e', 'g']
        contents = ['contents of a\n',
                    'contents of b\n',
                    'contents of e\n',
                    'contents of g\n',
                    ]
        self.build_tree(files, transport=t, line_endings='binary')
        self.check_transport_contents('contents of a\n', t, 'a')
        content_f = t.get_multi(files)
        for content, f in zip(contents, content_f):
            self.assertEqual(content, f.read())

        content_f = t.get_multi(iter(files))
        for content, f in zip(contents, content_f):
            self.assertEqual(content, f.read())

        self.assertRaises(NoSuchFile, t.get, 'c')
        self.assertListRaises(NoSuchFile, t.get_multi, ['a', 'b', 'c'])
        self.assertListRaises(NoSuchFile, t.get_multi, iter(['a', 'b', 'c']))

    def test_get_bytes(self):
        t = self.get_transport()

        files = ['a', 'b', 'e', 'g']
        contents = ['contents of a\n',
                    'contents of b\n',
                    'contents of e\n',
                    'contents of g\n',
                    ]
        self.build_tree(files, transport=t, line_endings='binary')
        self.check_transport_contents('contents of a\n', t, 'a')

        for content, fname in zip(contents, files):
            self.assertEqual(content, t.get_bytes(fname))

        self.assertRaises(NoSuchFile, t.get_bytes, 'c')

    def test_put(self):
        t = self.get_transport()

        if t.is_readonly():
            return

        self.applyDeprecated(zero_eleven, t.put, 'a', 'string\ncontents\n')
        self.check_transport_contents('string\ncontents\n', t, 'a')

        self.applyDeprecated(zero_eleven,
                             t.put, 'b', StringIO('file-like\ncontents\n'))
        self.check_transport_contents('file-like\ncontents\n', t, 'b')

        self.assertRaises(NoSuchFile,
            self.applyDeprecated,
            zero_eleven,
            t.put, 'path/doesnt/exist/c', StringIO('contents'))

    def test_put_bytes(self):
        t = self.get_transport()

        if t.is_readonly():
            self.assertRaises(TransportNotPossible,
                    t.put_bytes, 'a', 'some text for a\n')
            return

        t.put_bytes('a', 'some text for a\n')
        self.failUnless(t.has('a'))
        self.check_transport_contents('some text for a\n', t, 'a')

        # The contents should be overwritten
        t.put_bytes('a', 'new text for a\n')
        self.check_transport_contents('new text for a\n', t, 'a')

        self.assertRaises(NoSuchFile,
                          t.put_bytes, 'path/doesnt/exist/c', 'contents')

    def test_put_bytes_non_atomic(self):
        t = self.get_transport()

        if t.is_readonly():
            self.assertRaises(TransportNotPossible,
                    t.put_bytes_non_atomic, 'a', 'some text for a\n')
            return

        self.failIf(t.has('a'))
        t.put_bytes_non_atomic('a', 'some text for a\n')
        self.failUnless(t.has('a'))
        self.check_transport_contents('some text for a\n', t, 'a')
        # Put also replaces contents
        t.put_bytes_non_atomic('a', 'new\ncontents for\na\n')
        self.check_transport_contents('new\ncontents for\na\n', t, 'a')

        # Make sure we can create another file
        t.put_bytes_non_atomic('d', 'contents for\nd\n')
        # And overwrite 'a' with empty contents
        t.put_bytes_non_atomic('a', '')
        self.check_transport_contents('contents for\nd\n', t, 'd')
        self.check_transport_contents('', t, 'a')

        self.assertRaises(NoSuchFile, t.put_bytes_non_atomic, 'no/such/path',
                                       'contents\n')
        # Now test the create_parent flag
        self.assertRaises(NoSuchFile, t.put_bytes_non_atomic, 'dir/a',
                                       'contents\n')
        self.failIf(t.has('dir/a'))
        t.put_bytes_non_atomic('dir/a', 'contents for dir/a\n',
                               create_parent_dir=True)
        self.check_transport_contents('contents for dir/a\n', t, 'dir/a')
        
        # But we still get NoSuchFile if we can't make the parent dir
        self.assertRaises(NoSuchFile, t.put_bytes_non_atomic, 'not/there/a',
                                       'contents\n',
                                       create_parent_dir=True)

    def test_put_bytes_permissions(self):
        t = self.get_transport()

        if t.is_readonly():
            return
        if not t._can_roundtrip_unix_modebits():
            # Can't roundtrip, so no need to run this test
            return
        t.put_bytes('mode644', 'test text\n', mode=0644)
        self.assertTransportMode(t, 'mode644', 0644)
        t.put_bytes('mode666', 'test text\n', mode=0666)
        self.assertTransportMode(t, 'mode666', 0666)
        t.put_bytes('mode600', 'test text\n', mode=0600)
        self.assertTransportMode(t, 'mode600', 0600)
        # Yes, you can put_bytes a file such that it becomes readonly
        t.put_bytes('mode400', 'test text\n', mode=0400)
        self.assertTransportMode(t, 'mode400', 0400)

        # The default permissions should be based on the current umask
        umask = osutils.get_umask()
        t.put_bytes('nomode', 'test text\n', mode=None)
        self.assertTransportMode(t, 'nomode', 0666 & ~umask)
        
    def test_put_bytes_non_atomic_permissions(self):
        t = self.get_transport()

        if t.is_readonly():
            return
        if not t._can_roundtrip_unix_modebits():
            # Can't roundtrip, so no need to run this test
            return
        t.put_bytes_non_atomic('mode644', 'test text\n', mode=0644)
        self.assertTransportMode(t, 'mode644', 0644)
        t.put_bytes_non_atomic('mode666', 'test text\n', mode=0666)
        self.assertTransportMode(t, 'mode666', 0666)
        t.put_bytes_non_atomic('mode600', 'test text\n', mode=0600)
        self.assertTransportMode(t, 'mode600', 0600)
        t.put_bytes_non_atomic('mode400', 'test text\n', mode=0400)
        self.assertTransportMode(t, 'mode400', 0400)

        # The default permissions should be based on the current umask
        umask = osutils.get_umask()
        t.put_bytes_non_atomic('nomode', 'test text\n', mode=None)
        self.assertTransportMode(t, 'nomode', 0666 & ~umask)

        # We should also be able to set the mode for a parent directory
        # when it is created
        t.put_bytes_non_atomic('dir700/mode664', 'test text\n', mode=0664,
                               dir_mode=0700, create_parent_dir=True)
        self.assertTransportMode(t, 'dir700', 0700)
        t.put_bytes_non_atomic('dir770/mode664', 'test text\n', mode=0664,
                               dir_mode=0770, create_parent_dir=True)
        self.assertTransportMode(t, 'dir770', 0770)
        t.put_bytes_non_atomic('dir777/mode664', 'test text\n', mode=0664,
                               dir_mode=0777, create_parent_dir=True)
        self.assertTransportMode(t, 'dir777', 0777)
        
    def test_put_file(self):
        t = self.get_transport()

        if t.is_readonly():
            self.assertRaises(TransportNotPossible,
                    t.put_file, 'a', StringIO('some text for a\n'))
            return

        t.put_file('a', StringIO('some text for a\n'))
        self.failUnless(t.has('a'))
        self.check_transport_contents('some text for a\n', t, 'a')
        # Put also replaces contents
        t.put_file('a', StringIO('new\ncontents for\na\n'))
        self.check_transport_contents('new\ncontents for\na\n', t, 'a')
        self.assertRaises(NoSuchFile,
                          t.put_file, 'path/doesnt/exist/c',
                              StringIO('contents'))

    def test_put_file_non_atomic(self):
        t = self.get_transport()

        if t.is_readonly():
            self.assertRaises(TransportNotPossible,
                    t.put_file_non_atomic, 'a', StringIO('some text for a\n'))
            return

        self.failIf(t.has('a'))
        t.put_file_non_atomic('a', StringIO('some text for a\n'))
        self.failUnless(t.has('a'))
        self.check_transport_contents('some text for a\n', t, 'a')
        # Put also replaces contents
        t.put_file_non_atomic('a', StringIO('new\ncontents for\na\n'))
        self.check_transport_contents('new\ncontents for\na\n', t, 'a')

        # Make sure we can create another file
        t.put_file_non_atomic('d', StringIO('contents for\nd\n'))
        # And overwrite 'a' with empty contents
        t.put_file_non_atomic('a', StringIO(''))
        self.check_transport_contents('contents for\nd\n', t, 'd')
        self.check_transport_contents('', t, 'a')

        self.assertRaises(NoSuchFile, t.put_file_non_atomic, 'no/such/path',
                                       StringIO('contents\n'))
        # Now test the create_parent flag
        self.assertRaises(NoSuchFile, t.put_file_non_atomic, 'dir/a',
                                       StringIO('contents\n'))
        self.failIf(t.has('dir/a'))
        t.put_file_non_atomic('dir/a', StringIO('contents for dir/a\n'),
                              create_parent_dir=True)
        self.check_transport_contents('contents for dir/a\n', t, 'dir/a')
        
        # But we still get NoSuchFile if we can't make the parent dir
        self.assertRaises(NoSuchFile, t.put_file_non_atomic, 'not/there/a',
                                       StringIO('contents\n'),
                                       create_parent_dir=True)

    def test_put_file_permissions(self):

        t = self.get_transport()

        if t.is_readonly():
            return
        if not t._can_roundtrip_unix_modebits():
            # Can't roundtrip, so no need to run this test
            return
        t.put_file('mode644', StringIO('test text\n'), mode=0644)
        self.assertTransportMode(t, 'mode644', 0644)
        t.put_file('mode666', StringIO('test text\n'), mode=0666)
        self.assertTransportMode(t, 'mode666', 0666)
        t.put_file('mode600', StringIO('test text\n'), mode=0600)
        self.assertTransportMode(t, 'mode600', 0600)
        # Yes, you can put a file such that it becomes readonly
        t.put_file('mode400', StringIO('test text\n'), mode=0400)
        self.assertTransportMode(t, 'mode400', 0400)

        # XXX: put_multi is deprecated, so do we really care anymore?
        self.applyDeprecated(zero_eleven, t.put_multi,
                             [('mmode644', StringIO('text\n'))], mode=0644)
        self.assertTransportMode(t, 'mmode644', 0644)

        # The default permissions should be based on the current umask
        umask = osutils.get_umask()
        t.put_file('nomode', StringIO('test text\n'), mode=None)
        self.assertTransportMode(t, 'nomode', 0666 & ~umask)
        
    def test_put_file_non_atomic_permissions(self):
        t = self.get_transport()

        if t.is_readonly():
            return
        if not t._can_roundtrip_unix_modebits():
            # Can't roundtrip, so no need to run this test
            return
        t.put_file_non_atomic('mode644', StringIO('test text\n'), mode=0644)
        self.assertTransportMode(t, 'mode644', 0644)
        t.put_file_non_atomic('mode666', StringIO('test text\n'), mode=0666)
        self.assertTransportMode(t, 'mode666', 0666)
        t.put_file_non_atomic('mode600', StringIO('test text\n'), mode=0600)
        self.assertTransportMode(t, 'mode600', 0600)
        # Yes, you can put_file_non_atomic a file such that it becomes readonly
        t.put_file_non_atomic('mode400', StringIO('test text\n'), mode=0400)
        self.assertTransportMode(t, 'mode400', 0400)

        # The default permissions should be based on the current umask
        umask = osutils.get_umask()
        t.put_file_non_atomic('nomode', StringIO('test text\n'), mode=None)
        self.assertTransportMode(t, 'nomode', 0666 & ~umask)
        
        # We should also be able to set the mode for a parent directory
        # when it is created
        sio = StringIO()
        t.put_file_non_atomic('dir700/mode664', sio, mode=0664,
                              dir_mode=0700, create_parent_dir=True)
        self.assertTransportMode(t, 'dir700', 0700)
        t.put_file_non_atomic('dir770/mode664', sio, mode=0664,
                              dir_mode=0770, create_parent_dir=True)
        self.assertTransportMode(t, 'dir770', 0770)
        t.put_file_non_atomic('dir777/mode664', sio, mode=0664,
                              dir_mode=0777, create_parent_dir=True)
        self.assertTransportMode(t, 'dir777', 0777)

    def test_put_multi(self):
        t = self.get_transport()

        if t.is_readonly():
            return
        self.assertEqual(2, self.applyDeprecated(zero_eleven,
            t.put_multi, [('a', StringIO('new\ncontents for\na\n')),
                          ('d', StringIO('contents\nfor d\n'))]
            ))
        self.assertEqual(list(t.has_multi(['a', 'b', 'c', 'd'])),
                [True, False, False, True])
        self.check_transport_contents('new\ncontents for\na\n', t, 'a')
        self.check_transport_contents('contents\nfor d\n', t, 'd')

        self.assertEqual(2, self.applyDeprecated(zero_eleven,
            t.put_multi, iter([('a', StringIO('diff\ncontents for\na\n')),
                              ('d', StringIO('another contents\nfor d\n'))])
            ))
        self.check_transport_contents('diff\ncontents for\na\n', t, 'a')
        self.check_transport_contents('another contents\nfor d\n', t, 'd')

    def test_put_permissions(self):
        t = self.get_transport()

        if t.is_readonly():
            return
        if not t._can_roundtrip_unix_modebits():
            # Can't roundtrip, so no need to run this test
            return
        self.applyDeprecated(zero_eleven, t.put, 'mode644',
                             StringIO('test text\n'), mode=0644)
        self.assertTransportMode(t, 'mode644', 0644)
        self.applyDeprecated(zero_eleven, t.put, 'mode666',
                             StringIO('test text\n'), mode=0666)
        self.assertTransportMode(t, 'mode666', 0666)
        self.applyDeprecated(zero_eleven, t.put, 'mode600',
                             StringIO('test text\n'), mode=0600)
        self.assertTransportMode(t, 'mode600', 0600)
        # Yes, you can put a file such that it becomes readonly
        self.applyDeprecated(zero_eleven, t.put, 'mode400',
                             StringIO('test text\n'), mode=0400)
        self.assertTransportMode(t, 'mode400', 0400)
        self.applyDeprecated(zero_eleven, t.put_multi,
                             [('mmode644', StringIO('text\n'))], mode=0644)
        self.assertTransportMode(t, 'mmode644', 0644)

        # The default permissions should be based on the current umask
        umask = osutils.get_umask()
        self.applyDeprecated(zero_eleven, t.put, 'nomode',
                             StringIO('test text\n'), mode=None)
        self.assertTransportMode(t, 'nomode', 0666 & ~umask)
        
    def test_mkdir(self):
        t = self.get_transport()

        if t.is_readonly():
            # cannot mkdir on readonly transports. We're not testing for 
            # cache coherency because cache behaviour is not currently
            # defined for the transport interface.
            self.assertRaises(TransportNotPossible, t.mkdir, '.')
            self.assertRaises(TransportNotPossible, t.mkdir, 'new_dir')
            self.assertRaises(TransportNotPossible, t.mkdir_multi, ['new_dir'])
            self.assertRaises(TransportNotPossible, t.mkdir, 'path/doesnt/exist')
            return
        # Test mkdir
        t.mkdir('dir_a')
        self.assertEqual(t.has('dir_a'), True)
        self.assertEqual(t.has('dir_b'), False)

        t.mkdir('dir_b')
        self.assertEqual(t.has('dir_b'), True)

        t.mkdir_multi(['dir_c', 'dir_d'])

        t.mkdir_multi(iter(['dir_e', 'dir_f']))
        self.assertEqual(list(t.has_multi(
            ['dir_a', 'dir_b', 'dir_c', 'dir_q',
             'dir_d', 'dir_e', 'dir_f', 'dir_b'])),
            [True, True, True, False,
             True, True, True, True])

        # we were testing that a local mkdir followed by a transport
        # mkdir failed thusly, but given that we * in one process * do not
        # concurrently fiddle with disk dirs and then use transport to do 
        # things, the win here seems marginal compared to the constraint on
        # the interface. RBC 20051227
        t.mkdir('dir_g')
        self.assertRaises(FileExists, t.mkdir, 'dir_g')

        # Test get/put in sub-directories
        t.put_bytes('dir_a/a', 'contents of dir_a/a')
        t.put_file('dir_b/b', StringIO('contents of dir_b/b'))
        self.check_transport_contents('contents of dir_a/a', t, 'dir_a/a')
        self.check_transport_contents('contents of dir_b/b', t, 'dir_b/b')

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
        t.mkdir('dmode755', mode=0755)
        self.assertTransportMode(t, 'dmode755', 0755)
        t.mkdir('dmode555', mode=0555)
        self.assertTransportMode(t, 'dmode555', 0555)
        t.mkdir('dmode777', mode=0777)
        self.assertTransportMode(t, 'dmode777', 0777)
        t.mkdir('dmode700', mode=0700)
        self.assertTransportMode(t, 'dmode700', 0700)
        t.mkdir_multi(['mdmode755'], mode=0755)
        self.assertTransportMode(t, 'mdmode755', 0755)

        # Default mode should be based on umask
        umask = osutils.get_umask()
        t.mkdir('dnomode', mode=None)
        self.assertTransportMode(t, 'dnomode', 0777 & ~umask)

    def test_copy_to(self):
        # FIXME: test:   same server to same server (partly done)
        # same protocol two servers
        # and    different protocols (done for now except for MemoryTransport.
        # - RBC 20060122
        from bzrlib.transport.memory import MemoryTransport

        def simple_copy_files(transport_from, transport_to):
            files = ['a', 'b', 'c', 'd']
            self.build_tree(files, transport=transport_from)
            self.assertEqual(4, transport_from.copy_to(files, transport_to))
            for f in files:
                self.check_transport_contents(transport_to.get(f).read(),
                                              transport_from, f)

        t = self.get_transport()
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
            t.put_bytes('e/f', 'contents of e')
        self.assertRaises(NoSuchFile, t.copy_to, ['e/f'], temp_transport)
        temp_transport.mkdir('e')
        t.copy_to(['e/f'], temp_transport)

        del temp_transport
        temp_transport = MemoryTransport('memory:///')

        files = ['a', 'b', 'c', 'd']
        t.copy_to(iter(files), temp_transport)
        for f in files:
            self.check_transport_contents(temp_transport.get(f).read(),
                                          t, f)
        del temp_transport

        for mode in (0666, 0644, 0600, 0400):
            temp_transport = MemoryTransport("memory:///")
            t.copy_to(files, temp_transport, mode=mode)
            for f in files:
                self.assertTransportMode(temp_transport, f, mode)

    def test_append(self):
        t = self.get_transport()

        if t.is_readonly():
            return
        t.put_bytes('a', 'diff\ncontents for\na\n')
        t.put_bytes('b', 'contents\nfor b\n')

        self.assertEqual(20, self.applyDeprecated(zero_eleven,
            t.append, 'a', StringIO('add\nsome\nmore\ncontents\n')))

        self.check_transport_contents(
            'diff\ncontents for\na\nadd\nsome\nmore\ncontents\n',
            t, 'a')

        # And we can create new files, too
        self.assertEqual(0, self.applyDeprecated(zero_eleven,
            t.append, 'c', StringIO('some text\nfor a missing file\n')))
        self.check_transport_contents('some text\nfor a missing file\n',
                                      t, 'c')
    def test_append_file(self):
        t = self.get_transport()

        if t.is_readonly():
            self.assertRaises(TransportNotPossible,
                    t.append_file, 'a', 'add\nsome\nmore\ncontents\n')
            return
        t.put_bytes('a', 'diff\ncontents for\na\n')
        t.put_bytes('b', 'contents\nfor b\n')

        self.assertEqual(20,
            t.append_file('a', StringIO('add\nsome\nmore\ncontents\n')))

        self.check_transport_contents(
            'diff\ncontents for\na\nadd\nsome\nmore\ncontents\n',
            t, 'a')

        # a file with no parent should fail..
        self.assertRaises(NoSuchFile,
                          t.append_file, 'missing/path', StringIO('content'))

        # And we can create new files, too
        self.assertEqual(0,
            t.append_file('c', StringIO('some text\nfor a missing file\n')))
        self.check_transport_contents('some text\nfor a missing file\n',
                                      t, 'c')

    def test_append_bytes(self):
        t = self.get_transport()

        if t.is_readonly():
            self.assertRaises(TransportNotPossible,
                    t.append_bytes, 'a', 'add\nsome\nmore\ncontents\n')
            return

        self.assertEqual(0, t.append_bytes('a', 'diff\ncontents for\na\n'))
        self.assertEqual(0, t.append_bytes('b', 'contents\nfor b\n'))

        self.assertEqual(20,
            t.append_bytes('a', 'add\nsome\nmore\ncontents\n'))

        self.check_transport_contents(
            'diff\ncontents for\na\nadd\nsome\nmore\ncontents\n',
            t, 'a')

        # a file with no parent should fail..
        self.assertRaises(NoSuchFile,
                          t.append_bytes, 'missing/path', 'content')

    def test_append_multi(self):
        t = self.get_transport()

        if t.is_readonly():
            return
        t.put_bytes('a', 'diff\ncontents for\na\n'
                         'add\nsome\nmore\ncontents\n')
        t.put_bytes('b', 'contents\nfor b\n')

        self.assertEqual((43, 15),
            t.append_multi([('a', StringIO('and\nthen\nsome\nmore\n')),
                            ('b', StringIO('some\nmore\nfor\nb\n'))]))

        self.check_transport_contents(
            'diff\ncontents for\na\n'
            'add\nsome\nmore\ncontents\n'
            'and\nthen\nsome\nmore\n',
            t, 'a')
        self.check_transport_contents(
                'contents\nfor b\n'
                'some\nmore\nfor\nb\n',
                t, 'b')

        self.assertEqual((62, 31),
            t.append_multi(iter([('a', StringIO('a little bit more\n')),
                                 ('b', StringIO('from an iterator\n'))])))
        self.check_transport_contents(
            'diff\ncontents for\na\n'
            'add\nsome\nmore\ncontents\n'
            'and\nthen\nsome\nmore\n'
            'a little bit more\n',
            t, 'a')
        self.check_transport_contents(
                'contents\nfor b\n'
                'some\nmore\nfor\nb\n'
                'from an iterator\n',
                t, 'b')

        self.assertEqual((80, 0),
            t.append_multi([('a', StringIO('some text in a\n')),
                            ('d', StringIO('missing file r\n'))]))

        self.check_transport_contents(
            'diff\ncontents for\na\n'
            'add\nsome\nmore\ncontents\n'
            'and\nthen\nsome\nmore\n'
            'a little bit more\n'
            'some text in a\n',
            t, 'a')
        self.check_transport_contents('missing file r\n', t, 'd')

    def test_append_file_mode(self):
        """Check that append accepts a mode parameter"""
        # check append accepts a mode
        t = self.get_transport()
        if t.is_readonly():
            self.assertRaises(TransportNotPossible,
                t.append_file, 'f', StringIO('f'), mode=None)
            return
        t.append_file('f', StringIO('f'), mode=None)
        
    def test_append_bytes_mode(self):
        # check append_bytes accepts a mode
        t = self.get_transport()
        if t.is_readonly():
            self.assertRaises(TransportNotPossible,
                t.append_bytes, 'f', 'f', mode=None)
            return
        t.append_bytes('f', 'f', mode=None)
        
    def test_delete(self):
        # TODO: Test Transport.delete
        t = self.get_transport()

        # Not much to do with a readonly transport
        if t.is_readonly():
            self.assertRaises(TransportNotPossible, t.delete, 'missing')
            return

        t.put_bytes('a', 'a little bit of text\n')
        self.failUnless(t.has('a'))
        t.delete('a')
        self.failIf(t.has('a'))

        self.assertRaises(NoSuchFile, t.delete, 'a')

        t.put_bytes('a', 'a text\n')
        t.put_bytes('b', 'b text\n')
        t.put_bytes('c', 'c text\n')
        self.assertEqual([True, True, True],
                list(t.has_multi(['a', 'b', 'c'])))
        t.delete_multi(['a', 'c'])
        self.assertEqual([False, True, False],
                list(t.has_multi(['a', 'b', 'c'])))
        self.failIf(t.has('a'))
        self.failUnless(t.has('b'))
        self.failIf(t.has('c'))

        self.assertRaises(NoSuchFile,
                t.delete_multi, ['a', 'b', 'c'])

        self.assertRaises(NoSuchFile,
                t.delete_multi, iter(['a', 'b', 'c']))

        t.put_bytes('a', 'another a text\n')
        t.put_bytes('c', 'another c text\n')
        t.delete_multi(iter(['a', 'b', 'c']))

        # We should have deleted everything
        # SftpServer creates control files in the
        # working directory, so we can just do a
        # plain "listdir".
        # self.assertEqual([], os.listdir('.'))

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

    def test_rename_dir_succeeds(self):
        t = self.get_transport()
        if t.is_readonly():
            raise TestSkipped("transport is readonly")
        t.mkdir('adir')
        t.mkdir('adir/asubdir')
        t.rename('adir', 'bdir')
        self.assertTrue(t.has('bdir/asubdir'))
        self.assertFalse(t.has('adir'))

    def test_rename_dir_nonempty(self):
        """Attempting to replace a nonemtpy directory should fail"""
        t = self.get_transport()
        if t.is_readonly():
            raise TestSkipped("transport is readonly")
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

        t.put_bytes('a', 'a first file\n')
        self.assertEquals([True, False], list(t.has_multi(['a', 'b'])))

        t.move('a', 'b')
        self.failUnless(t.has('b'))
        self.failIf(t.has('a'))

        self.check_transport_contents('a first file\n', t, 'b')
        self.assertEquals([False, True], list(t.has_multi(['a', 'b'])))

        # Overwrite a file
        t.put_bytes('c', 'c this file\n')
        t.move('c', 'b')
        self.failIf(t.has('c'))
        self.check_transport_contents('c this file\n', t, 'b')

        # TODO: Try to write a test for atomicity
        # TODO: Test moving into a non-existant subdirectory
        # TODO: Test Transport.move_multi

    def test_copy(self):
        t = self.get_transport()

        if t.is_readonly():
            return

        t.put_bytes('a', 'a file\n')
        t.copy('a', 'b')
        self.check_transport_contents('a file\n', t, 'b')

        self.assertRaises(NoSuchFile, t.copy, 'c', 'd')
        os.mkdir('c')
        # What should the assert be if you try to copy a
        # file over a directory?
        #self.assertRaises(Something, t.copy, 'a', 'c')
        t.put_bytes('d', 'text in d\n')
        t.copy('d', 'b')
        self.check_transport_contents('text in d\n', t, 'b')

        # TODO: test copy_multi

    def test_connection_error(self):
        """ConnectionError is raised when connection is impossible.
        
        The error may be raised from either the constructor or the first
        operation on the transport.
        """
        try:
            url = self._server.get_bogus_url()
        except NotImplementedError:
            raise TestSkipped("Transport %s has no bogus URL support." %
                              self._server.__class__)
        # This should be:  but SSH still connects on construction. No COOKIE!
        # self.assertRaises((ConnectionError, NoSuchFile), t.get, '.bzr/branch')
        try:
            t = bzrlib.transport.get_transport(url)
            t.get('.bzr/branch')
        except (ConnectionError, NoSuchFile), e:
            pass
        except (Exception), e:
            self.fail('Wrong exception thrown (%s.%s): %s' 
                        % (e.__class__.__module__, e.__class__.__name__, e))
        else:
            self.fail('Did not get the expected ConnectionError or NoSuchFile.')

    def test_stat(self):
        # TODO: Test stat, just try once, and if it throws, stop testing
        from stat import S_ISDIR, S_ISREG

        t = self.get_transport()

        try:
            st = t.stat('.')
        except TransportNotPossible, e:
            # This transport cannot stat
            return

        paths = ['a', 'b/', 'b/c', 'b/d/', 'b/d/e']
        sizes = [14, 0, 16, 0, 18] 
        self.build_tree(paths, transport=t, line_endings='binary')

        for path, size in zip(paths, sizes):
            st = t.stat(path)
            if path.endswith('/'):
                self.failUnless(S_ISDIR(st.st_mode))
                # directory sizes are meaningless
            else:
                self.failUnless(S_ISREG(st.st_mode))
                self.assertEqual(size, st.st_size)

        remote_stats = list(t.stat_multi(paths))
        remote_iter_stats = list(t.stat_multi(iter(paths)))

        self.assertRaises(NoSuchFile, t.stat, 'q')
        self.assertRaises(NoSuchFile, t.stat, 'b/a')

        self.assertListRaises(NoSuchFile, t.stat_multi, ['a', 'c', 'd'])
        self.assertListRaises(NoSuchFile, t.stat_multi, iter(['a', 'c', 'd']))
        self.build_tree(['subdir/', 'subdir/file'], transport=t)
        subdir = t.clone('subdir')
        subdir.stat('./file')
        subdir.stat('.')

    def test_list_dir(self):
        # TODO: Test list_dir, just try once, and if it throws, stop testing
        t = self.get_transport()
        
        if not t.listable():
            self.assertRaises(TransportNotPossible, t.list_dir, '.')
            return

        def sorted_list(d):
            l = list(t.list_dir(d))
            l.sort()
            return l

        # SftpServer creates control files in the working directory
        # so lets move down a directory to avoid those.
        if not t.is_readonly():
            t.mkdir('wd')
        else:
            os.mkdir('wd')
        t = t.clone('wd')

        self.assertEqual([], sorted_list('.'))
        # c2 is precisely one letter longer than c here to test that
        # suffixing is not confused.
        # a%25b checks that quoting is done consistently across transports
        tree_names = ['a', 'a%25b', 'b', 'c/', 'c/d', 'c/e', 'c2/']
        if not t.is_readonly():
            self.build_tree(tree_names, transport=t)
        else:
            self.build_tree(['wd/' + name for name in tree_names])

        self.assertEqual(
            ['a', 'a%2525b', 'b', 'c', 'c2'], sorted_list('.'))
        self.assertEqual(['d', 'e'], sorted_list('c'))

        if not t.is_readonly():
            t.delete('c/d')
            t.delete('b')
        else:
            os.unlink('wd/c/d')
            os.unlink('wd/b')
            
        self.assertEqual(['a', 'a%2525b', 'c', 'c2'], sorted_list('.'))
        self.assertEqual(['e'], sorted_list('c'))

        self.assertListRaises(PathError, t.list_dir, 'q')
        self.assertListRaises(PathError, t.list_dir, 'c/f')
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

    def test_clone(self):
        # TODO: Test that clone moves up and down the filesystem
        t1 = self.get_transport()

        self.build_tree(['a', 'b/', 'b/c'], transport=t1)

        self.failUnless(t1.has('a'))
        self.failUnless(t1.has('b/c'))
        self.failIf(t1.has('c'))

        t2 = t1.clone('b')
        self.assertEqual(t1.base + 'b/', t2.base)

        self.failUnless(t2.has('c'))
        self.failIf(t2.has('a'))

        t3 = t2.clone('..')
        self.failUnless(t3.has('a'))
        self.failIf(t3.has('c'))

        self.failIf(t1.has('b/d'))
        self.failIf(t2.has('d'))
        self.failIf(t3.has('b/d'))

        if t1.is_readonly():
            open('b/d', 'wb').write('newfile\n')
        else:
            t2.put_bytes('d', 'newfile\n')

        self.failUnless(t1.has('b/d'))
        self.failUnless(t2.has('d'))
        self.failUnless(t3.has('b/d'))

    def test_clone_to_root(self):
        orig_transport = self.get_transport()
        # Repeatedly go up to a parent directory until we're at the root
        # directory of this transport
        root_transport = orig_transport
        new_transport = root_transport.clone("..")
        # as we are walking up directories, the path must be must be 
        # growing less, except at the top
        self.assertTrue(len(new_transport.base) < len(root_transport.base)
            or new_transport.base == root_transport.base)
        while new_transport.base != root_transport.base:
            root_transport = new_transport
            new_transport = root_transport.clone("..")
            # as we are walking up directories, the path must be must be 
            # growing less, except at the top
            self.assertTrue(len(new_transport.base) < len(root_transport.base)
                or new_transport.base == root_transport.base)

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
        # subdirs which dont exist should still give relpaths.
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

    def test_local_abspath(self):
        transport = self.get_transport()
        try:
            p = transport.local_abspath('.')
        except TransportNotPossible:
            pass # This is not a local transport
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
                         'isolated/dir/b%25z', # make sure quoting is correct
                         'isolated/bar'],
                        transport=transport)
        paths = set(transport.iter_files_recursive())
        # nb the directories are not converted
        self.assertEqual(paths,
                    set(['isolated/dir/foo',
                         'isolated/dir/bar',
                         'isolated/dir/b%2525z',
                         'isolated/bar']))
        sub_transport = transport.clone('isolated')
        paths = set(sub_transport.iter_files_recursive())
        self.assertEqual(paths,
            set(['dir/foo', 'dir/bar', 'dir/b%2525z', 'bar']))

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
                         'from/dir/b%25z', # make sure quoting is correct
                         'from/bar'],
                        transport=transport)
        transport.copy_tree('from', 'to')
        paths = set(transport.iter_files_recursive())
        self.assertEqual(paths,
                    set(['from/dir/foo',
                         'from/dir/bar',
                         'from/dir/b%2525z',
                         'from/bar',
                         'to/dir/foo',
                         'to/dir/bar',
                         'to/dir/b%2525z',
                         'to/bar',]))

    def test_unicode_paths(self):
        """Test that we can read/write files with Unicode names."""
        t = self.get_transport()

        # With FAT32 and certain encodings on win32
        # '\xe5' and '\xe4' actually map to the same file
        # adding a suffix kicks in the 'preserving but insensitive'
        # route, and maintains the right files
        files = [u'\xe5.1', # a w/ circle iso-8859-1
                 u'\xe4.2', # a w/ dots iso-8859-1
                 u'\u017d', # Z with umlat iso-8859-2
                 u'\u062c', # Arabic j
                 u'\u0410', # Russian A
                 u'\u65e5', # Kanji person
                ]

        try:
            self.build_tree(files, transport=t, line_endings='binary')
        except UnicodeError:
            raise TestSkipped("cannot handle unicode paths in current encoding")

        # A plain unicode string is not a valid url
        for fname in files:
            self.assertRaises(InvalidURL, t.get, fname)

        for fname in files:
            fname_utf8 = fname.encode('utf-8')
            contents = 'contents of %s\n' % (fname_utf8,)
            self.check_transport_contents(contents, t, urlutils.escape(fname))

    def test_connect_twice_is_same_content(self):
        # check that our server (whatever it is) is accessable reliably
        # via get_transport and multiple connections share content.
        transport = self.get_transport()
        if transport.is_readonly():
            return
        transport.put_bytes('foo', 'bar')
        transport2 = self.get_transport()
        self.check_transport_contents('bar', transport2, 'foo')
        # its base should be usable.
        transport2 = bzrlib.transport.get_transport(transport.base)
        self.check_transport_contents('bar', transport2, 'foo')

        # now opening at a relative url should give use a sane result:
        transport.mkdir('newdir')
        transport2 = bzrlib.transport.get_transport(transport.base + "newdir")
        transport2 = transport2.clone('..')
        self.check_transport_contents('bar', transport2, 'foo')

    def test_lock_write(self):
        """Test transport-level write locks.

        These are deprecated and transports may decline to support them.
        """
        transport = self.get_transport()
        if transport.is_readonly():
            self.assertRaises(TransportNotPossible, transport.lock_write, 'foo')
            return
        transport.put_bytes('lock', '')
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
            file('lock', 'w').close()
        else:
            transport.put_bytes('lock', '')
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
            file('a', 'w').write('0123456789')
        else:
            transport.put_bytes('a', '0123456789')

        d = list(transport.readv('a', ((0, 1), (1, 1), (3, 2), (9, 1))))
        self.assertEqual(d[0], (0, '0'))
        self.assertEqual(d[1], (1, '1'))
        self.assertEqual(d[2], (3, '34'))
        self.assertEqual(d[3], (9, '9'))

    def test_readv_out_of_order(self):
        transport = self.get_transport()
        if transport.is_readonly():
            file('a', 'w').write('0123456789')
        else:
            transport.put_bytes('a', '01234567890')

        d = list(transport.readv('a', ((1, 1), (9, 1), (0, 1), (3, 2))))
        self.assertEqual(d[0], (1, '1'))
        self.assertEqual(d[1], (9, '9'))
        self.assertEqual(d[2], (0, '0'))
        self.assertEqual(d[3], (3, '34'))

    def test_get_smart_medium(self):
        """All transports must either give a smart medium, or know they can't.
        """
        transport = self.get_transport()
        try:
            medium = transport.get_smart_medium()
            self.assertIsInstance(medium, smart.SmartClientMedium)
        except errors.NoSmartMedium:
            # as long as we got it we're fine
            pass

    def test_readv_short_read(self):
        transport = self.get_transport()
        if transport.is_readonly():
            file('a', 'w').write('0123456789')
        else:
            transport.put_bytes('a', '01234567890')

        # This is intentionally reading off the end of the file
        # since we are sure that it cannot get there
        self.assertListRaises((errors.ShortReadvError, AssertionError),
                              transport.readv, 'a', [(1,1), (8,10)])

        # This is trying to seek past the end of the file, it should
        # also raise a special error
        self.assertListRaises(errors.ShortReadvError,
                              transport.readv, 'a', [(12,2)])
