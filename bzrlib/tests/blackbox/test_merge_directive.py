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

from bzrlib import gpg, tests


EMAIL1 = """To: pqm@example.com
From: J. Random Hacker <jrandom@example.com>
Subject: bar

# Bazaar merge directive format experimental-1
# revision_id: jrandom@example.com-.*
# target_branch: ../tree2
# testament_sha1: .*
# timestamp: .*
# source_branch: .
#"""


class TestMergeDirective(tests.TestCaseWithTransport):

    def test_merge_directive(self):
        tree1 = self.make_branch_and_tree('tree1')
        self.build_tree_contents([('tree1/file', 'a\nb\nc\nd\n')])
        tree1.branch.get_config().set_user_option('email',
            'J. Random Hacker <jrandom@example.com>')
        tree1.add('file')
        tree1.commit('foo')
        tree2=tree1.bzrdir.sprout('tree2').open_workingtree()
        self.build_tree_contents([('tree1/file', 'a\nb\nc\nd\ne\n')])
        tree1.commit('bar')
        os.chdir('tree1')
        self.run_bzr_error(('No submit branch',), 'merge-directive', retcode=3)
        self.run_bzr('merge-directive', '../tree2')
        md_text = self.run_bzr('merge-directive')[0]
        self.assertContainsRe(md_text, "Bazaar revision bundle")
        self.assertNotContainsRe(md_text, 'source_branch:')
        self.assertContainsRe(md_text, "\\+e")
        self.run_bzr_error(('No public branch',), 'merge-directive', '--diff',
                           retcode=3)
        self.run_bzr('merge-directive', '--diff', '../tree2', '.')
        md_text = self.run_bzr('merge-directive', '--diff')[0]
        self.assertNotContainsRe(md_text, "Bazaar revision bundle")
        self.assertContainsRe(md_text, "\\+e")
        md_text = self.run_bzr('merge-directive', '--plain')[0]
        self.assertNotContainsRe(md_text, "\\+e")
        md_text = self.run_bzr('merge-directive')[0]
        self.assertContainsRe(md_text, 'source_branch:')
        self.assertNotContainsRe(md_text, 'message: Message for merge')
        md_text = self.run_bzr('merge-directive', '-m', 'Message for merge')[0]
        self.assertContainsRe(md_text, 'message: Message for merge')
        old_strategy = gpg.GPGStrategy
        gpg.GPGStrategy = gpg.LoopbackGPGStrategy
        try:
            md_text = self.run_bzr('merge-directive', '--sign')[0]
        finally:
            gpg.GPGStrategy = old_strategy
        self.assertContainsRe(md_text, '^-----BEGIN PSEUDO-SIGNED CONTENT')
        md_text = self.run_bzr('merge-directive', '-r', '-2')[0]
        self.assertNotContainsRe(md_text, "\\+e")
        sendmail_calls = []
        import smtplib
        def sendmail(self, from_, to, message):
            sendmail_calls.append((self, from_, to, message))
        old_sendmail = smtplib.SMTP.sendmail
        smtplib.SMTP.sendmail = sendmail
        try:
            md_text = self.run_bzr('merge-directive', '--mail-to',
                                   'pqm@example.com', '--plain')[0]
        finally:
            smtplib.SMTP.sendmail = old_sendmail
        self.assertEqual('', md_text)
        self.assertEqual(1, len(sendmail_calls))
        call = sendmail_calls[0]
        self.assertEqual(('J. Random Hacker <jrandom@example.com>',
                          'pqm@example.com'), call[1:3])
        self.assertContainsRe(call[3], EMAIL1)
