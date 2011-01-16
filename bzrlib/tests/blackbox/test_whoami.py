# Copyright (C) 2006, 2007, 2009, 2010, 2011 Canonical Ltd
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


"""Black-box tests for bzr whoami."""

import os

import bzrlib
from bzrlib import (
    osutils,
    config,
    )
from bzrlib.tests import TestCaseWithTransport


class TestWhoami(TestCaseWithTransport):

    def test_whoami(self):
        # this should always identify something, if only "john@localhost"
        out = self.run_bzr("whoami")[0]
        self.assertTrue(len(out) > 0)
        self.assertEquals(1, out.count('@'))

        out = self.run_bzr("whoami --email")[0]
        self.assertTrue(len(out) > 0)
        self.assertEquals(1, out.count('@'))

    def test_whoami_branch(self):
        """branch specific user identity works."""
        wt = self.make_branch_and_tree('.')
        b = bzrlib.branch.Branch.open('.')
        b.get_config().set_user_option('email',
                                       'Branch Identity <branch@identi.ty>')
        whoami = self.run_bzr("whoami")[0]
        self.assertEquals('Branch Identity <branch@identi.ty>\n', whoami)
        whoami_email = self.run_bzr("whoami --email")[0]
        self.assertEquals('branch@identi.ty\n', whoami_email)

        # Verify that the environment variable overrides the value
        # in the file
        self.overrideEnv('BZR_EMAIL', 'Different ID <other@environ.ment>')
        whoami = self.run_bzr("whoami")[0]
        self.assertEquals('Different ID <other@environ.ment>\n', whoami)
        whoami_email = self.run_bzr("whoami --email")[0]
        self.assertEquals('other@environ.ment\n', whoami_email)

    def test_whoami_utf8(self):
        """verify that an identity can be in utf-8."""
        wt = self.make_branch_and_tree('.')
        self.run_bzr(['whoami', u'Branch Identity \u20ac <branch@identi.ty>'],
                     encoding='utf-8')
        whoami = self.run_bzr("whoami", encoding='utf-8')[0]
        self.assertEquals('Branch Identity \xe2\x82\xac ' +
                          '<branch@identi.ty>\n', whoami)
        whoami_email = self.run_bzr("whoami --email", encoding='utf-8')[0]
        self.assertEquals('branch@identi.ty\n', whoami_email)

    def test_whoami_ascii(self):
        """
        verify that whoami doesn't totally break when in utf-8, using an ascii
        encoding.
        """
        wt = self.make_branch_and_tree('.')
        b = bzrlib.branch.Branch.open('.')
        b.get_config().set_user_option('email', u'Branch Identity \u20ac ' +
                                       '<branch@identi.ty>')
        whoami = self.run_bzr("whoami", encoding='ascii')[0]
        self.assertEquals('Branch Identity ? <branch@identi.ty>\n', whoami)
        whoami_email = self.run_bzr("whoami --email", encoding='ascii')[0]
        self.assertEquals('branch@identi.ty\n', whoami_email)

    def test_warning(self):
        """verify that a warning is displayed if no email is given."""
        self.make_branch_and_tree('.')
        display = self.run_bzr(['whoami', 'Branch Identity'])[1]
        self.assertEquals('"Branch Identity" does not seem to contain an '
                          'email address.  This is allowed, but not '
                          'recommended.\n', display)

    def test_whoami_not_set(self):
        """Ensure whoami error if username is not set.
        """
        self.overrideEnv('EMAIL', None)
        self.overrideEnv('BZR_EMAIL', None)
        out, err = self.run_bzr(['whoami'], 3)
        self.assertContainsRe(err, 'Unable to determine your name')

    def test_whoami_directory(self):
        """Test --directory option."""
        wt = self.make_branch_and_tree('subdir')
        c = wt.branch.get_config()
        c.set_user_option('email', 'Branch Identity <branch@identi.ty>')
        out, err = self.run_bzr("whoami --directory subdir")
        self.assertEquals('Branch Identity <branch@identi.ty>\n', out)
        self.run_bzr(['whoami', '--directory', 'subdir', '--branch',
                      'Changed Identity <changed@identi.ty>'])
        self.assertEquals('Changed Identity <changed@identi.ty>',
                          c.get_user_option('email'))

    def test_whoami_remote_directory(self):
        """Test --directory option with a remote directory."""
        wt = self.make_branch_and_tree('subdir')
        c = wt.branch.get_config()
        c.set_user_option('email', 'Branch Identity <branch@identi.ty>')
        url = self.get_readonly_url() + '/subdir'
        out, err = self.run_bzr(['whoami', '--directory', url])
        self.assertEquals('Branch Identity <branch@identi.ty>\n', out)
        url = self.get_url('subdir')
        self.run_bzr(['whoami', '--directory', url, '--branch',
                      'Changed Identity <changed@identi.ty>'])
        # The identity has been set in the branch config (but not the global
        # config)
        self.assertEquals('Changed Identity <changed@identi.ty>',
                          c.get_user_option('email'))
        global_conf = config.GlobalConfig()
        self.assertEquals(None, global_conf.get_user_option('email'))

    def test_whoami_nonbranch_directory(self):
        """Test --directory mentioning a non-branch directory."""
        wt = self.build_tree(['subdir/'])
        out, err = self.run_bzr("whoami --directory subdir", retcode=3)
        self.assertContainsRe(err, 'ERROR: Not a branch')
