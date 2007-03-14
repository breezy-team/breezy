# Copyright (C) 2007 Canonical Ltd
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

import os
import smtplib

from bzrlib import gpg, tests


EMAIL1 = """To: pqm@example.com
From: J. Random Hacker <jrandom@example.com>
Subject: bar

# Bazaar merge directive format 1
# revision_id: jrandom@example.com-.*
# target_branch: ../tree2
# testament_sha1: .*
# timestamp: .*
# source_branch: .
#"""


class TestMergeDirective(tests.TestCaseWithTransport):

    def prepare_merge_directive(self):
        tree1 = self.make_branch_and_tree('tree1')
        self.build_tree_contents([('tree1/file', 'a\nb\nc\nd\n')])
        tree1.branch.get_config().set_user_option('email',
            'J. Random Hacker <jrandom@example.com>')
        tree1.branch.get_config().set_user_option('smtp_server', 'bogushost')
        tree1.add('file')
        tree1.commit('foo')
        tree2=tree1.bzrdir.sprout('tree2').open_workingtree()
        self.build_tree_contents([('tree1/file', 'a\nb\nc\nd\ne\n')])
        tree1.commit('bar')
        os.chdir('tree1')

    def test_merge_directive(self):
        self.prepare_merge_directive()
        md_text = self.run_bzr('merge-directive', '../tree2')[0]
        self.assertContainsRe(md_text, "\\+e")
        md_text = self.run_bzr('merge-directive', '-r', '-2', '../tree2')[0]
        self.assertNotContainsRe(md_text, "\\+e")

    def test_submit_branch(self):
        self.prepare_merge_directive()
        self.run_bzr_error(('No submit branch',), 'merge-directive', retcode=3)
        self.run_bzr('merge-directive', '../tree2')

    def test_public_branch(self):
        self.prepare_merge_directive()
        self.run_bzr_error(('No public branch',), 'merge-directive', '--diff',
                           '../tree2', retcode=3)
        md_text = self.run_bzr('merge-directive', '../tree2')[0]
        self.assertNotContainsRe(md_text, 'source_branch:')
        self.run_bzr('merge-directive', '--diff', '../tree2', '.')
        self.run_bzr('merge-directive', '--diff')[0]
        self.assertNotContainsRe(md_text, 'source_branch:')

    def test_patch_types(self):
        self.prepare_merge_directive()
        md_text = self.run_bzr('merge-directive', '../tree2')[0]
        self.assertContainsRe(md_text, "Bazaar revision bundle")
        self.assertContainsRe(md_text, "\\+e")
        md_text = self.run_bzr('merge-directive', '../tree2', '--diff', '.')[0]
        self.assertNotContainsRe(md_text, "Bazaar revision bundle")
        self.assertContainsRe(md_text, "\\+e")
        md_text = self.run_bzr('merge-directive', '--plain')[0]
        self.assertNotContainsRe(md_text, "\\+e")

    def test_message(self):
        self.prepare_merge_directive()
        md_text = self.run_bzr('merge-directive', '../tree2')[0]
        self.assertNotContainsRe(md_text, 'message: Message for merge')
        md_text = self.run_bzr('merge-directive', '-m', 'Message for merge')[0]
        self.assertContainsRe(md_text, 'message: Message for merge')

    def test_signing(self):
        self.prepare_merge_directive()
        old_strategy = gpg.GPGStrategy
        gpg.GPGStrategy = gpg.LoopbackGPGStrategy
        try:
            md_text = self.run_bzr('merge-directive', '--sign', '../tree2')[0]
        finally:
            gpg.GPGStrategy = old_strategy
        self.assertContainsRe(md_text, '^-----BEGIN PSEUDO-SIGNED CONTENT')

    def test_mail(self):
        self.prepare_merge_directive()
        sendmail_calls = []
        def sendmail(self, from_, to, message):
            sendmail_calls.append((self, from_, to, message))
        connect_calls = []
        def connect(self, host='localhost', port=0):
            connect_calls.append((self, host, port))
        old_sendmail = smtplib.SMTP.sendmail
        smtplib.SMTP.sendmail = sendmail
        old_connect = smtplib.SMTP.connect
        smtplib.SMTP.connect = connect
        try:
            md_text = self.run_bzr('merge-directive', '--mail-to',
                                   'pqm@example.com', '--plain', '../tree2',
                                   '.')[0]
        finally:
            smtplib.SMTP.sendmail = old_sendmail
            smtplib.SMTP.connect = old_connect
        self.assertEqual('', md_text)
        self.assertEqual(1, len(connect_calls))
        call = connect_calls[0]
        self.assertEqual(('bogushost', 0), call[1:3])
        self.assertEqual(1, len(sendmail_calls))
        call = sendmail_calls[0]
        self.assertEqual(('J. Random Hacker <jrandom@example.com>',
                          'pqm@example.com'), call[1:3])
        self.assertContainsRe(call[3], EMAIL1)
