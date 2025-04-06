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

"""A convenience class around smtplib."""

import smtplib
import socket
from email.utils import getaddresses, parseaddr

from . import config
from .errors import BzrError, InternalBzrError

smtp_password = config.Option(
    "smtp_password",
    default=None,
    help="""\
Password to use for authentication to SMTP server.
""",
)
smtp_server = config.Option(
    "smtp_server",
    default=None,
    help="""\
Hostname of the SMTP server to use for sending email.
""",
)
smtp_username = config.Option(
    "smtp_username",
    default=None,
    help="""\
Username to use for authentication to SMTP server.
""",
)


class SMTPError(BzrError):
    _fmt = "SMTP error: %(error)s"

    def __init__(self, error):
        self.error = error


class SMTPConnectionRefused(SMTPError):
    _fmt = "SMTP connection to %(host)s refused"

    def __init__(self, error, host):
        self.error = error
        self.host = host


class DefaultSMTPConnectionRefused(SMTPConnectionRefused):
    _fmt = "Please specify smtp_server.  No server at default %(host)s."


class NoDestinationAddress(InternalBzrError):
    _fmt = "Message does not have a destination address."


class SMTPConnection:
    """Connect to an SMTP server and send an email.

    This is a gateway between breezy.config.Config and smtplib.SMTP. It
    understands the basic bzr SMTP configuration information: smtp_server,
    smtp_username, and smtp_password.
    """

    _default_smtp_server = "localhost"

    def __init__(self, config, _smtp_factory=None):
        self._smtp_factory = _smtp_factory
        if self._smtp_factory is None:
            self._smtp_factory = smtplib.SMTP
        self._config = config
        self._config_smtp_server = config.get("smtp_server")
        self._smtp_server = self._config_smtp_server
        if self._smtp_server is None:
            self._smtp_server = self._default_smtp_server

        self._smtp_username = config.get("smtp_username")
        self._smtp_password = config.get("smtp_password")

        self._connection = None

    def _connect(self):
        """If we haven't connected, connect and authenticate."""
        if self._connection is not None:
            return

        self._create_connection()
        # FIXME: _authenticate() should only be called when the server has
        # refused unauthenticated access, so it can safely try to authenticate
        # with the default username. JRV20090407
        self._authenticate()

    def _create_connection(self):
        """Create an SMTP connection."""
        try:
            self._connection = self._smtp_factory(host=self._smtp_server)
        except ConnectionRefusedError as err:
            if self._config_smtp_server is None:
                raise DefaultSMTPConnectionRefused(
                    socket.error, self._smtp_server
                ) from err
            else:
                raise SMTPConnectionRefused(socket.error, self._smtp_server) from err

        # Say EHLO (falling back to HELO) to query the server's features.
        code, resp = self._connection.ehlo()
        if not (200 <= code <= 299):
            code, resp = self._connection.helo()
            if not (200 <= code <= 299):
                raise SMTPError(f"server refused HELO: {code} {resp}")

        # Use TLS if the server advertised it:
        if self._connection.has_extn("starttls"):
            code, resp = self._connection.starttls()
            if not (200 <= code <= 299):
                raise SMTPError("server refused STARTTLS: %d %s" % (code, resp))
            # Say EHLO again, to check for newly revealed features
            code, resp = self._connection.ehlo()
            if not (200 <= code <= 299):
                raise SMTPError(f"server refused EHLO: {code} {resp}")

    def _authenticate(self):
        """If necessary authenticate yourself to the server."""
        auth = config.AuthenticationConfig()
        if self._smtp_username is None:
            # FIXME: Since _authenticate gets called even when no authentication
            # is necessary, it's not possible to use the default username
            # here yet.
            self._smtp_username = auth.get_user("smtp", self._smtp_server)
            if self._smtp_username is None:
                return

        if self._smtp_password is None:
            self._smtp_password = auth.get_password(
                "smtp", self._smtp_server, self._smtp_username
            )

        # smtplib requires that the username and password be byte
        # strings.  The CRAM-MD5 spec doesn't give any guidance on
        # encodings, but the SASL PLAIN spec says UTF-8, so that's
        # what we'll use.
        username = self._smtp_username.encode("utf-8")
        password = self._smtp_password.encode("utf-8")

        self._connection.login(username, password)

    @staticmethod
    def get_message_addresses(message):
        """Get the origin and destination addresses of a message.

        :param message: A message object supporting get() to access its
            headers, like email.message.Message or
            breezy.email_message.EmailMessage.
        :return: A pair (from_email, to_emails), where from_email is the email
            address in the From header, and to_emails a list of all the
            addresses in the To, Cc, and Bcc headers.
        """
        from_email = parseaddr(message.get("From", None))[1]
        to_full_addresses = []
        for header in ["To", "Cc", "Bcc"]:
            value = message.get(header, None)
            if value:
                to_full_addresses.append(value)
        to_emails = [pair[1] for pair in getaddresses(to_full_addresses)]

        return from_email, to_emails

    def send_email(self, message):
        """Send an email message.

        The message will be sent to all addresses in the To, Cc and Bcc
        headers.

        :param message: An email.message.Message or
            email.mime.multipart.MIMEMultipart object.
        :return: None
        """
        from_email, to_emails = self.get_message_addresses(message)

        if not to_emails:
            raise NoDestinationAddress

        try:
            self._connect()
            self._connection.sendmail(from_email, to_emails, message.as_string())
        except smtplib.SMTPRecipientsRefused as e:
            raise SMTPError(
                "server refused recipient: %d %s" % next(iter(e.recipients.values()))
            ) from er
        except smtplib.SMTPResponseException as e:
            raise SMTPError("%d %s" % (e.smtp_code, e.smtp_error)) from e
        except smtplib.SMTPException as e:
            raise SMTPError(str(e)) from e
