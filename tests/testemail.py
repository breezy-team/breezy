# Copyright (C) 2005 by Canonical Ltd
#   Authors: Robert Collins <robert.collins@canonical.com>
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

from cStringIO import StringIO
from unittest import TestLoader

from bzrlib.branch import Branch
import bzrlib.config as config
from bzrlib.selftest import TestCaseInTempDir
from bzrlib.plugins.email import post_commit, EmailSender


def test_suite():
    return TestLoader().loadTestsFromName(__name__)


sample_config=("[DEFAULT]\n"
               "post_commit_to=demo@example.com\n"
               "post_commit_sender=Sample <foo@example.com>\n")


class TestGetTo(TestCaseInTempDir):

    def test_body(self):
        sender = self.get_sender()
        # FIXME: this should not use a literal log, rather grab one from bzrlib.log
        self.assertEqual(
            '------------------------------------------------------------\n'
            'revno: 1\n'
            'revision-id: A\n'
            'committer: Sample <john@example.com>\n'
            'timestamp: Thu 1970-01-01 00:00:01 +0000\n'
            'message:\n'
            '  foo bar baz\n'
            '  fuzzy\n'
            '  wuzzy\n', sender.body())

    def test_to(self):
        sender = self.get_sender()
        self.assertEqual('demo@example.com', sender.to())

    def test_from(self):
        sender = self.get_sender()
        self.assertEqual('Sample <foo@example.com>', sender.from_address())

    def test_should_send(self):
        sender = self.get_sender()
        self.assertEqual(True, sender.should_send())

    def test_should_not_send(self):
        sender = self.get_sender("")
        self.assertEqual(False, sender.should_send())

    def test_subject(self):
        sender = self.get_sender()
        self.assertEqual("New revision 1 in %s: foo bar baz" % 
                            sender.branch.base,
                         sender.subject())

    def get_sender(self, text=sample_config):
        self.branch = Branch.initialize('.')
        self.branch.commit('foo bar baz\nfuzzy\rwuzzy', rev_id='A',
                           allow_pointless=True,
                           timestamp=1,
                           timezone=0,
                           committer="Sample <john@example.com>",
                           )
        my_config = config.BranchConfig(self.branch)
        config_file = StringIO(text)
        (my_config._get_location_config().
            _get_global_config()._get_parser(config_file))
        return EmailSender(self.branch, 'A', my_config)
