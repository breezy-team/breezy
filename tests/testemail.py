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

from bzrlib.bzrdir import BzrDir
import bzrlib.config as config
from bzrlib.tests import TestCaseInTempDir, TestCaseWithMemoryTransport
from bzrlib.plugins.email import post_commit
from bzrlib.plugins.email.emailer import EmailSender, SMTPConnection


def test_suite():
    return TestLoader().loadTestsFromName(__name__)


sample_config=("[DEFAULT]\n"
               "post_commit_to=demo@example.com\n"
               "post_commit_sender=Sample <foo@example.com>\n")

unconfigured_config=("[DEFAULT]\n"
                     "email=Robert <foo@example.com>\n")

sender_configured_config=("[DEFAULT]\n"
                          "post_commit_sender=Sample <foo@example.com>\n")

to_configured_config=("[DEFAULT]\n"
                      "post_commit_to=Sample <foo@example.com>\n")

with_url_config=("[DEFAULT]\n"
                 "post_commit_url=http://some.fake/url/\n"
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
            'branch nick: work\n'
            'timestamp: Thu 1970-01-01 00:00:01 +0000\n'
            'message:\n'
            '  foo bar baz\n'
            '  fuzzy\n'
            '  wuzzy\n', sender.body())

    def test_command_line(self):
        sender = self.get_sender()
        self.assertEqual(['mail', '-s', sender.subject(), '-a', 
                          'From: ' + sender.from_address(), sender.to()],
                         sender._command_line())

    def test_to(self):
        sender = self.get_sender()
        self.assertEqual('demo@example.com', sender.to())

    def test_from(self):
        sender = self.get_sender()
        self.assertEqual('Sample <foo@example.com>', sender.from_address())

    def test_from_default(self):
        sender = self.get_sender(unconfigured_config)
        self.assertEqual('Robert <foo@example.com>', sender.from_address())

    def test_should_send(self):
        sender = self.get_sender()
        self.assertEqual(True, sender.should_send())

    def test_should_not_send(self):
        sender = self.get_sender(unconfigured_config)
        self.assertEqual(False, sender.should_send())

    def test_should_not_send_sender_configured(self):
        sender = self.get_sender(sender_configured_config)
        self.assertEqual(False, sender.should_send())

    def test_should_not_send_to_configured(self):
        sender = self.get_sender(to_configured_config)
        self.assertEqual(True, sender.should_send())

    def test_url_set(self):
        sender = self.get_sender(with_url_config)
        self.assertEqual(sender.url(), 'http://some.fake/url/')

    def test_public_url_set(self):
        config=("[DEFAULT]\n"
                "public_branch=http://the.publication/location/\n")
        sender = self.get_sender(config)
        self.assertEqual(sender.url(), 'http://the.publication/location/')

    def test_url_precedence(self):
        config=("[DEFAULT]\n"
                "post_commit_url=http://some.fake/url/\n"
                "public_branch=http://the.publication/location/\n")
        sender = self.get_sender(config)
        self.assertEqual(sender.url(), 'http://some.fake/url/')

    def test_url_unset(self):
        sender = self.get_sender()
        self.assertEqual(sender.url(), sender.branch.base)

    def test_subject(self):
        sender = self.get_sender()
        self.assertEqual("Rev 1: foo bar baz in %s" % 
                            sender.branch.base,
                         sender.subject())

    def get_sender(self, text=sample_config):
        self.branch = BzrDir.create_branch_convenience('.')
        tree = self.branch.bzrdir.open_workingtree()
        tree.commit('foo bar baz\nfuzzy\rwuzzy', rev_id='A',
            allow_pointless=True,
            timestamp=1,
            timezone=0,
            committer="Sample <john@example.com>",
            )
        my_config = self.branch.get_config()
        config_file = StringIO(text)
        (my_config._get_global_config()._get_parser(config_file))
        return EmailSender(self.branch, 'A', my_config)


class InstrumentedSMTPConnection(SMTPConnection):
    """Instrument SMTPConnection.

    We don't want to actually connect or send messages, so this just
    fakes it.
    """
    
    class FakeSMTP(object):
        """Fakes an SMTP connection."""
    
        def __init__(self, actions):
            self.actions = actions
        
        def sendmail(self, from_addr, to_addrs, msg):
            self.actions.append(('sendmail', from_addr, to_addrs, msg))
        
        def login(self, username, password):
            self.actions.append(('login', username, password))
        
    def __init__(self, config):
        super(InstrumentedSMTPConnection, self).__init__(config)
        self.actions = []

    def _create_connection(self):
        self.actions.append(('create_connection',))
        self._connection = InstrumentedSMTPConnection.FakeSMTP(self.actions)

    def _basic_message(self, *args, **kwargs):
        """Override to force the boundary for easier testing."""
        msg = super(InstrumentedSMTPConnection,
        self)._basic_message(*args, **kwargs)
        msg.set_boundary('=====123456==')
        return msg

           
class TestSMTPConnection(TestCaseWithMemoryTransport):

    def get_connection(self, text):
        self.tree = self.make_branch_and_memory_tree('tree')
        self.tree.lock_write()
        self.addCleanup(self.tree.unlock)

        self.tree.add('') # You have to add the root directory
        self.tree.commit(u'Commit message\nfoo b\xe5r baz\n',
                         rev_id='A',
                         allow_pointless=True,
                         timestamp=1,
                         timezone=0,
                         committer=u'Jerry F\xb5z <jerry@fooz.com>',
                         )
        my_config = self.tree.branch.get_config()
        config_file = StringIO(text)
        (my_config._get_global_config()._get_parser(config_file))
        return InstrumentedSMTPConnection(my_config)

    def test_defaults(self):
        conn = self.get_connection(unconfigured_config)
        self.assertEqual('localhost', conn._smtp_server)
        self.assertEqual(None, conn._smtp_username)
        self.assertEqual(None, conn._smtp_password)

    def test_simple_send(self):
        conn = self.get_connection(unconfigured_config)
        from_addr = u'Jerry F\xb5z <jerry@fooz.com>'
        to_addr = u'Biz N\xe5 <biz@na.com>'
        subject = u'Hello Biz N\xe5'
        message=(u'Hello Biz N\xe5\n'
                 u'I haven\'t heard\n'
                 u'from you in a while\n')
        conn.send_text_email(from_addr, [to_addr], subject, message)
        self.assertEqual(('create_connection',), conn.actions[0])
        self.assertEqual(('sendmail', 'jerry@fooz.com', ['biz@na.com']),
                         conn.actions[1][:3])
        self.assertEqualDiff((
                           'MIME-Version: 1.0\n'
                           'Content-Type: multipart/mixed; charset="utf-8"; boundary="=====123456=="\n'
                           'Content-Transfer-Encoding: base64\n'
                           'From: =?utf-8?b?SmVycnkgRsK1eiA8amVycnlAZm9vei5jb20+?=\n'
                           'To: =?utf-8?b?Qml6IE7DpSA8Yml6QG5hLmNvbT4=?=\n'
                           'Subject: =?utf-8?q?Hello_Biz_N=C3=A5?=\n'
                           '\n'
                           '--=====123456==\n'
                           'Content-Type: text/plain; charset="utf-8"\n'
                           'MIME-Version: 1.0\n'
                           'Content-Transfer-Encoding: base64\n'
                           '\n'
                           'SGVsbG8gQml6IE7DpQpJIGhhdmVuJ3QgaGVhcmQKZnJvbSB5b3UgaW4gYSB3aGlsZQo=\n'
                           '\n'
                           '--=====123456==--'
                           ), conn.actions[1][3])
