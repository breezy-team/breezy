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

from email.Header import decode_header

from bzrlib import __version__ as _bzrlib_version
from bzrlib.email_message import EmailMessage
from bzrlib.errors import BzrBadParameterNotUnicode
from bzrlib.smtp_connection import SMTPConnection
from bzrlib.tests import TestCase

EMPTY_MESSAGE = '''\
From: from@from.com
Subject: subject
To: to@to.com
User-Agent: Bazaar (%s)

''' % _bzrlib_version

_SIMPLE_MESSAGE = '''\
MIME-Version: 1.0
Content-Type: text/plain; charset="%%s"
Content-Transfer-Encoding: %%s
From: from@from.com
Subject: subject
To: to@to.com
User-Agent: Bazaar (%s)

%%s''' % _bzrlib_version

SIMPLE_MESSAGE_ASCII = _SIMPLE_MESSAGE % ('us-ascii', '7bit', 'body')
SIMPLE_MESSAGE_UTF8 = _SIMPLE_MESSAGE % ('utf-8', 'base64', 'YsOzZHk=\n')
SIMPLE_MESSAGE_8BIT = _SIMPLE_MESSAGE % ('8-bit', 'base64', 'YvRkeQ==\n')


BOUNDARY = '=====123456=='

_MULTIPART_HEAD = '''\
Content-Type: multipart/mixed; boundary="%(boundary)s"
MIME-Version: 1.0
From: from@from.com
Subject: subject
To: to@to.com
User-Agent: Bazaar (%(version)s)

--%(boundary)s
MIME-Version: 1.0
Content-Type: text/plain; charset="us-ascii"
Content-Transfer-Encoding: 7bit
Content-Disposition: inline

body
''' %  { 'version': _bzrlib_version, 'boundary': BOUNDARY }

SIMPLE_MULTIPART_MESSAGE = _MULTIPART_HEAD + '--%s--' % BOUNDARY

COMPLEX_MULTIPART_MESSAGE = _MULTIPART_HEAD + '''\
--%(boundary)s
MIME-Version: 1.0
Content-Type: text/%%s; charset="us-ascii"; name="lines.txt"
Content-Transfer-Encoding: 7bit
Content-Disposition: inline

a
b
c
d
e

--%(boundary)s--''' %  { 'boundary': BOUNDARY }


class TestEmailMessage(TestCase):

    def test_empty_message(self):
        msg = EmailMessage('from@from.com', 'to@to.com', 'subject')
        self.assertEqualDiff(EMPTY_MESSAGE , msg.as_string())

    def test_simple_message(self):
        pairs = {
            'body': SIMPLE_MESSAGE_ASCII,
            u'b\xf3dy': SIMPLE_MESSAGE_UTF8,
            'b\xc3\xb3dy': SIMPLE_MESSAGE_UTF8,
            'b\xf4dy': SIMPLE_MESSAGE_8BIT,
        }
        for body, expected in pairs.items():
            msg = EmailMessage('from@from.com', 'to@to.com', 'subject', body)
            self.assertEqualDiff(expected, msg.as_string())

    def test_multipart_message(self):
        msg = EmailMessage('from@from.com', 'to@to.com', 'subject')
        msg.add_inline_attachment('body')
        self.assertEqualDiff(SIMPLE_MULTIPART_MESSAGE, msg.as_string(BOUNDARY))

        msg = EmailMessage('from@from.com', 'to@to.com', 'subject', 'body')
        msg.add_inline_attachment(u'a\nb\nc\nd\ne\n', 'lines.txt', 'x-subtype')
        self.assertEqualDiff(COMPLEX_MULTIPART_MESSAGE % 'x-subtype',
                msg.as_string(BOUNDARY))

    def test_headers_accept_unicode_and_utf8(self):
        for user in [ u'Pepe P\xe9rez <pperez@ejemplo.com>',
                'Pepe P\xc3\xa9red <pperez@ejemplo.com>' ]:
            msg = EmailMessage(user, user, user) # no exception raised

            for header in ['From', 'To', 'Subject']:
                value = msg[header]
                str(value).decode('ascii') # no UnicodeDecodeError

    def test_headers_reject_8bit(self):
        for i in range(3): # from_address, to_address, subject
            x = [ '"J. Random Developer" <jrandom@example.com>' ] * 3
            x[i] = 'Pepe P\xe9rez <pperez@ejemplo.com>'
            self.assertRaises(BzrBadParameterNotUnicode, EmailMessage, *x)

    def test_multiple_destinations(self):
        to_addresses = [ 'to1@to.com', 'to2@to.com', 'to3@to.com' ]
        msg = EmailMessage('from@from.com', to_addresses, 'subject')
        self.assertContainsRe(msg.as_string(), 'To: ' +
                ', '.join(to_addresses)) # re.M can't be passed, so no ^$

    def test_retrieving_headers(self):
        msg = EmailMessage('from@from.com', 'to@to.com', 'subject')
        for header, value in [('From', 'from@from.com'), ('To', 'to@to.com'),
                ('Subject', 'subject')]:
            self.assertEqual(value, msg.get(header))
            self.assertEqual(value, msg[header])
        self.assertEqual(None, msg.get('Does-Not-Exist'))
        self.assertEqual(None, msg['Does-Not-Exist'])
        self.assertEqual('None', msg.get('Does-Not-Exist', 'None'))

    def test_setting_headers(self):
        msg = EmailMessage('from@from.com', 'to@to.com', 'subject')
        msg['To'] = 'to2@to.com'
        msg['Cc'] = 'cc@cc.com'
        self.assertEqual('to2@to.com', msg['To'])
        self.assertEqual('cc@cc.com', msg['Cc'])

    def test_send(self):
        class FakeConfig:
            def get_user_option(self, option):
                return None

        messages = []

        def send_as_append(_self, msg):
            messages.append(msg.as_string(BOUNDARY))

        old_send_email = SMTPConnection.send_email
        try:
            SMTPConnection.send_email = send_as_append

            EmailMessage.send(FakeConfig(), 'from@from.com', 'to@to.com',
                    'subject', 'body', u'a\nb\nc\nd\ne\n', 'lines.txt')
            self.assertEqualDiff(COMPLEX_MULTIPART_MESSAGE % 'plain',
                    messages[0])
            messages[:] = []

            EmailMessage.send(FakeConfig(), 'from@from.com', 'to@to.com',
                    'subject', 'body', u'a\nb\nc\nd\ne\n', 'lines.txt',
                    'x-patch')
            self.assertEqualDiff(COMPLEX_MULTIPART_MESSAGE % 'x-patch',
                    messages[0])
            messages[:] = []

            EmailMessage.send(FakeConfig(), 'from@from.com', 'to@to.com',
                    'subject', 'body')
            self.assertEqualDiff(SIMPLE_MESSAGE_ASCII , messages[0])
            messages[:] = []
        finally:
            SMTPConnection.send_email = old_send_email

    def test_address_to_encoded_header(self):
        def decode(s):
            """Convert a RFC2047-encoded string to a unicode string."""
            return ' '.join([chunk.decode(encoding or 'ascii')
                             for chunk, encoding in decode_header(s)])

        address = 'jrandom@example.com'
        encoded = EmailMessage.address_to_encoded_header(address)
        self.assertEqual(address, encoded)

        address = 'J Random Developer <jrandom@example.com>'
        encoded = EmailMessage.address_to_encoded_header(address)
        self.assertEqual(address, encoded)

        address = '"J. Random Developer" <jrandom@example.com>'
        encoded = EmailMessage.address_to_encoded_header(address)
        self.assertEqual(address, encoded)

        address = u'Pepe P\xe9rez <pperez@ejemplo.com>' # unicode ok
        encoded = EmailMessage.address_to_encoded_header(address)
        self.assert_('pperez@ejemplo.com' in encoded) # addr must be unencoded
        self.assertEquals(address, decode(encoded))

        address = 'Pepe P\xc3\xa9red <pperez@ejemplo.com>' # UTF-8 ok
        encoded = EmailMessage.address_to_encoded_header(address)
        self.assert_('pperez@ejemplo.com' in encoded)
        self.assertEquals(address, decode(encoded).encode('utf-8'))

        address = 'Pepe P\xe9rez <pperez@ejemplo.com>' # ISO-8859-1 not ok
        self.assertRaises(BzrBadParameterNotUnicode,
                EmailMessage.address_to_encoded_header, address)

    def test_string_with_encoding(self):
        pairs = {
                u'Pepe':        ('Pepe', 'ascii'),
                u'P\xe9rez':    ('P\xc3\xa9rez', 'utf-8'),
                'Perez':         ('Perez', 'ascii'), # u'Pepe' == 'Pepe'
                'P\xc3\xa9rez': ('P\xc3\xa9rez', 'utf-8'),
                'P\xe8rez':     ('P\xe8rez', '8-bit'),
        }
        for string_, pair in pairs.items():
            self.assertEqual(pair, EmailMessage.string_with_encoding(string_))
