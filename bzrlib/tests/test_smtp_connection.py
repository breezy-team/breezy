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
import errno
import smtplib
import socket
import sys

from bzrlib import (
    config,
    email_message,
    errors,
    smtp_connection,
    tests,
    ui,
    )


def connection_refuser():
    def connect(server):
        raise socket.error(errno.ECONNREFUSED, 'Connection Refused')
    smtp = smtplib.SMTP()
    smtp.connect = connect
    return smtp


def everybody_is_welcome():
    """Fake a smtp server that implements login by accepting anybody."""
    def connect(server):
        return (220, "You're so welcome")

    def starttls():
        pass

    def login(user, password):
        pass

    smtp = smtplib.SMTP()
    smtp.connect = connect
    smtp.starttls = starttls
    smtp.login = login
    return smtp


class TestSMTPConnection(tests.TestCaseInTempDir):

    def get_connection(self, text, smtp_factory=None):
        my_config = config.GlobalConfig()
        config_file = StringIO(text)
        my_config._get_parser(config_file)
        return smtp_connection.SMTPConnection(my_config,
                                              _smtp_factory=smtp_factory)

    def test_defaults(self):
        conn = self.get_connection('')
        self.assertEqual('localhost', conn._smtp_server)
        self.assertEqual(None, conn._smtp_username)
        self.assertEqual(None, conn._smtp_password)

    def test_smtp_server(self):
        conn = self.get_connection('[DEFAULT]\nsmtp_server=host:10\n')
        self.assertEqual('host:10', conn._smtp_server)

    def test_missing_server(self):
        conn = self.get_connection('', smtp_factory=connection_refuser)
        self.assertRaises(errors.DefaultSMTPConnectionRefused, conn._connect)
        conn = self.get_connection('[DEFAULT]\nsmtp_server=smtp.example.com\n',
                                   smtp_factory=connection_refuser)
        self.assertRaises(errors.SMTPConnectionRefused, conn._connect)

    def test_smtp_username(self):
        conn = self.get_connection('')
        self.assertIs(None, conn._smtp_username)

        conn = self.get_connection('[DEFAULT]\nsmtp_username=joebody\n')
        self.assertEqual(u'joebody', conn._smtp_username)

    def test_smtp_password_from_config(self):
        conn = self.get_connection('')
        self.assertIs(None, conn._smtp_password)

        conn = self.get_connection('[DEFAULT]\nsmtp_password=mypass\n')
        self.assertEqual(u'mypass', conn._smtp_password)

    def test_smtp_password_from_user(self):
        user = 'joe'
        password = 'hispass'
        conn = self.get_connection('[DEFAULT]\nsmtp_username=%s\n' % user,
                                   smtp_factory=everybody_is_welcome)
        self.assertIs(None, conn._smtp_password)

        ui.ui_factory = tests.TestUIFactory(stdin=password + '\n',
                                            stdout=tests.StringIOWrapper())
        conn._connect()
        self.assertEqual(password, conn._smtp_password)
        # stdin should be empty (the provided password have been consumed)
        self.assertEqual('', ui.ui_factory.stdin.readline())

    def test_smtp_password_from_auth_config(self):
        user = 'joe'
        password = 'hispass'
        conn = self.get_connection('[DEFAULT]\nsmtp_username=%s\n' % user,
                                   smtp_factory=everybody_is_welcome)
        self.assertEqual(user, conn._smtp_username)
        self.assertIs(None, conn._smtp_password)
        # Create a config file with the right password
        conf = config.AuthenticationConfig()
        conf._get_config().update({'smtptest':
                                       {'scheme': 'smtp', 'user':user,
                                        'password': password}})
        conf._save()

        conn._connect()
        self.assertEqual(password, conn._smtp_password)

    def test_get_message_addresses(self):
        msg = Message()

        from_, to = smtp_connection.SMTPConnection.get_message_addresses(msg)
        self.assertEqual('', from_)
        self.assertEqual([], to)

        msg['From'] = '"J. Random Developer" <jrandom@example.com>'
        msg['To'] = 'John Doe <john@doe.com>, Jane Doe <jane@doe.com>'
        msg['CC'] = u'Pepe P\xe9rez <pperez@ejemplo.com>'
        msg['Bcc'] = 'user@localhost'

        from_, to = smtp_connection.SMTPConnection.get_message_addresses(msg)
        self.assertEqual('jrandom@example.com', from_)
        self.assertEqual(sorted(['john@doe.com', 'jane@doe.com',
            'pperez@ejemplo.com', 'user@localhost']), sorted(to))

        # now with bzrlib's EmailMessage
        msg = email_message.EmailMessage(
            '"J. Random Developer" <jrandom@example.com>',
            ['John Doe <john@doe.com>', 'Jane Doe <jane@doe.com>',
             u'Pepe P\xe9rez <pperez@ejemplo.com>', 'user@localhost' ],
            'subject')

        from_, to = smtp_connection.SMTPConnection.get_message_addresses(msg)
        self.assertEqual('jrandom@example.com', from_)
        self.assertEqual(sorted(['john@doe.com', 'jane@doe.com',
            'pperez@ejemplo.com', 'user@localhost']), sorted(to))

    def test_destination_address_required(self):
        class FakeConfig:
            def get_user_option(self, option):
                return None

        msg = Message()
        msg['From'] = '"J. Random Developer" <jrandom@example.com>'
        self.assertRaises(
            errors.NoDestinationAddress,
            smtp_connection.SMTPConnection(FakeConfig()).send_email, msg)

        msg = email_message.EmailMessage('from@from.com', '', 'subject')
        self.assertRaises(
            errors.NoDestinationAddress,
            smtp_connection.SMTPConnection(FakeConfig()).send_email, msg)

        msg = email_message.EmailMessage('from@from.com', [], 'subject')
        self.assertRaises(
            errors.NoDestinationAddress,
            smtp_connection.SMTPConnection(FakeConfig()).send_email, msg)
