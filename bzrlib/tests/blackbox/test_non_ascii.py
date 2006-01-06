# Copyright (C) 2005 by Canonical Ltd
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
        # TODO: jam 20050105 Handle the case where we can't create a
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
        bzr = self.run_bzr
        txt = bzr('log')[0]

    def test_ls(self):
        bzr = self.run_bzr
        txt = bzr('ls')[0]

