# Copyright (C) 2007, 2009, 2011, 2014, 2016 Canonical Ltd
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

from email.header import decode_header

from .. import __version__ as _breezy_version
from .. import tests
from ..email_message import EmailMessage
from ..errors import BzrBadParameterNotUnicode
from ..smtp_connection import SMTPConnection

EMPTY_MESSAGE = (
    """\
From: from@from.com
Subject: subject
To: to@to.com
User-Agent: Bazaar ({})

""".format(_breezy_version)
)

_SIMPLE_MESSAGE = (
    """\
MIME-Version: 1.0
Content-Type: text/plain; charset="%s"
Content-Transfer-Encoding: %s
From: from@from.com
Subject: subject
To: to@to.com
User-Agent: Bazaar ({})

%s""".format(_breezy_version)
)

SIMPLE_MESSAGE_ASCII = _SIMPLE_MESSAGE % ("us-ascii", "7bit", "body")
SIMPLE_MESSAGE_UTF8 = _SIMPLE_MESSAGE % ("utf-8", "base64", "YsOzZHk=\n")
SIMPLE_MESSAGE_8BIT = _SIMPLE_MESSAGE % ("8-bit", "base64", "YvRkeQ==\n")


BOUNDARY = "=====123456=="

_MULTIPART_HEAD = """\
Content-Type: multipart/mixed; boundary="{boundary}"
MIME-Version: 1.0
From: from@from.com
Subject: subject
To: to@to.com
User-Agent: Bazaar ({version})

--{boundary}
MIME-Version: 1.0
Content-Type: text/plain; charset="us-ascii"
Content-Transfer-Encoding: 7bit
Content-Disposition: inline

body
""".format(version=_breezy_version, boundary=BOUNDARY)


def simple_multipart_message():
    msg = _MULTIPART_HEAD + "--{}--\n".format(BOUNDARY)
    return msg


def complex_multipart_message(typ):
    msg = (
        _MULTIPART_HEAD
        + """\
--{boundary}
MIME-Version: 1.0
Content-Type: text/%s; charset="us-ascii"; name="lines.txt"
Content-Transfer-Encoding: 7bit
Content-Disposition: inline

a
b
c
d
e

--{boundary}--
""".format(boundary=BOUNDARY)
    )
    return msg % (typ,)


class TestEmailMessage(tests.TestCase):
    def test_empty_message(self):
        msg = EmailMessage("from@from.com", "to@to.com", "subject")
        self.assertEqualDiff(EMPTY_MESSAGE, msg.as_string())

    def test_simple_message(self):
        pairs = {
            b"body": SIMPLE_MESSAGE_ASCII,
            "b\xf3dy": SIMPLE_MESSAGE_UTF8,
            b"b\xc3\xb3dy": SIMPLE_MESSAGE_UTF8,
            b"b\xf4dy": SIMPLE_MESSAGE_8BIT,
        }
        for body, expected in pairs.items():
            msg = EmailMessage("from@from.com", "to@to.com", "subject", body)
            self.assertEqualDiff(expected, msg.as_string())

    def test_multipart_message_simple(self):
        msg = EmailMessage("from@from.com", "to@to.com", "subject")
        msg.add_inline_attachment("body")
        self.assertEqualDiff(simple_multipart_message(), msg.as_string(BOUNDARY))

    def test_multipart_message_complex(self):
        msg = EmailMessage("from@from.com", "to@to.com", "subject", "body")
        msg.add_inline_attachment("a\nb\nc\nd\ne\n", "lines.txt", "x-subtype")
        self.assertEqualDiff(
            complex_multipart_message("x-subtype"), msg.as_string(BOUNDARY)
        )

    def test_headers_accept_unicode_and_utf8(self):
        for user in [
            "Pepe P\xe9rez <pperez@ejemplo.com>",
            "Pepe P\xc3\xa9red <pperez@ejemplo.com>",
        ]:
            msg = EmailMessage(user, user, user)  # no exception raised

            for header in ["From", "To", "Subject"]:
                value = msg[header]
                value.encode("ascii")  # no UnicodeDecodeError

    def test_headers_reject_8bit(self):
        for i in range(3):  # from_address, to_address, subject
            x = [b'"J. Random Developer" <jrandom@example.com>'] * 3
            x[i] = b"Pepe P\xe9rez <pperez@ejemplo.com>"
            self.assertRaises(BzrBadParameterNotUnicode, EmailMessage, *x)

    def test_multiple_destinations(self):
        to_addresses = ["to1@to.com", "to2@to.com", "to3@to.com"]
        msg = EmailMessage("from@from.com", to_addresses, "subject")
        self.assertContainsRe(
            msg.as_string(), "To: " + ", ".join(to_addresses)
        )  # re.M can't be passed, so no ^$

    def test_retrieving_headers(self):
        msg = EmailMessage("from@from.com", "to@to.com", "subject")
        for header, value in [
            ("From", "from@from.com"),
            ("To", "to@to.com"),
            ("Subject", "subject"),
        ]:
            self.assertEqual(value, msg.get(header))
            self.assertEqual(value, msg[header])
        self.assertEqual(None, msg.get("Does-Not-Exist"))
        self.assertEqual(None, msg["Does-Not-Exist"])
        self.assertEqual("None", msg.get("Does-Not-Exist", "None"))

    def test_setting_headers(self):
        msg = EmailMessage("from@from.com", "to@to.com", "subject")
        msg["To"] = "to2@to.com"
        msg["Cc"] = "cc@cc.com"
        self.assertEqual("to2@to.com", msg["To"])
        self.assertEqual("cc@cc.com", msg["Cc"])

    def test_address_to_encoded_header(self):
        def decode(s):
            """Convert a RFC2047-encoded string to a unicode string."""
            return "".join(
                [
                    chunk.decode(encoding or "ascii")
                    for chunk, encoding in decode_header(s)
                ]
            )

        address = "jrandom@example.com"
        encoded = EmailMessage.address_to_encoded_header(address)
        self.assertEqual(address, encoded)

        address = "J Random Developer <jrandom@example.com>"
        encoded = EmailMessage.address_to_encoded_header(address)
        self.assertEqual(address, encoded)

        address = '"J. Random Developer" <jrandom@example.com>'
        encoded = EmailMessage.address_to_encoded_header(address)
        self.assertEqual(address, encoded)

        address = "Pepe P\xe9rez <pperez@ejemplo.com>"  # unicode ok
        encoded = EmailMessage.address_to_encoded_header(address)
        # addr must be unencoded
        self.assertTrue("pperez@ejemplo.com" in encoded)
        self.assertEqual(address, decode(encoded))

        address = b"Pepe P\xe9rez <pperez@ejemplo.com>"  # ISO-8859-1 not ok
        self.assertRaises(
            BzrBadParameterNotUnicode, EmailMessage.address_to_encoded_header, address
        )

    def test_string_with_encoding(self):
        pairs = {
            "Pepe": (b"Pepe", "ascii"),
            "P\xe9rez": (b"P\xc3\xa9rez", "utf-8"),
            b"P\xc3\xa9rez": (b"P\xc3\xa9rez", "utf-8"),
            b"P\xe8rez": (b"P\xe8rez", "8-bit"),
        }
        for string_, pair in pairs.items():
            self.assertEqual(pair, EmailMessage.string_with_encoding(string_))


class TestSend(tests.TestCase):
    def setUp(self):
        super().setUp()
        self.messages = []

        def send_as_append(_self, msg):
            self.messages.append(msg.as_string(BOUNDARY))

        self.overrideAttr(SMTPConnection, "send_email", send_as_append)

    def send_email(
        self, attachment=None, attachment_filename=None, attachment_mime_subtype="plain"
    ):
        class FakeConfig:
            def get(self, option):
                return None

        EmailMessage.send(
            FakeConfig(),
            "from@from.com",
            "to@to.com",
            "subject",
            "body",
            attachment=attachment,
            attachment_filename=attachment_filename,
            attachment_mime_subtype=attachment_mime_subtype,
        )

    def assertMessage(self, expected):
        self.assertLength(1, self.messages)
        self.assertEqualDiff(expected, self.messages[0])

    def test_send_plain(self):
        self.send_email("a\nb\nc\nd\ne\n", "lines.txt")
        self.assertMessage(complex_multipart_message("plain"))

    def test_send_patch(self):
        self.send_email("a\nb\nc\nd\ne\n", "lines.txt", "x-patch")
        self.assertMessage(complex_multipart_message("x-patch"))

    def test_send_simple(self):
        self.send_email()
        self.assertMessage(SIMPLE_MESSAGE_ASCII)
