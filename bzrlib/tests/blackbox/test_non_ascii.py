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


class TestNonAscii(TestCaseInTempDir):

    def setUp(self):
        super(TestNonAscii, self).setUp()
        self._orig_email = os.environ.get('BZREMAIL', None)
        email = _erik + u' <joe@foo.com>'
        try:
            os.environ['BZREMAIL'] = email.encode(bzrlib.user_encoding)
        except UnicodeEncodeError:
            raise TestSkipped('Cannot encode Erik B?gfors in encoding %s' 
                              % bzrlib.user_encoding)

        bzr = self.run_bzr
        bzr('init')
        open('a', 'wb').write('foo\n')
        bzr('add', 'a')
        bzr('commit', '-m', 'adding a')
        open('b', 'wb').write(_shrimp_sandwich.encode('utf-8') + '\n')
        bzr('add', 'b')
        bzr('commit', '-m', u'Creating a ' + _shrimp_sandwich)
        # TODO: jam 20060105 Handle the case where we can't create a
        #       unicode filename on the current filesytem. I don't know
        #       what exception would be raised, because all of my
        #       filesystems support it. :)
        fname = _juju + '.txt'
        open(fname, 'wb').write('arabic filename\n')
        bzr('add', fname)
        bzr('commit', '-m', u'And an arabic file\n')
    
    def tearDown(self):
        if self._orig_email is not None:
            os.environ['BZREMAIL'] = self._orig_email
        else:
            if os.environ.get('BZREMAIL', None) is not None:
                del os.environ['BZREMAIL']
        super(TestNonAscii, self).tearDown()

    def test_log(self):
        bzr = self.run_bzr_decode

        txt = bzr('log')
        self.assertNotEqual(-1, txt.find(_erik))
        self.assertNotEqual(-1, txt.find(_shrimp_sandwich))

        txt = bzr('log', '--verbose')
        self.assertNotEqual(-1, txt.find(_juju))

        # Make sure log doesn't fail even if we can't write out
        txt = bzr('log', '--verbose', encoding='ascii')
        self.assertEqual(-1, txt.find(_juju))
        self.assertNotEqual(-1, txt.find(_juju.encode('ascii', 'replace')))

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

        open(_juju + '.txt', 'ab').write('added something\n')
        txt = bzr('status')
        self.assertEqual(u'modified:\n  \u062c\u0648\u062c\u0648.txt\n' , txt)

    def test_cat(self):
        # bzr cat shouldn't change the contents
        # using run_bzr since that doesn't decode
        txt = self.run_bzr('cat', 'b')[0]
        self.assertEqual(_shrimp_sandwich.encode('utf-8') + '\n', txt)

        txt = self.run_bzr('cat', _juju + '.txt')[0]
        self.assertEqual('arabic filename\n', txt)

    def test_cat_revision(self):
        bzr = self.run_bzr_decode

        txt = bzr('cat-revision', '-r', '1')
        self.assertNotEqual(-1, txt.find(_erik))

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

        fname1 = _juju + '.txt'
        fname2 = _juju + '2.txt'

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

        fname = _juju + '2.txt'
        bzr('mv', 'a', fname)
        txt = bzr('renames')
        self.assertEqual('a => ' + fname + '\n', txt)

        bzr('renames', retcode=3, encoding='ascii')

    def test_remove(self):
        bzr = self.run_bzr_decode

        fname = _juju + '.txt'
        txt = bzr('remove', fname, encoding='ascii')

    def test_remove_verbose(self):
        bzr = self.run_bzr_decode

        raise TestSkipped('bzr remove --verbose uses tree.remove, which calls print directly.')
        fname = _juju + '.txt'
        txt = bzr('remove', '--verbose', fname, encoding='ascii')

