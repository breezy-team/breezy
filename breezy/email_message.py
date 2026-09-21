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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""A convenience class for building the email messages breezy sends."""

from . import __version__ as _breezy_version
from ._cmd_rs import email_message as _email_message_rs
from .errors import BzrBadParameterNotUnicode
from .smtp_connection import SMTPConnection

_USER_AGENT = f"Bazaar ({_breezy_version})"


def _translate_unicode_errors(func, *args, **kwargs):
    """Call func, reporting non-unicode arguments as breezy errors."""
    try:
        return func(*args, **kwargs)
    except _email_message_rs.BadParameterNotUnicode as e:
        raise BzrBadParameterNotUnicode(e.args[0]) from e


class EmailMessage:
    """An email message.

    The constructor needs an origin address, a destination address or addresses
    and a subject, and accepts a body as well. Add additional parts to the
    message with add_inline_attachment(). Retrieve the entire formatted message
    with as_string().

    Headers can be accessed with get() and msg[], and modified with msg[] =.
    """

    def __init__(self, from_address, to_address, subject, body=None):
        """Create an email message.

        :param from_address: The origin address, to be put on the From header.
        :param to_address: The destination address of the message, to be put in
            the To header. Can also be a list of addresses.
        :param subject: The subject of the message.
        :param body: If given, the body of the message.

        All four parameters can be unicode strings or byte strings, but for the
        addresses and subject byte strings must be encoded in UTF-8. For the
        body any byte string will be accepted; if it's not ASCII or UTF-8,
        it'll be sent with charset=8-bit.
        """
        self._msg = _translate_unicode_errors(
            _email_message_rs.EmailMessage,
            from_address,
            to_address,
            subject,
            body,
            _USER_AGENT,
        )

    def add_inline_attachment(self, body, filename=None, mime_subtype="plain"):
        """Add an inline attachment to the message.

        :param body: A text to attach. Can be an unicode string or a byte
            string, and it'll be sent as ascii, utf-8, or 8-bit, in that
            preferred order.
        :param filename: The name for the attachment. This will give a default
            name for email programs to save the attachment.
        :param mime_subtype: MIME subtype of the attachment (eg. 'plain' for
            text/plain [default]).

        The attachment body will be displayed inline, so do not use this
        function to attach binary attachments.

        :raises ValueError: if the filename or subtype contains a line break.
        """
        self._msg.add_inline_attachment(body, filename, mime_subtype)

    def as_string(self, boundary=None):
        """Return the entire formatted message as a string.

        :param boundary: The boundary to use between MIME parts, if applicable.
            Used for tests.
        """
        return self._msg.as_string(boundary)

    __str__ = as_string

    def get(self, header, failobj=None):
        """Get a header from the message, returning failobj if not present."""
        return self._msg.get(header, failobj)

    def __getitem__(self, header):
        """Get a header from the message, returning None if not present.

        This method intentionally does not raise KeyError to mimic the behavior
        of __getitem__ in email.Message.
        """
        return self._msg[header]

    def __setitem__(self, header, value):
        """Set a header in the message.

        Args:
            header: The header name to set.
            value: The value to set for the header.
        """
        self._msg[header] = value

    @staticmethod
    def send(
        config,
        from_address,
        to_address,
        subject,
        body,
        attachment=None,
        attachment_filename=None,
        attachment_mime_subtype="plain",
    ):
        """Create an email message and send it with SMTPConnection.

        :param config: config object to pass to SMTPConnection constructor.

        See EmailMessage.__init__() and EmailMessage.add_inline_attachment()
        for an explanation of the rest of parameters.
        """
        msg = EmailMessage(from_address, to_address, subject, body)
        if attachment is not None:
            msg.add_inline_attachment(
                attachment, attachment_filename, attachment_mime_subtype
            )
        SMTPConnection(config).send_email(msg)

    @staticmethod
    def address_to_encoded_header(address):
        """RFC2047-encode an address if necessary.

        :param address: An unicode string.
        :return: A possibly RFC2047-encoded string.
        :raises ValueError: if the address itself is not ASCII.
        """
        return _translate_unicode_errors(
            _email_message_rs.address_to_encoded_header, address
        )

    @staticmethod
    def string_with_encoding(string_):
        r"""Return a str object together with an encoding.

        :param string\\_: A str or unicode object.
        :return: A tuple (str, encoding), where encoding is one of 'ascii',
            'utf-8', or '8-bit', in that preferred order.
        """
        return _email_message_rs.string_with_encoding(string_)
