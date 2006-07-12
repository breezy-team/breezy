# Copyright (C) 2006 by Canonical Ltd
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


"""Black-box tests for bzr whoami."""

import os

import bzrlib
from bzrlib.branch import Branch
from bzrlib.tests.blackbox import ExternalBase


class TestWhoami(ExternalBase):

    def test_whoami(self):
        # this should always identify something, if only "john@localhost"
        out = self.run_bzr("whoami")[0]
        self.assertTrue(len(out) > 0)
        self.assertEquals(1, out.count('@'))

        out = self.run_bzr("whoami", "--email")[0]
        self.assertTrue(len(out) > 0)
        self.assertEquals(1, out.count('@'))
        
    def test_whoami_branch(self):
        """branch specific user identity works."""
        wt = self.make_branch_and_tree('.')
        b = bzrlib.branch.Branch.open('.')
        b.get_config().set_user_option('email',
                                       'Branch Identity <branch@identi.ty>')
        bzr_email = os.environ.get('BZREMAIL')
        if bzr_email is not None:
            del os.environ['BZREMAIL']
        try:
            whoami = self.run_bzr("whoami")[0]
            self.assertEquals('Branch Identity <branch@identi.ty>\n', whoami)
            whoami_email = self.run_bzr("whoami", "--email")[0]
            self.assertEquals('branch@identi.ty\n', whoami_email)

            # Verify that the environment variable overrides the value 
            # in the file
            os.environ['BZREMAIL'] = 'Different ID <other@environ.ment>'
            whoami = self.run_bzr("whoami")[0]
            self.assertEquals('Different ID <other@environ.ment>\n', whoami)
            whoami_email = self.run_bzr("whoami", "--email")[0]
            self.assertEquals('other@environ.ment\n', whoami_email)
        finally:
            if bzr_email is not None:
                os.environ['BZREMAIL'] = bzr_email

    def test_whoami_utf8(self):
        """verify that an identity can be in utf-8."""
        wt = self.make_branch_and_tree('.')
        self.run_bzr('whoami', u'Branch Identity \u20ac <branch@identi.ty>',
                     encoding='utf-8')
        bzr_email = os.environ.get('BZREMAIL')
        if bzr_email is not None:
            del os.environ['BZREMAIL']
        try:
            whoami = self.run_bzr("whoami", encoding='utf-8')[0]
            self.assertEquals('Branch Identity \xe2\x82\xac ' +
                              '<branch@identi.ty>\n', whoami)
            whoami_email = self.run_bzr("whoami", "--email",
                                        encoding='utf-8')[0]
            self.assertEquals('branch@identi.ty\n', whoami_email)
        finally:
            if bzr_email is not None:
                os.environ['BZREMAIL'] = bzr_email

    def test_whoami_ascii(self):
        """
        verify that whoami doesn't totally break when in utf-8, using an ascii
        encoding.
        """
        wt = self.make_branch_and_tree('.')
        b = bzrlib.branch.Branch.open('.')
        b.get_config().set_user_option('email', u'Branch Identity \u20ac ' +
                                       '<branch@identi.ty>')
        bzr_email = os.environ.get('BZREMAIL')
        if bzr_email is not None:
            del os.environ['BZREMAIL']
        try:
            whoami = self.run_bzr("whoami", encoding='ascii')[0]
            self.assertEquals('Branch Identity ? <branch@identi.ty>\n', whoami)
            whoami_email = self.run_bzr("whoami", "--email",
                                        encoding='ascii')[0]
            self.assertEquals('branch@identi.ty\n', whoami_email)
        finally:
            if bzr_email is not None:
                os.environ['BZREMAIL'] = bzr_email

    def test_warning(self):
        """verify that a warning is displayed if no email is given."""
        self.make_branch_and_tree('.')
        display = self.run_bzr('whoami', 'Branch Identity')[1]
        self.assertEquals("'Branch Identity' doesn't seem to contain a " +
                          "reasonable email address\n", display)
