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

"""A convenience class around smtplib."""

from email import Utils
import smtplib

from bzrlib import ui
from bzrlib.errors import NoDestinationAddress, SMTPError


class SMTPConnection(object):
    """Connect to an SMTP server and send an email.

    This is a gateway between bzrlib.config.Config and smtplib.SMTP. It
    understands the basic bzr SMTP configuration information: smtp_server,
    smtp_username, and smtp_password.
    """

    _default_smtp_server = 'localhost'

    def __init__(self, config):
        self._config = config
        self._smtp_server = config.get_user_option('smtp_server')
        if self._smtp_server is None:
            self._smtp_server = self._default_smtp_server

        self._smtp_username = config.get_user_option('smtp_username')
        self._smtp_password = config.get_user_option('smtp_password')

        self._connection = None

    def _connect(self):
        """If we haven't connected, connect and authenticate."""
        if self._connection is not None:
            return

        self._create_connection()
        self._authenticate()

    def _create_connection(self):
        """Create an SMTP connection."""
        self._connection = smtplib.SMTP()
        self._connection.connect(self._smtp_server)

        # If this fails, it just returns an error, but it shouldn't raise an
        # exception unless something goes really wrong (in which case we want
        # to fail anyway).
        self._connection.starttls()

    def _authenticate(self):
        """If necessary authenticate yourself to the server."""
        if self._smtp_username is None:
            return

        if self._smtp_password is None:
            self._smtp_password = ui.ui_factory.get_password(
                'Please enter the SMTP password: %(user)s@%(host)s',
                user=self._smtp_username,
                host=self._smtp_server)

        self._connection.login(self._smtp_username, self._smtp_password)

    @staticmethod
    def get_message_addresses(message):
        """Get the origin and destination addresses of a message.

        :param message: An email.Message or email.MIMEMultipart object.
        :return: A pair (from_email, to_emails), where from_email is the email
            address in the From header, and to_emails a list of all the
            addresses in the To, Cc, and Bcc headers.
        """
        from_email = Utils.parseaddr(message['From'])[1]
        to_full_addresses = []
        for header in ['To', 'Cc', 'Bcc']:
            to_full_addresses += message.get_all(header, [])
        to_emails = [ pair[1] for pair in
                Utils.getaddresses(to_full_addresses) ]

        return from_email, to_emails

    def send_email(self, message):
        """Send an email message.

        The message will be sent to all addresses in the To, Cc and Bcc
        headers.

        :param message: An email.Message or email.MIMEMultipart object.
        :return: None
        """
        from_email, to_emails = self.get_message_addresses(message)

        if not to_emails:
            raise NoDestinationAddress

        try:
            self._connect()
            self._connection.sendmail(from_email, to_emails,
                                      message.as_string())
        except smtplib.SMTPRecipientsRefused, e:
            raise SMTPError('server refused recipient: %d %s' %
                    e.recipients.values()[0])
        except smtplib.SMTPResponseException, e:
            raise SMTPError('%d %s' % (e.smtp_code, e.smtp_error))
        except smtplib.SMTPException, e:
            raise SMTPError(str(e))
