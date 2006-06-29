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


"""Black-box tests for bzr whoami.
"""

import os

import bzrlib
from bzrlib.branch import Branch
from bzrlib.tests.blackbox import ExternalBase


class TestWhoami(ExternalBase):

    def test_whoami(self):
        # this should always identify something, if only "john@localhost"
        out = self.run_bzr("whoami")[0]
        self.assertTrue(len(out) > 0)
        self.assertEquals(out.count('@'), 1)

        out = self.run_bzr("whoami", "--email")[0]
        self.assertTrue(len(out) > 0)
        self.assertEquals(out.count('@'), 1)
        
    def test_whoami_branch(self):
        """branch specific user identity works."""
        self.run_bzr('init')
        b = bzrlib.branch.Branch.open('.')
        b.get_config().set_user_option('email', 'Branch Identity <branch@identi.ty>')
        bzr_email = os.environ.get('BZREMAIL')
        if bzr_email is not None:
            del os.environ['BZREMAIL']
        try:
            whoami = self.run_bzr("whoami")[0]
            whoami_email = self.run_bzr("whoami", "--email")[0]
            self.assertTrue(whoami.startswith('Branch Identity <branch@identi.ty>'))
            self.assertTrue(whoami_email.startswith('branch@identi.ty'))

            # Verify that the environment variable overrides the value 
            # in the file
            os.environ['BZREMAIL'] = 'Different ID <other@environ.ment>'
            whoami = self.run_bzr("whoami")[0]
            whoami_email = self.run_bzr("whoami", "--email")[0]
            self.assertTrue(whoami.startswith('Different ID <other@environ.ment>'))
            self.assertTrue(whoami_email.startswith('other@environ.ment'))
        finally:
            if bzr_email is not None:
                os.environ['BZREMAIL'] = bzr_email

    def test_whoami_utf8(self):
        """verify that an identity can be in utf-8."""
        self.run_bzr('init')
        self.run_bzr('whoami', u'Branch Identity \u20ac <branch@identi.ty>', encoding='utf-8')
        bzr_email = os.environ.get('BZREMAIL')
        if bzr_email is not None:
            del os.environ['BZREMAIL']
        try:
            whoami = self.run_bzr("whoami", encoding='utf-8')[0]
            whoami_email = self.run_bzr("whoami", "--email", encoding='utf-8')[0]
            self.assertTrue(whoami.startswith('Branch Identity \xe2\x82\xac <branch@identi.ty>'))
            self.assertTrue(whoami_email.startswith('branch@identi.ty'))
        finally:
            if bzr_email is not None:
                os.environ['BZREMAIL'] = bzr_email

    def test_whoami_ascii(self):
        """verify that whoami doesn't totally break when in utf-8, using an ascii encoding."""
        self.runbzr('init')
        b = bzrlib.branch.Branch.open('.')
        b.get_config().set_user_option('email', u'Branch Identity \u20ac <branch@identi.ty>')
        bzr_email = os.environ.get('BZREMAIL')
        if bzr_email is not None:
            del os.environ['BZREMAIL']
        try:
            whoami = self.run_bzr("whoami", encoding='ascii')[0]
            whoami_email = self.run_bzr("whoami", "--email", encoding='ascii')[0]
            self.assertTrue(whoami.startswith('Branch Identity ? <branch@identi.ty>'))
            self.assertTrue(whoami_email.startswith('branch@identi.ty'))
        finally:
            if bzr_email is not None:
                os.environ['BZREMAIL'] = bzr_email
