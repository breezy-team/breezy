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


from bzrlib.selftest import TestCaseInTempDir
from bzrlib.selftest.HTTPTestUtil import TestCaseWithWebserver
from bzrlib.errors import NoSuchFile, FileExists, TransportNotPossible
from cStringIO import StringIO

def _append(fn, txt):
    """Append the given text (file-like object) to the supplied filename."""
    f = open(fn, 'ab')
    f.write(txt)
    f.flush()
    f.close()
    del f

def test_transport(tester, t, readonly=False):
    """Test a transport object. Basically, it assumes that the
    Transport object is connected to the current working directory.
    So that whatever is done through the transport, should show
    up in the working directory, and vice-versa.

    This also tests to make sure that the functions work with both
    generators and lists (assuming iter(list) is effectively a generator)
    """
    import tempfile, os
    from bzrlib.transport.local import LocalTransport

    # Test has
    files = ['a', 'b', 'e', 'g']
    tester.build_tree(files)
    tester.assertEqual(t.has('a'), True)
    tester.assertEqual(t.has('c'), False)
    tester.assertEqual(list(t.has_multi(['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'])),
            [True, True, False, False, True, False, True, False])
    tester.assertEqual(list(t.has_multi(iter(['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']))),
            [True, True, False, False, True, False, True, False])

    # Test get
    tester.assertEqual(t.get('a').read(), open('a').read())
    content_f = t.get_multi(files)
    for path,f in zip(files, content_f):
        tester.assertEqual(open(path).read(), f.read())

    content_f = t.get_multi(iter(files))
    for path,f in zip(files, content_f):
        tester.assertEqual(open(path).read(), f.read())

    tester.assertRaises(NoSuchFile, t.get, 'c')
    try:
        files = list(t.get_multi(['a', 'b', 'c']))
    except NoSuchFile:
        pass
    else:
        tester.fail('Failed to raise NoSuchFile for missing file in get_multi')
    try:
        files = list(t.get_multi(iter(['a', 'b', 'c', 'e'])))
    except NoSuchFile:
        pass
    else:
        tester.fail('Failed to raise NoSuchFile for missing file in get_multi')

    # Test put
    if readonly:
        tester.assertRaises(TransportNotPossible,
                t.put, 'c', 'some text for c\n')
        open('c', 'wb').write('some text for c\n')
    else:
        t.put('c', 'some text for c\n')
    tester.assert_(os.path.exists('c'))
    tester.check_file_contents('c', 'some text for c\n')
    tester.assertEqual(t.get('c').read(), 'some text for c\n')
    # Make sure 'has' is updated
    tester.assertEqual(list(t.has_multi(['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'])),
            [True, True, True, False, True, False, True, False])
    if readonly:
        tester.assertRaises(TransportNotPossible,
                t.put_multi,
                [('a', 'new\ncontents for\na\n'),
                    ('d', 'contents\nfor d\n')])
        open('a', 'wb').write('new\ncontents for\na\n')
        open('d', 'wb').write('contents\nfor d\n')
    else:
        # Put also replaces contents
        tester.assertEqual(t.put_multi([('a', 'new\ncontents for\na\n'),
                                      ('d', 'contents\nfor d\n')]),
                         2)
    tester.assertEqual(list(t.has_multi(['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'])),
            [True, True, True, True, True, False, True, False])
    tester.check_file_contents('a', 'new\ncontents for\na\n')
    tester.check_file_contents('d', 'contents\nfor d\n')

    if readonly:
        tester.assertRaises(TransportNotPossible,
            t.put_multi, iter([('a', 'diff\ncontents for\na\n'),
                              ('d', 'another contents\nfor d\n')]))
        open('a', 'wb').write('diff\ncontents for\na\n')
        open('d', 'wb').write('another contents\nfor d\n')
    else:
        tester.assertEqual(
            t.put_multi(iter([('a', 'diff\ncontents for\na\n'),
                              ('d', 'another contents\nfor d\n')]))
                         , 2)
    tester.check_file_contents('a', 'diff\ncontents for\na\n')
    tester.check_file_contents('d', 'another contents\nfor d\n')

    if readonly:
        tester.assertRaises(TransportNotPossible,
                t.put, 'path/doesnt/exist/c', 'contents')
    else:
        tester.assertRaises(NoSuchFile,
                t.put, 'path/doesnt/exist/c', 'contents')

    # Test mkdir
    os.mkdir('dir_a')
    tester.assertEqual(t.has('dir_a'), True)
    tester.assertEqual(t.has('dir_b'), False)

    if readonly:
        tester.assertRaises(TransportNotPossible,
                t.mkdir, 'dir_b')
        os.mkdir('dir_b')
    else:
        t.mkdir('dir_b')
    tester.assertEqual(t.has('dir_b'), True)
    tester.assert_(os.path.isdir('dir_b'))

    if readonly:
        tester.assertRaises(TransportNotPossible,
                t.mkdir_multi, ['dir_c', 'dir_d'])
        os.mkdir('dir_c')
        os.mkdir('dir_d')
    else:
        t.mkdir_multi(['dir_c', 'dir_d'])

    if readonly:
        tester.assertRaises(TransportNotPossible,
                t.mkdir_multi, iter(['dir_e', 'dir_f']))
        os.mkdir('dir_e')
        os.mkdir('dir_f')
    else:
        t.mkdir_multi(iter(['dir_e', 'dir_f']))
    tester.assertEqual(list(t.has_multi(
        ['dir_a', 'dir_b', 'dir_c', 'dir_q',
         'dir_d', 'dir_e', 'dir_f', 'dir_b'])),
        [True, True, True, False,
         True, True, True, True])
    for d in ['dir_a', 'dir_b', 'dir_c', 'dir_d', 'dir_e', 'dir_f']:
        tester.assert_(os.path.isdir(d))

    if not readonly:
        tester.assertRaises(NoSuchFile, t.mkdir, 'path/doesnt/exist')
        tester.assertRaises(FileExists, t.mkdir, 'dir_a') # Creating a directory again should fail

    # Make sure the transport recognizes when a
    # directory is created by other means
    # Caching Transports will fail, because dir_e was already seen not
    # to exist. So instead, we will search for a new directory
    #os.mkdir('dir_e')
    #if not readonly:
    #    tester.assertRaises(FileExists, t.mkdir, 'dir_e')

    os.mkdir('dir_g')
    if not readonly:
        tester.assertRaises(FileExists, t.mkdir, 'dir_g')

    # Test get/put in sub-directories
    if readonly:
        open('dir_a/a', 'wb').write('contents of dir_a/a')
        open('dir_b/b', 'wb').write('contents of dir_b/b')
    else:
        tester.assertEqual(
            t.put_multi([('dir_a/a', 'contents of dir_a/a'),
                         ('dir_b/b', 'contents of dir_b/b')])
                      , 2)
    for f in ('dir_a/a', 'dir_b/b'):
        tester.assertEqual(t.get(f).read(), open(f).read())

    # Test copy_to
    dtmp = tempfile.mkdtemp(dir='.', prefix='test-transport-')
    dtmp_base = os.path.basename(dtmp)
    local_t = LocalTransport(dtmp)

    files = ['a', 'b', 'c', 'd']
    t.copy_to(files, local_t)
    for f in files:
        tester.assertEquals(open(f).read(),
                open(os.path.join(dtmp_base, f)).read())

    del dtmp, dtmp_base, local_t

    dtmp = tempfile.mkdtemp(dir='.', prefix='test-transport-')
    dtmp_base = os.path.basename(dtmp)
    local_t = LocalTransport(dtmp)

    files = ['a', 'b', 'c', 'd']
    t.copy_to(iter(files), local_t)
    for f in files:
        tester.assertEquals(open(f).read(),
                open(os.path.join(dtmp_base, f)).read())

    del dtmp, dtmp_base, local_t

    # Test append, and append_multi
    if readonly:
        tester.assertRaises(TransportNotPossible,
                t.append, 'a', 'add\nsome\nmore\ncontents\n')
        _append('a', 'add\nsome\nmore\ncontents\n')
    else:
        t.append('a', 'add\nsome\nmore\ncontents\n')

    tester.check_file_contents('a', 
        'diff\ncontents for\na\nadd\nsome\nmore\ncontents\n')

    if readonly:
        tester.assertRaises(TransportNotPossible,
                t.append_multi,
                    [('a', 'and\nthen\nsome\nmore\n'),
                     ('d', 'some\nmore\nfor\nd\n')])
        _append('a', 'and\nthen\nsome\nmore\n')
        _append('d', 'some\nmore\nfor\nd\n')
    else:
        t.append_multi([('a', 'and\nthen\nsome\nmore\n'),
                ('d', 'some\nmore\nfor\nd\n')])
    tester.check_file_contents('a', 
        'diff\ncontents for\na\n'
        'add\nsome\nmore\ncontents\n'
        'and\nthen\nsome\nmore\n')
    tester.check_file_contents('d', 
            'another contents\nfor d\n'
            'some\nmore\nfor\nd\n')

    if readonly:
        _append('a', 'a little bit more\n')
        _append('d', 'from an iterator\n')
    else:
        t.append_multi(iter([('a', 'a little bit more\n'),
                ('d', 'from an iterator\n')]))
    tester.check_file_contents('a', 
        'diff\ncontents for\na\n'
        'add\nsome\nmore\ncontents\n'
        'and\nthen\nsome\nmore\n'
        'a little bit more\n')
    tester.check_file_contents('d', 
            'another contents\nfor d\n'
            'some\nmore\nfor\nd\n'
            'from an iterator\n')

    # Test that StringIO can be used as a file-like object with put
    f1 = StringIO('this is a string\nand some more stuff\n')
    if readonly:
        open('f1', 'wb').write(f1.read())
    else:
        t.put('f1', f1)

    del f1

    tester.check_file_contents('f1', 
            'this is a string\nand some more stuff\n')

    f2 = StringIO('here is some text\nand a bit more\n')
    f3 = StringIO('some text for the\nthird file created\n')

    if readonly:
        open('f2', 'wb').write(f2.read())
        open('f3', 'wb').write(f3.read())
    else:
        t.put_multi([('f2', f2), ('f3', f3)])

    del f2, f3

    tester.check_file_contents('f2', 'here is some text\nand a bit more\n')
    tester.check_file_contents('f3', 'some text for the\nthird file created\n')

    # Test that an actual file object can be used with put
    f4 = open('f1', 'rb')
    if readonly:
        open('f4', 'wb').write(f4.read())
    else:
        t.put('f4', f4)

    del f4

    tester.check_file_contents('f4', 
            'this is a string\nand some more stuff\n')

    f5 = open('f2', 'rb')
    f6 = open('f3', 'rb')
    if readonly:
        open('f5', 'wb').write(f5.read())
        open('f6', 'wb').write(f6.read())
    else:
        t.put_multi([('f5', f5), ('f6', f6)])

    del f5, f6

    tester.check_file_contents('f5', 'here is some text\nand a bit more\n')
    tester.check_file_contents('f6', 'some text for the\nthird file created\n')

    # Test that StringIO can be used as a file-like object with append
    a1 = StringIO('appending to\none\n')
    if readonly:
        _append('f1', a1.read())
    else:
        t.append('f1', a1)

    del a1

    tester.check_file_contents('f1', 
            'this is a string\nand some more stuff\n'
            'appending to\none\n')

    a2 = StringIO('adding more\ntext to two\n')
    a3 = StringIO('some garbage\nto put in three\n')

    if readonly:
        _append('f2', a2.read())
        _append('f3', a3.read())
    else:
        t.append_multi([('f2', a2), ('f3', a3)])

    del a2, a3

    tester.check_file_contents('f2',
            'here is some text\nand a bit more\n'
            'adding more\ntext to two\n')
    tester.check_file_contents('f3', 
            'some text for the\nthird file created\n'
            'some garbage\nto put in three\n')

    # Test that an actual file object can be used with put
    a4 = open('f1', 'rb')
    if readonly:
        _append('f4', a4.read())
    else:
        t.append('f4', a4)

    del a4

    tester.check_file_contents('f4', 
            'this is a string\nand some more stuff\n'
            'this is a string\nand some more stuff\n'
            'appending to\none\n')

    a5 = open('f2', 'rb')
    a6 = open('f3', 'rb')
    if readonly:
        _append('f5', a5.read())
        _append('f6', a6.read())
    else:
        t.append_multi([('f5', a5), ('f6', a6)])

    del a5, a6

    tester.check_file_contents('f5',
            'here is some text\nand a bit more\n'
            'here is some text\nand a bit more\n'
            'adding more\ntext to two\n')
    tester.check_file_contents('f6',
            'some text for the\nthird file created\n'
            'some text for the\nthird file created\n'
            'some garbage\nto put in three\n')

    # Test get_partial
    tester.assertRaises(NoSuchFile,
            t.get_partial, 'a-missing-file', 20)
    tester.assertRaises(NoSuchFile,
            t.get_partial, 'another-missing-file', 20, 30)
    f = t.get_partial('f5', 33)
    tester.assertEqual(f.read(), 
            'here is some text\nand a bit more\n'
            'adding more\ntext to two\n')
    f = t.get_partial('f5', 66)
    tester.assertEqual(f.read(), 
            'adding more\ntext to two\n')
    f = t.get_partial('f5', 66, 10)
    tester.assertEqual(f.read(10), 
            'adding mor')

    del f

    offsets = [('f5', 33), ('f6', 20, 10), ('f4', 10, 20)]
    values = ['here is some text\nand a bit more\nadding more\ntext to two\n',
              'ird file c',
              'string\nand some more'
             ]
    contents_f = t.get_partial_multi(offsets)
    count = 0
    for f, val in zip(contents_f, values):
        count += 1
        tester.assertEqual(val, f.read(len(val)))
    # Make sure we saw all values, and no extra
    tester.assertEqual(len(values), count)
    tester.assertEqual(list(contents_f), [])

    # Do the same thing with an iterator
    offsets = iter([('f5', 34), ('f6', 18, 10), ('f4', 15, 15)])
    values = ['ere is some text\nand a bit more\nadding more\ntext to two\n',
              'third file',
              'g\nand some more'
             ]
    contents_f = t.get_partial_multi(offsets)
    count = 0
    for f, val in zip(contents_f, values):
        count += 1
        tester.assertEqual(val, f.read(len(val)))
    tester.assertEqual(len(values), count)
    tester.assertEqual(list(contents_f), [])

    # TODO: Test delete, move, etc.
    # TODO: Test locking

class LocalTransportTest(TestCaseInTempDir):
    def test_local_transport(self):
        from bzrlib.transport.local import LocalTransport

        t = LocalTransport('.')
        test_transport(self, t)

class HttpTransportTest(TestCaseWithWebserver):
    def test_http_transport(self):
        from bzrlib.transport.http import HttpTransport

        url = self.get_remote_url('.')
        t = HttpTransport(url)
        test_transport(self, t, readonly=True)

