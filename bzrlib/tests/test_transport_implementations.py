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

"""Tests for Transport implementations.

Transport implementations tested here are supplied by
TransportTestProviderAdapter.
"""

import os
from cStringIO import StringIO
import stat
import sys

from bzrlib.errors import (NoSuchFile, FileExists,
                           TransportNotPossible, ConnectionError)
from bzrlib.tests import TestCaseInTempDir, TestSkipped
from bzrlib.transport import memory, urlescape
import bzrlib.transport


def _append(fn, txt):
    """Append the given text (file-like object) to the supplied filename."""
    f = open(fn, 'ab')
    f.write(txt.read())
    f.flush()
    f.close()
    del f


class TestTransportImplementation(TestCaseInTempDir):
    """Implementation verification for transports.
    
    To verify a transport we need a server factory, which is a callable
    that accepts no parameters and returns an implementation of
    bzrlib.transport.Server.
    
    That Server is then used to construct transport instances and test
    the transport via loopback activity.

    Currently this assumes that the Transport object is connected to the 
    current working directory.  So that whatever is done 
    through the transport, should show up in the working 
    directory, and vice-versa. This is a bug, because its possible to have
    URL schemes which provide access to something that may not be 
    result in storage on the local disk, i.e. due to file system limits, or 
    due to it being a database or some other non-filesystem tool.

    This also tests to make sure that the functions work with both
    generators and lists (assuming iter(list) is effectively a generator)
    """
    
    def setUp(self):
        super(TestTransportImplementation, self).setUp()
        self._server = self.transport_server()
        self._server.setUp()

    def tearDown(self):
        super(TestTransportImplementation, self).tearDown()
        self._server.tearDown()
        
    def check_transport_contents(self, content, transport, relpath):
        """Check that transport.get(relpath).read() == content."""
        self.assertEqual(content, transport.get(relpath).read())

    def get_transport(self):
        """Return a connected transport to the local directory."""
        t = bzrlib.transport.get_transport(self._server.get_url())
        self.failUnless(isinstance(t, self.transport_class), 
                        "Got the wrong class from get_transport"
                        "(%r, expected %r)" % (t.__class__, 
                                               self.transport_class))
        return t

    def assertListRaises(self, excClass, func, *args, **kwargs):
        """Many transport functions can return generators this makes sure
        to wrap them in a list() call to make sure the whole generator
        is run, and that the proper exception is raised.
        """
        try:
            list(func(*args, **kwargs))
        except excClass:
            return
        else:
            if hasattr(excClass,'__name__'): excName = excClass.__name__
            else: excName = str(excClass)
            raise self.failureException, "%s not raised" % excName

    def test_has(self):
        t = self.get_transport()

        files = ['a', 'b', 'e', 'g', '%']
        self.build_tree(files, transport=t)
        self.assertEqual(True, t.has('a'))
        self.assertEqual(False, t.has('c'))
        self.assertEqual(True, t.has(urlescape('%')))
        self.assertEqual(list(t.has_multi(['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'])),
                [True, True, False, False, True, False, True, False])
        self.assertEqual(True, t.has_any(['a', 'b', 'c']))
        self.assertEqual(False, t.has_any(['c', 'd', 'f', urlescape('%%')]))
        self.assertEqual(list(t.has_multi(iter(['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']))),
                [True, True, False, False, True, False, True, False])
        self.assertEqual(False, t.has_any(['c', 'c', 'c']))
        self.assertEqual(True, t.has_any(['b', 'b', 'b']))

    def test_get(self):
        t = self.get_transport()

        files = ['a', 'b', 'e', 'g']
        contents = ['contents of a\n',
                    'contents of b\n',
                    'contents of e\n',
                    'contents of g\n',
                    ]
        self.build_tree(files, transport=t)
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

    def test_put(self):
        t = self.get_transport()

        if t.is_readonly():
            self.assertRaises(TransportNotPossible,
                    t.put, 'a', 'some text for a\n')
            return

        t.put('a', StringIO('some text for a\n'))
        self.failUnless(t.has('a'))
        self.check_transport_contents('some text for a\n', t, 'a')
        # Make sure 'has' is updated
        self.assertEqual(list(t.has_multi(['a', 'b', 'c', 'd', 'e'])),
                [True, False, False, False, False])
        # Put also replaces contents
        self.assertEqual(t.put_multi([('a', StringIO('new\ncontents for\na\n')),
                                      ('d', StringIO('contents\nfor d\n'))]),
                         2)
        self.assertEqual(list(t.has_multi(['a', 'b', 'c', 'd', 'e'])),
                [True, False, False, True, False])
        self.check_transport_contents('new\ncontents for\na\n', t, 'a')
        self.check_transport_contents('contents\nfor d\n', t, 'd')

        self.assertEqual(
            t.put_multi(iter([('a', StringIO('diff\ncontents for\na\n')),
                              ('d', StringIO('another contents\nfor d\n'))])),
                        2)
        self.check_transport_contents('diff\ncontents for\na\n', t, 'a')
        self.check_transport_contents('another contents\nfor d\n', t, 'd')

        self.assertRaises(NoSuchFile,
                          t.put, 'path/doesnt/exist/c', 'contents')

    def test_put_permissions(self):
        t = self.get_transport()

        if t.is_readonly():
            return
        t.put('mode644', StringIO('test text\n'), mode=0644)
        self.assertMode(t, 'mode644', 0644)
        t.put('mode666', StringIO('test text\n'), mode=0666)
        self.assertMode(t, 'mode666', 0666)
        t.put('mode600', StringIO('test text\n'), mode=0600)
        self.assertMode(t, 'mode600', 0600)
        # Yes, you can put a file such that it becomes readonly
        t.put('mode400', StringIO('test text\n'), mode=0400)
        self.assertMode(t, 'mode400', 0400)
        t.put_multi([('mmode644', StringIO('text\n'))], mode=0644)
        self.assertMode(t, 'mmode644', 0644)
        
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
        self.assertEqual(
            t.put_multi([('dir_a/a', StringIO('contents of dir_a/a')),
                         ('dir_b/b', StringIO('contents of dir_b/b'))])
                        , 2)
        self.check_transport_contents('contents of dir_a/a', t, 'dir_a/a')
        self.check_transport_contents('contents of dir_b/b', t, 'dir_b/b')

        # mkdir of a dir with an absent parent
        self.assertRaises(NoSuchFile, t.mkdir, 'missing/dir')

    def test_mkdir_permissions(self):
        t = self.get_transport()
        if t.is_readonly():
            return
        # Test mkdir with a mode
        t.mkdir('dmode755', mode=0755)
        self.assertMode(t, 'dmode755', 0755)
        t.mkdir('dmode555', mode=0555)
        self.assertMode(t, 'dmode555', 0555)
        t.mkdir('dmode777', mode=0777)
        self.assertMode(t, 'dmode777', 0777)
        t.mkdir('dmode700', mode=0700)
        self.assertMode(t, 'dmode700', 0700)
        # TODO: jam 20051215 test mkdir_multi with a mode
        t.mkdir_multi(['mdmode755'], mode=0755)
        self.assertMode(t, 'mdmode755', 0755)

    def test_copy_to(self):
        from bzrlib.transport.memory import MemoryTransport
        t = self.get_transport()

        files = ['a', 'b', 'c', 'd']
        self.build_tree(files, transport=t)

        temp_transport = MemoryTransport('memory:/')

        t.copy_to(files, temp_transport)
        for f in files:
            self.check_transport_contents(temp_transport.get(f).read(),
                                          t, f)

        # Test that copying into a missing directory raises
        # NoSuchFile
        if t.is_readonly():
            os.mkdir('e')
            open('e/f', 'wb').write('contents of e')
        else:
            t.mkdir('e')
            t.put('e/f', StringIO('contents of e'))
        self.assertRaises(NoSuchFile, t.copy_to, ['e/f'], temp_transport)
        temp_transport.mkdir('e')
        t.copy_to(['e/f'], temp_transport)

        del temp_transport
        temp_transport = MemoryTransport('memory:/')

        files = ['a', 'b', 'c', 'd']
        t.copy_to(iter(files), temp_transport)
        for f in files:
            self.check_transport_contents(temp_transport.get(f).read(),
                                          t, f)
        del temp_transport

        for mode in (0666, 0644, 0600, 0400):
            temp_transport = MemoryTransport("memory:/")
            t.copy_to(files, temp_transport, mode=mode)
            for f in files:
                self.assertMode(temp_transport, f, mode)

    def test_append(self):
        t = self.get_transport()

        if t.is_readonly():
            open('a', 'wb').write('diff\ncontents for\na\n')
            open('b', 'wb').write('contents\nfor b\n')
        else:
            t.put_multi([
                    ('a', StringIO('diff\ncontents for\na\n')),
                    ('b', StringIO('contents\nfor b\n'))
                    ])

        if t.is_readonly():
            self.assertRaises(TransportNotPossible,
                    t.append, 'a', 'add\nsome\nmore\ncontents\n')
            _append('a', StringIO('add\nsome\nmore\ncontents\n'))
        else:
            t.append('a', StringIO('add\nsome\nmore\ncontents\n'))

        self.check_transport_contents(
            'diff\ncontents for\na\nadd\nsome\nmore\ncontents\n',
            t, 'a')

        if t.is_readonly():
            self.assertRaises(TransportNotPossible,
                    t.append_multi,
                        [('a', 'and\nthen\nsome\nmore\n'),
                         ('b', 'some\nmore\nfor\nb\n')])
            _append('a', StringIO('and\nthen\nsome\nmore\n'))
            _append('b', StringIO('some\nmore\nfor\nb\n'))
        else:
            t.append_multi([('a', StringIO('and\nthen\nsome\nmore\n')),
                    ('b', StringIO('some\nmore\nfor\nb\n'))])
        self.check_transport_contents(
            'diff\ncontents for\na\n'
            'add\nsome\nmore\ncontents\n'
            'and\nthen\nsome\nmore\n',
            t, 'a')
        self.check_transport_contents(
                'contents\nfor b\n'
                'some\nmore\nfor\nb\n',
                t, 'b')

        if t.is_readonly():
            _append('a', StringIO('a little bit more\n'))
            _append('b', StringIO('from an iterator\n'))
        else:
            t.append_multi(iter([('a', StringIO('a little bit more\n')),
                    ('b', StringIO('from an iterator\n'))]))
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

        if t.is_readonly():
            _append('c', StringIO('some text\nfor a missing file\n'))
            _append('a', StringIO('some text in a\n'))
            _append('d', StringIO('missing file r\n'))
        else:
            t.append('c', StringIO('some text\nfor a missing file\n'))
            t.append_multi([('a', StringIO('some text in a\n')),
                            ('d', StringIO('missing file r\n'))])
        self.check_transport_contents(
            'diff\ncontents for\na\n'
            'add\nsome\nmore\ncontents\n'
            'and\nthen\nsome\nmore\n'
            'a little bit more\n'
            'some text in a\n',
            t, 'a')
        self.check_transport_contents('some text\nfor a missing file\n',
                                      t, 'c')
        self.check_transport_contents('missing file r\n', t, 'd')
        
        # a file with no parent should fail..
        if not t.is_readonly():
            self.assertRaises(NoSuchFile,
                              t.append, 'missing/path', 
                              StringIO('content'))

    def test_append_file(self):
        t = self.get_transport()

        contents = [
            ('f1', StringIO('this is a string\nand some more stuff\n')),
            ('f2', StringIO('here is some text\nand a bit more\n')),
            ('f3', StringIO('some text for the\nthird file created\n')),
            ('f4', StringIO('this is a string\nand some more stuff\n')),
            ('f5', StringIO('here is some text\nand a bit more\n')),
            ('f6', StringIO('some text for the\nthird file created\n'))
        ]
        
        if t.is_readonly():
            for f, val in contents:
                open(f, 'wb').write(val.read())
        else:
            t.put_multi(contents)

        a1 = StringIO('appending to\none\n')
        if t.is_readonly():
            _append('f1', a1)
        else:
            t.append('f1', a1)

        del a1

        self.check_transport_contents(
                'this is a string\nand some more stuff\n'
                'appending to\none\n',
                t, 'f1')

        a2 = StringIO('adding more\ntext to two\n')
        a3 = StringIO('some garbage\nto put in three\n')

        if t.is_readonly():
            _append('f2', a2)
            _append('f3', a3)
        else:
            t.append_multi([('f2', a2), ('f3', a3)])

        del a2, a3

        self.check_transport_contents(
                'here is some text\nand a bit more\n'
                'adding more\ntext to two\n',
                t, 'f2')
        self.check_transport_contents( 
                'some text for the\nthird file created\n'
                'some garbage\nto put in three\n',
                t, 'f3')

        # Test that an actual file object can be used with put
        a4 = t.get('f1')
        if t.is_readonly():
            _append('f4', a4)
        else:
            t.append('f4', a4)

        del a4

        self.check_transport_contents(
                'this is a string\nand some more stuff\n'
                'this is a string\nand some more stuff\n'
                'appending to\none\n',
                t, 'f4')

        a5 = t.get('f2')
        a6 = t.get('f3')
        if t.is_readonly():
            _append('f5', a5)
            _append('f6', a6)
        else:
            t.append_multi([('f5', a5), ('f6', a6)])

        del a5, a6

        self.check_transport_contents(
                'here is some text\nand a bit more\n'
                'here is some text\nand a bit more\n'
                'adding more\ntext to two\n',
                t, 'f5')
        self.check_transport_contents(
                'some text for the\nthird file created\n'
                'some text for the\nthird file created\n'
                'some garbage\nto put in three\n',
                t, 'f6')

        a5 = t.get('f2')
        a6 = t.get('f2')
        a7 = t.get('f3')
        if t.is_readonly():
            _append('c', a5)
            _append('a', a6)
            _append('d', a7)
        else:
            t.append('c', a5)
            t.append_multi([('a', a6), ('d', a7)])
        del a5, a6, a7
        self.check_transport_contents(t.get('f2').read(), t, 'c')
        self.check_transport_contents(t.get('f3').read(), t, 'd')


    def test_delete(self):
        # TODO: Test Transport.delete
        t = self.get_transport()

        # Not much to do with a readonly transport
        if t.is_readonly():
            return

        t.put('a', StringIO('a little bit of text\n'))
        self.failUnless(t.has('a'))
        t.delete('a')
        self.failIf(t.has('a'))

        self.assertRaises(NoSuchFile, t.delete, 'a')

        t.put('a', StringIO('a text\n'))
        t.put('b', StringIO('b text\n'))
        t.put('c', StringIO('c text\n'))
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

        t.put('a', StringIO('another a text\n'))
        t.put('c', StringIO('another c text\n'))
        t.delete_multi(iter(['a', 'b', 'c']))

        # We should have deleted everything
        # SftpServer creates control files in the
        # working directory, so we can just do a
        # plain "listdir".
        # self.assertEqual([], os.listdir('.'))

    def test_move(self):
        t = self.get_transport()

        if t.is_readonly():
            return

        # TODO: I would like to use os.listdir() to
        # make sure there are no extra files, but SftpServer
        # creates control files in the working directory
        # perhaps all of this could be done in a subdirectory

        t.put('a', StringIO('a first file\n'))
        self.assertEquals([True, False], list(t.has_multi(['a', 'b'])))

        t.move('a', 'b')
        self.failUnless(t.has('b'))
        self.failIf(t.has('a'))

        self.check_transport_contents('a first file\n', t, 'b')
        self.assertEquals([False, True], list(t.has_multi(['a', 'b'])))

        # Overwrite a file
        t.put('c', StringIO('c this file\n'))
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

        t.put('a', StringIO('a file\n'))
        t.copy('a', 'b')
        self.check_transport_contents('a file\n', t, 'b')

        self.assertRaises(NoSuchFile, t.copy, 'c', 'd')
        os.mkdir('c')
        # What should the assert be if you try to copy a
        # file over a directory?
        #self.assertRaises(Something, t.copy, 'a', 'c')
        t.put('d', StringIO('text in d\n'))
        t.copy('d', 'b')
        self.check_transport_contents('text in d\n', t, 'b')

        # TODO: test copy_multi

    def test_connection_error(self):
        """ConnectionError is raised when connection is impossible"""
        try:
            url = self._server.get_bogus_url()
        except NotImplementedError:
            raise TestSkipped("Transport %s has no bogus URL support." %
                              self._server.__class__)
        t = bzrlib.transport.get_transport(url)
        try:
            t.get('.bzr/branch')
        except (ConnectionError, NoSuchFile), e:
            pass
        except (Exception), e:
            self.failIf(True, 'Wrong exception thrown: %s' % e)
        else:
            self.failIf(True, 'Did not get the expected exception.')

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
        self.build_tree(paths, transport=t)

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
        t.mkdir('wd')
        t = t.clone('wd')

        self.assertEqual([], sorted_list(u'.'))
        self.build_tree(['a', 'b', 'c/', 'c/d', 'c/e'], transport=t)

        self.assertEqual([u'a', u'b', u'c'], sorted_list(u'.'))
        self.assertEqual([u'd', u'e'], sorted_list(u'c'))

        t.delete('c/d')
        t.delete('b')
        self.assertEqual([u'a', u'c'], sorted_list('.'))
        self.assertEqual([u'e'], sorted_list(u'c'))

        self.assertListRaises(NoSuchFile, t.list_dir, 'q')
        self.assertListRaises(NoSuchFile, t.list_dir, 'c/f')
        self.assertListRaises(NoSuchFile, t.list_dir, 'a')

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
            t2.put('d', StringIO('newfile\n'))

        self.failUnless(t1.has('b/d'))
        self.failUnless(t2.has('d'))
        self.failUnless(t3.has('b/d'))

    def test_relpath(self):
        t = self.get_transport()
        self.assertEqual('', t.relpath(t.base))
        # base ends with /
        self.assertEqual('', t.relpath(t.base[:-1]))
        # subdirs which dont exist should still give relpaths.
        self.assertEqual('foo', t.relpath(t.base + 'foo'))
        # trailing slash should be the same.
        self.assertEqual('foo', t.relpath(t.base + 'foo/'))

    def test_abspath(self):
        # smoke test for abspath. Corner cases for backends like unix fs's
        # that have aliasing problems like symlinks should go in backend
        # specific test cases.
        transport = self.get_transport()
        self.assertEqual(transport.base + 'relpath',
                         transport.abspath('relpath'))

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
                         'isolated/bar'],
                        transport=transport)
        transport = transport.clone('isolated')
        paths = set(transport.iter_files_recursive())
        self.assertEqual(set(['dir/foo', 'dir/bar', 'bar']), paths)
