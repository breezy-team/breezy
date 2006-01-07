# Copyright (C) 2006 by Canonical Ltd
# -*- coding: utf-8 -*-

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

"""\
Black-box tests for bzr handling non-ascii characters.
"""

import sys
import os
import bzrlib
from bzrlib.tests import TestCaseInTempDir, TestSkipped
from bzrlib.trace import mutter, note

_mu = u'\xb5'
# Swedish?
_erik = u'Erik B\xe5gfors'
# Swedish 'räksmörgås' means shrimp sandwich
_shrimp_sandwich = u'r\xe4ksm\xf6rg\xe5s'
# TODO: jam 20060105 Is there a way we can decode punycode for people
#       who have non-ascii email addresses? Does it matter to us, we
#       really would have no problem just using utf-8 internally, since
#       we don't actually ever send email to these addresses.
_punycode_erik = 'Bgfors-iua'
# Arabic, probably only Unicode encodings can handle this one
_juju = u'\u062c\u0648\u062c\u0648'
# Alternative for arabic
_juju_alt = u'j\xfbj\xfa'
# Russian
_alexander = u'\u0410\u043b\u0435\u043a\u0441\u0430\u043d\u0434\u0440'


class TestNonAscii(TestCaseInTempDir):

    def setUp(self):
        super(TestNonAscii, self).setUp()
        self._orig_email = os.environ.get('BZREMAIL', None)
        email = _erik + u' <joe@foo.com>'
        try:
            os.environ['BZREMAIL'] = email.encode(bzrlib.user_encoding)
        except UnicodeEncodeError:
            note('Unable to test unicode in BZREMAIL')
            # Do the rest of the tests, just don't expect
            # _erik to exist in the email
            os.environ['BZREMAIL'] = 'Erik Bagfors <joe@foo.com>'
            self.email_name = 'Erik Bagfors'
        else:
            self.email_name = _erik

        bzr = self.run_bzr
        bzr('init')
        open('a', 'wb').write('foo\n')
        bzr('add', 'a')
        bzr('commit', '-m', 'adding a')
        open('b', 'wb').write(_shrimp_sandwich.encode('utf-8') + '\n')
        bzr('add', 'b')
        bzr('commit', '-m', u'Creating a ' + _shrimp_sandwich)
        fname = _juju + '.txt'
        try:
            open(fname, 'wb').write('unicode filename\n')
        except UnicodeEncodeError:
            note('Unable to create an arabic filename')
            fname = _juju_alt + '.txt'
            try:
                open(fname, 'wb').write('unicode filename\n')
            except UnicodeEncodeError:
                raise TestSkipped("can't create an arabic or european filename"
                    " in filesystem encoding %s" % sys.getfilesystemencoding())
            else:
                self.juju = _juju_alt
        else:
            self.juju = _juju

        bzr('add', fname)
        bzr('commit', '-m', u'And an unicode file\n')
    
    def tearDown(self):
        if self._orig_email is not None:
            os.environ['BZREMAIL'] = self._orig_email
        else:
            if os.environ.get('BZREMAIL', None) is not None:
                del os.environ['BZREMAIL']
        super(TestNonAscii, self).tearDown()

    def test_ls(self):
        bzr = self.run_bzr_decode

        txt = bzr('ls')
        self.assertEqual(['a', 'b', u'\u062c\u0648\u062c\u0648.txt'],
                         txt.splitlines())
        txt = bzr('ls', '--null')
        self.assertEqual(['a', 'b', u'\u062c\u0648\u062c\u0648.txt', ''],
                         txt.split('\0'))

        txt = bzr('ls', encoding='ascii', retcode=3)
        txt = bzr('ls', '--null', encoding='ascii', retcode=3)

    def test_status(self):
        bzr = self.run_bzr_decode

        open(self.juju + '.txt', 'ab').write('added something\n')
        txt = bzr('status')
        self.assertEqual(u'modified:\n  \u062c\u0648\u062c\u0648.txt\n' , txt)

    def test_cat(self):
        # bzr cat shouldn't change the contents
        # using run_bzr since that doesn't decode
        txt = self.run_bzr('cat', 'b')[0]
        self.assertEqual(_shrimp_sandwich.encode('utf-8') + '\n', txt)

        txt = self.run_bzr('cat', self.juju + '.txt')[0]
        self.assertEqual('unicode filename\n', txt)

    def test_cat_revision(self):
        bzr = self.run_bzr_decode

        txt = bzr('cat-revision', '-r', '1')
        self.assertNotEqual(-1, txt.find(self.email_name))

        txt = bzr('cat-revision', '-r', '2')
        self.assertNotEqual(-1, txt.find(_shrimp_sandwich))

    def test_mkdir(self):
        bzr = self.run_bzr_decode

        txt = bzr('mkdir', _shrimp_sandwich)
        self.assertEqual('added ' + _shrimp_sandwich + '\n', txt)

    def test_relpath(self):
        bzr = self.run_bzr_decode

        txt = bzr('relpath', _shrimp_sandwich)
        self.assertEqual(_shrimp_sandwich + '\n', txt)

        # TODO: jam 20060106 if relpath can return a munged string
        #       this text needs to be fixed
        bzr('relpath', _shrimp_sandwich, encoding='ascii',
                 retcode=3)

    def test_inventory(self):
        bzr = self.run_bzr_decode

        txt = bzr('inventory')
        self.assertEqual(['a', 'b', u'\u062c\u0648\u062c\u0648.txt'],
                         txt.splitlines())

        # inventory should fail if unable to encode
        bzr('inventory', encoding='ascii', retcode=3)

        # We don't really care about the ids themselves,
        # but the command shouldn't fail
        txt = bzr('inventory', '--show-ids')

    def test_revno(self):
        # There isn't a lot to test here, since revno should always
        # be an integer
        bzr = self.run_bzr_decode

        self.assertEqual('3\n', bzr('revno'))

    def test_revision_info(self):
        bzr = self.run_bzr_decode

        bzr('revision-info', '-r', '1')

        # TODO: jam 20060105 We have no revisions with non-ascii characters.
        bzr('revision-info', '-r', '1', encoding='ascii')

    def test_mv(self):
        bzr = self.run_bzr_decode

        fname1 = self.juju + '.txt'
        fname2 = self.juju + '2.txt'

        bzr('mv', 'a', fname1, retcode=3)

        txt = bzr('mv', 'a', fname2)
        self.assertEqual(u'a => ' + fname2 + '\n', txt)
        self.failIfExists('a')
        self.failUnlessExists(fname2)

        bzr('commit', '-m', 'renamed to non-ascii')

        bzr('mkdir', _shrimp_sandwich)
        txt = bzr('mv', fname1, fname2, _shrimp_sandwich)
        self.assertEqual([fname1 + ' => ' + _shrimp_sandwich + '/' + fname1,
                          fname2 + ' => ' + _shrimp_sandwich + '/' + fname2]
                         , txt.splitlines())

        # The rename should still succeed
        txt = bzr('mv', _shrimp_sandwich + '/' + fname2, 'a',
            encoding='ascii')
        self.failUnlessExists('a')
        self.assertEqual('r?ksm?rg?s/????2.txt => a\n', txt)

    def test_branch(self):
        # We should be able to branch into a directory that
        # has a unicode name, even if we can't display the name
        bzr = self.run_bzr_decode

        bzr('branch', u'.', _shrimp_sandwich)

        bzr('branch', u'.', _shrimp_sandwich + '2', encoding='ascii')

    def test_pull(self):
        # Make sure we can pull from paths that can't be encoded
        bzr = self.run_bzr_decode

        bzr('branch', '.', _shrimp_sandwich)
        bzr('branch', _shrimp_sandwich, _shrimp_sandwich + '2')

        os.chdir(_shrimp_sandwich)
        open('a', 'ab').write('more text\n')
        bzr('commit', '-m', 'mod a')

        pwd = os.getcwdu()

        os.chdir('../' + _shrimp_sandwich + '2')
        txt = bzr('pull')

        self.assertEqual(u'Using saved location: %s\n' % (pwd,), txt)

        os.chdir('../' + _shrimp_sandwich)
        open('a', 'ab').write('and yet more\n')
        # here we cheat. If self.erik is not _erik, then technically
        # we would not be able to supply the argument, since sys.argv
        # could not be decoded to those characters.
        # but self.run_bzr takes the decoded string directly
        bzr('commit', '-m', 'modifying a by ' + _erik)

        os.chdir('../' + _shrimp_sandwich + '2')
        # We should be able to pull, even if our encoding is bad
        bzr('pull', '--verbose', encoding='ascii')

    def test_push(self):
        # TODO: Test push to an SFTP location
        # Make sure we can pull from paths that can't be encoded
        bzr = self.run_bzr_decode

        # ConfigObj has to be modified to make it allow unicode
        # strings. It seems to have the functionality, but doesn't
        # like to use it.
        bzr('push', _shrimp_sandwich)

        open('a', 'ab').write('adding more text\n')
        bzr('commit', '-m', 'added some stuff')

        bzr('push')

        f = open('a', 'ab')
        f.write('and a bit more: ')
        f.write(_shrimp_sandwich.encode('utf-8'))
        f.write('\n')
        f.close()
        bzr('commit', '-m', u'Added some ' + _shrimp_sandwich)
        bzr('push', '--verbose', encoding='ascii')

        bzr('push', '--verbose', _shrimp_sandwich + '2')

        bzr('push', '--verbose', _shrimp_sandwich + '3',
            encoding='ascii')

    def test_renames(self):
        bzr = self.run_bzr_decode

        fname = self.juju + '2.txt'
        bzr('mv', 'a', fname)
        txt = bzr('renames')
        self.assertEqual('a => ' + fname + '\n', txt)

        bzr('renames', retcode=3, encoding='ascii')

    def test_remove(self):
        bzr = self.run_bzr_decode

        fname = self.juju + '.txt'
        txt = bzr('remove', fname, encoding='ascii')

    def test_remove_verbose(self):
        bzr = self.run_bzr_decode

        raise TestSkipped('bzr remove --verbose uses tree.remove, which calls print directly.')
        fname = self.juju + '.txt'
        txt = bzr('remove', '--verbose', fname, encoding='ascii')

    def test_file_id(self):
        bzr = self.run_bzr_decode

        fname = self.juju + '.txt'
        txt = bzr('file-id', fname)

        # TODO: jam 20060106 We don't support non-ascii file ids yet, 
        #       so there is nothing which would fail in ascii encoding
        #       This *should* be retcode=3
        txt = bzr('file-id', fname, encoding='ascii')

    def test_file_path(self):
        bzr = self.run_bzr_decode

        # Create a directory structure
        fname = self.juju + '.txt'
        bzr('mkdir', 'base')
        bzr('mkdir', 'base/' + _shrimp_sandwich)
        path = '/'.join(['base', _shrimp_sandwich, fname])
        bzr('mv', fname, path)
        bzr('commit', '-m', 'moving things around')

        txt = bzr('file-path', path)

        # TODO: jam 20060106 We don't support non-ascii file ids yet, 
        #       so there is nothing which would fail in ascii encoding
        #       This *should* be retcode=3
        txt = bzr('file-path', path, encoding='ascii')

    def test_revision_history(self):
        bzr = self.run_bzr_decode

        # TODO: jam 20060106 We don't support non-ascii revision ids yet, 
        #       so there is nothing which would fail in ascii encoding
        txt = bzr('revision-history')

    def test_ancestry(self):
        bzr = self.run_bzr_decode

        # TODO: jam 20060106 We don't support non-ascii revision ids yet, 
        #       so there is nothing which would fail in ascii encoding
        txt = bzr('ancestry')

    def test_diff(self):
        # TODO: jam 20060106 diff is a difficult one to test, because it 
        #       shouldn't encode the file contents, but it needs some sort
        #       of encoding for the paths, etc which are displayed.
        pass

    def test_deleted(self):
        bzr = self.run_bzr_decode

        fname = self.juju + '.txt'
        os.remove(fname)
        bzr('rm', fname)

        txt = bzr('deleted')
        self.assertEqual(fname+'\n', txt)

        txt = bzr('deleted', '--show-ids')
        self.failUnless(txt.startswith(fname))

        # Deleted should fail if cannot decode
        # Because it is giving the exact paths
        # which might be used by a front end
        bzr('deleted', encoding='ascii', retcode=3)

    def test_modified(self):
        bzr = self.run_bzr_decode

        fname = self.juju + '.txt'
        open(fname, 'ab').write('modified\n')

        txt = bzr('modified')
        self.assertEqual(fname+'\n', txt)

        bzr('modified', encoding='ascii', retcode=3)

    def test_added(self):
        bzr = self.run_bzr_decode

        fname = self.juju + '2.txt'
        open(fname, 'wb').write('added\n')
        bzr('add', fname)

        txt = bzr('added')
        self.assertEqual(fname+'\n', txt)

        bzr('added', encoding='ascii', retcode=3)

    def test_root(self):
        bzr = self.run_bzr_decode

        bzr('root')

        bzr('branch', u'.', _shrimp_sandwich)

        os.chdir(_shrimp_sandwich)

        txt = bzr('root')
        self.failUnless(txt.endswith(_shrimp_sandwich+'\n'))

        txt = bzr('root', encoding='ascii', retcode=3)

    def test_log(self):
        bzr = self.run_bzr_decode

        txt = bzr('log')
        self.assertNotEqual(-1, txt.find(self.email_name))
        self.assertNotEqual(-1, txt.find(_shrimp_sandwich))

        txt = bzr('log', '--verbose')
        self.assertNotEqual(-1, txt.find(self.juju))

        # Make sure log doesn't fail even if we can't write out
        txt = bzr('log', '--verbose', encoding='ascii')
        self.assertEqual(-1, txt.find(self.juju))
        self.assertNotEqual(-1, txt.find(self.juju.encode('ascii', 'replace')))

    def test_touching_revisions(self):
        bzr = self.run_bzr_decode

        fname = self.juju + '.txt'
        txt = bzr('touching-revisions', fname)
        self.assertEqual(u'     3 added %s\n' % (fname,), txt)

        fname_new = _shrimp_sandwich + '.txt'
        bzr('mv', fname, fname_new)
        bzr('commit', '-m', u'Renamed %s => %s' % (fname, fname_new))

        txt = bzr('touching-revisions', fname_new)
        expected_txt = (u'     3 added %s\n' 
                        u'     4 renamed %s => %s\n'
                        % (fname, fname, fname_new))
        self.assertEqual(expected_txt, txt)

        txt = bzr('touching-revisions', fname_new, encoding='ascii')
        expected_ascii = expected_txt.encode('ascii', 'replace')
        self.assertEqual(expected_ascii, txt)


