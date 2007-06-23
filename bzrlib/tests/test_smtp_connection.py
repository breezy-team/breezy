# Copyright (C) 2005, 2007 Canonical Ltd
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
from email.Message import Message

from bzrlib import config
from bzrlib.errors import NoDestinationAddress
from bzrlib.tests import TestCase
from bzrlib.smtp_connection import SMTPConnection


class TestSMTPConnection(TestCase):

    def get_connection(self, text):
        my_config = config.GlobalConfig()
        config_file = StringIO(text)
        my_config._get_parser(config_file)
        return SMTPConnection(my_config)

    def test_defaults(self):
        conn = self.get_connection('')
        self.assertEqual('localhost', conn._smtp_server)
        self.assertEqual(None, conn._smtp_username)
        self.assertEqual(None, conn._smtp_password)

    def test_smtp_server(self):
        conn = self.get_connection('[DEFAULT]\nsmtp_server=host:10\n')
        self.assertEqual('host:10', conn._smtp_server)

    def test_smtp_username(self):
        conn = self.get_connection('')
        self.assertIs(None, conn._smtp_username)

        conn = self.get_connection('[DEFAULT]\nsmtp_username=joebody\n')
        self.assertEqual(u'joebody', conn._smtp_username)

    def test_smtp_password(self):
        conn = self.get_connection('')
        self.assertIs(None, conn._smtp_password)

        conn = self.get_connection('[DEFAULT]\nsmtp_password=mypass\n')
        self.assertEqual(u'mypass', conn._smtp_password)

    def test_get_message_addresses(self):
        msg = Message()

        from_, to = SMTPConnection.get_message_addresses(msg)
        self.assertEqual('', from_)
        self.assertEqual([], to)

        msg['From'] = '"J. Random Developer" <jrandom@example.com>'
        msg['To'] = 'John Doe <john@doe.com>, Jane Doe <jane@doe.com>'
        msg['CC'] = u'Pepe P\xe9rez <pperez@ejemplo.com>'
        msg['Bcc'] = 'user@localhost'

        from_, to = SMTPConnection.get_message_addresses(msg)
        self.assertEqual('jrandom@example.com', from_)
        self.assertEqual(sorted(['john@doe.com', 'jane@doe.com',
            'pperez@ejemplo.com', 'user@localhost']), sorted(to))

    def test_destination_address_required(self):
        class FakeConfig:
            def get_user_option(self, option):
                return None

        msg = Message()
        msg['From'] = '"J. Random Developer" <jrandom@example.com>'
        self.assertRaises(NoDestinationAddress,
                SMTPConnection(FakeConfig()).send_email, msg)
