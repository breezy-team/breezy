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

from bzrlib import (
    config,
    __version__ as _bzrlib_version,
    )
from bzrlib.tests import TestCase
from bzrlib.plugins.email.smtp_connection import SMTPConnection


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
        msg, from_email, to_emails = super(InstrumentedSMTPConnection,
        self)._basic_message(*args, **kwargs)
        msg.set_boundary('=====123456==')
        return msg, from_email, to_emails

           
class TestSMTPConnection(TestCase):

    def get_connection(self, text):
        my_config = config.GlobalConfig()
        config_file = StringIO(text)
        (my_config._get_parser(config_file))
        return InstrumentedSMTPConnection(my_config)

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

    def assertSplitEquals(self, username, email, address):
        actual = SMTPConnection._split_address(address)
        self.assertEqual((username, email), actual)

    def test__split_address(self):
        self.assertSplitEquals(u'Joe Foo', 'joe@foo.com',
                               u'Joe Foo <joe@foo.com>')
        self.assertSplitEquals(u'Joe F\xb5', 'joe@foo.com',
                               u'Joe F\xb5 <joe@foo.com>')
        self.assertSplitEquals('', 'joe', 'joe')

    def test_simple_send(self):
        """Test that we build up a reasonable looking email.
        
        This also tests that we extract the right email addresses, etc, and it
        gets passed to sendmail() with the right parameters.
        """
        conn = self.get_connection('')
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
   'Content-Type: multipart/mixed; boundary="=====123456=="\n'
   'MIME-Version: 1.0\n'
   'From: =?utf8?q?Jerry_F=C2=B5z?= <jerry@fooz.com>\n'
   'User-Agent: bzr/%s\n'
   'To: =?utf8?q?Biz_N=C3=A5?= <biz@na.com>\n'
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
   ) % _bzrlib_version, conn.actions[1][3])

    def test_send_text_and_attachment_email(self):
        conn = self.get_connection('')
        from_addr = u'Jerry F\xb5z <jerry@fooz.com>'
        to_addr = u'Biz N\xe5 <biz@na.com>'
        subject = u'Hello Biz N\xe5'
        message=(u'Hello Biz N\xe5\n'
                 u'See my attached patch\n')
        diff_txt = ('=== diff contents\n'
                    '--- old\n'
                    '+++ new\n'
                    ' unchanged\n'
                    '-old binary\xb5\n'
                    '-new binary\xe5\n'
                    ' unchanged\n')
        conn.send_text_and_attachment_email(from_addr, [to_addr], subject,
                                            message, diff_txt, 'test.diff')
        self.assertEqual(('create_connection',), conn.actions[0])
        self.assertEqual(('sendmail', 'jerry@fooz.com', ['biz@na.com']),
                         conn.actions[1][:3])
        self.assertEqualDiff((
   'Content-Type: multipart/mixed; boundary="=====123456=="\n'
   'MIME-Version: 1.0\n'
   'From: =?utf8?q?Jerry_F=C2=B5z?= <jerry@fooz.com>\n'
   'User-Agent: bzr/%s\n'
   'To: =?utf8?q?Biz_N=C3=A5?= <biz@na.com>\n'
   'Subject: =?utf-8?q?Hello_Biz_N=C3=A5?=\n'
   '\n'
   '--=====123456==\n'
   'Content-Type: text/plain; charset="utf-8"\n'
   'MIME-Version: 1.0\n'
   'Content-Transfer-Encoding: base64\n'
   '\n'
   'SGVsbG8gQml6IE7DpQpTZWUgbXkgYXR0YWNoZWQgcGF0Y2gK\n'
   '\n'
   '--=====123456==\n'
   'Content-Type: text/plain; charset="8-bit"; name="test.diff"\n'
   'MIME-Version: 1.0\n'
   'Content-Transfer-Encoding: base64\n'
   'Content-Disposition: inline; filename="test.diff"\n'
   '\n'
   'PT09IGRpZmYgY29udGVudHMKLS0tIG9sZAorKysgbmV3CiB1bmNoYW5nZWQKLW9sZCBiaW5hcnm1\n'
   'Ci1uZXcgYmluYXJ55QogdW5jaGFuZ2VkCg==\n'
   '\n'
   '--=====123456==--'
   ) % _bzrlib_version, conn.actions[1][3])

    def test_create_and_send(self):
        """Test that you can create a custom email, and send it."""
        conn = self.get_connection('')
        email_msg, from_email, to_emails = conn.create_email(
            'Joe Foo <joe@foo.com>',
            ['Jane Foo <jane@foo.com>', 'Barry Foo <barry@foo.com>'],
            'Hi Jane and Barry',
            'Check out the attachment\n')
        self.assertEqual('joe@foo.com', from_email)
        self.assertEqual(['jane@foo.com', 'barry@foo.com'], to_emails)

        try:
            # python 2.5
            from email.mime.nonmultipart import MIMENonMultipart
            from email.encoders import encode_base64
        except ImportError:
            # python 2.4
            from email.MIMENonMultipart import MIMENonMultipart
            from email.Encoders import encode_base64

        attachment_txt = '\x00foo\xff\xff\xff\xff'
        attachment = MIMENonMultipart('application', 'octet-stream')
        attachment.set_payload(attachment_txt)
        encode_base64(attachment)

        email_msg.attach(attachment)

        # This will add someone to send to, but not include it in the To list.
        to_emails.append('b@cc.com')
        conn.send_email(email_msg, from_email, to_emails)

        self.assertEqual(('create_connection',), conn.actions[0])
        self.assertEqual(('sendmail', 'joe@foo.com',
                          ['jane@foo.com', 'barry@foo.com', 'b@cc.com']),
                         conn.actions[1][:3])
        self.assertEqualDiff((
   'Content-Type: multipart/mixed; boundary="=====123456=="\n'
   'MIME-Version: 1.0\n'
   'From: =?utf8?q?Joe_Foo?= <joe@foo.com>\n'
   'User-Agent: bzr/%s\n'
   'To: =?utf8?q?Jane_Foo?= <jane@foo.com>, =?utf8?q?Barry_Foo?= <barry@foo.com>\n'
   'Subject: Hi Jane and Barry\n'
   '\n'
   '--=====123456==\n'
   'Content-Type: text/plain; charset="utf-8"\n'
   'MIME-Version: 1.0\n'
   'Content-Transfer-Encoding: base64\n'
   '\n'
   'Q2hlY2sgb3V0IHRoZSBhdHRhY2htZW50Cg==\n'
   '\n'
   '--=====123456==\n'
   'Content-Type: application/octet-stream\n'
   'MIME-Version: 1.0\n'
   'Content-Transfer-Encoding: base64\n'
   '\n'
   'AGZvb/////8=\n'
   '--=====123456==--'
   ) % _bzrlib_version, conn.actions[1][3])

    def test_email_parse(self):
        """Check that python's email can parse our emails."""
        conn = self.get_connection('')
        from_addr = u'Jerry F\xb5z <jerry@fooz.com>'
        to_addr = u'Biz N\xe5 <biz@na.com>'
        subject = u'Hello Biz N\xe5'
        message=(u'Hello Biz N\xe5\n'
                 u'See my attached patch\n')
        diff_txt = ('=== diff contents\n'
                    '--- old\n'
                    '+++ new\n'
                    ' unchanged\n'
                    '-old binary\xb5\n'
                    '-new binary\xe5\n'
                    ' unchanged\n')
        conn.send_text_and_attachment_email(from_addr, [to_addr], subject,
                                            message, diff_txt, 'test.diff')
        self.assertEqual(('create_connection',), conn.actions[0])
        self.assertEqual(('sendmail', 'jerry@fooz.com', ['biz@na.com']),
                         conn.actions[1][:3])
        email_message_text = conn.actions[1][3]

        try:
            # python 2.5
            from email.parser import Parser
            from email.header import decode_header
        except ImportError:
            # python 2.4
            from email.Parser import Parser
            from email.Header import decode_header

        def decode(s):
            """Convert a header string to a unicode string.

            This handles '=?utf-8?q?foo=C2=B5?=' => u'Foo\\xb5'
            """
            return ' '.join([chunk.decode(encoding or 'ascii')
                             for chunk, encoding in decode_header(s)])

        p = Parser()
        email_message = p.parsestr(email_message_text)

        self.assertEqual(from_addr, decode(email_message['From']))
        self.assertEqual(to_addr, decode(email_message['To']))
        self.assertEqual(subject, decode(email_message['Subject']))
        text_payload = email_message.get_payload(0)
        diff_payload = email_message.get_payload(1)
        # I haven't found a way to have python's email read the charset=""
        # portion of the Content-Type header. So I'm doing it manually
        # The 'decode=True' here means to decode from base64 => 8-bit text.
        # text_payload.get_charset() returns None
        text = text_payload.get_payload(decode=True).decode('utf-8')
        self.assertEqual(message, text)
        self.assertEqual(diff_txt, diff_payload.get_payload(decode=True))
