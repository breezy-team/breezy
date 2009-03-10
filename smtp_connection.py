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

"""A convenience class around smtplib and email."""

from email.Header import Header
from email.Message import Message
try:
    # python <= 2.4
    from email.MIMEText import MIMEText
    from email.MIMEMultipart import MIMEMultipart
    from email.Utils import parseaddr
except ImportError:
    # python 2.5 moved MIMEText into a better namespace
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from email.utils import parseaddr
import socket
import smtplib

from bzrlib import (
    errors,
    ui,
    __version__ as _bzrlib_version,
    )


class SMTPConnection(object):
    """Connect to an SMTP server and send an email.

    This is a gateway between bzrlib.config.Config and smtplib.SMTP. It
    understands the basic bzr SMTP configuration information.
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
        try:
            self._connection.connect(self._smtp_server)
        except socket.error, e:
            raise errors.SocketConnectionError(
                host=self._smtp_server,
                msg="Unable to connect to smtp server to send email to",
                orig_error=e)

        # If this fails, it just returns an error, but it shouldn't raise an
        # exception unless something goes really wrong (in which case we want
        # to fail anyway).
        try:
            self._connection.starttls()
        except smtplib.SMTPException, e:
            if e.args[0] == 'STARTTLS extension not supported by server.':
                # python2.6 changed to raising an exception here; we can't
                # really do anything else without it so just continue
                # <https://bugs.edge.launchpad.net/bzr-email/+bug/335332>
                pass
            else:
                raise

    def _authenticate(self):
        """If necessary authenticate yourself to the server."""
        if self._smtp_username is None:
            return

        if self._smtp_password is None:
            self._smtp_password = ui.ui_factory.get_password(
                'Please enter the SMTP password: %(user)s@%(host)s',
                user=self._smtp_username,
                host=self._smtp_server)
        try:
            self._connection.login(self._smtp_username, self._smtp_password)
        except smtplib.SMTPHeloError, e:
            raise errors.BzrCommandError('SMTP server refused HELO: %d %s'
                                         % (e.smtp_code, e.smtp_error))
        except smtplib.SMTPAuthenticationError, e:
            raise errors.BzrCommandError('SMTP server refused authentication: %d %s'
                                         % (e.smtp_code, e.smtp_error))
        except smtplib.SMTPException, e:
            raise errors.BzrCommandError(str(e))

    @staticmethod
    def _split_address(address):
        """Split an username + email address into its parts.

        This takes "Joe Foo <joe@foo.com>" and returns "Joe Foo",
        "joe@foo.com".
        :param address: A combined username
        :return: (username, email)
        """
        return parseaddr(address)

    def _basic_message(self, from_address, to_addresses, subject):
        """Create the basic Message using the right Header info.

        This creates an email Message with no payload.
        :param from_address: The Unicode from address.
        :param to_addresses: A list of Unicode destination addresses.
        :param subject: A Unicode subject for the email.
        """
        # It would be nice to use a single part if we only had one, but we
        # would have to know ahead of time how many parts we needed.
        # So instead, just default to multipart.
        msg = MIMEMultipart()

        # Header() does a good job of doing the proper encoding. However it
        # confuses my SMTP server because it doesn't decode the strings. So it
        # is better to send the addresses as:
        #   =?utf-8?q?username?= <email@addr.com>
        # Which is how Thunderbird does it

        from_user, from_email = self._split_address(from_address)
        msg['From'] = '%s <%s>' % (Header(unicode(from_user)), from_email)
        msg['User-Agent'] = 'bzr/%s' % _bzrlib_version

        to_emails = []
        to_header = []
        for addr in to_addresses:
            to_user, to_email = self._split_address(addr)
            to_emails.append(to_email)
            to_header.append('%s <%s>' % (Header(unicode(to_user)), to_email))

        msg['To'] = ', '.join(to_header)
        msg['Subject'] = Header(subject)
        return msg, from_email, to_emails

    def create_email(self, from_address, to_addresses, subject, text):
        """Create an email.Message object.

        This function allows you to create a basic email, and then add extra
        payload to it.

        :param from_address: A Unicode string with the source email address.
            Example: u'Joe B\xe5 <joe@bar.com>'
        :param to_addresses: A list of addresses to send to.
            Example: [u'Joe B\xe5 <joe@bar.com>', u'Lilly <lilly@nowhere.com>']
        :param subject: A Unicode Subject for the email.
            Example: u'Use Bazaar, its c\xb5l'
        :param text: A Unicode message (will be encoded into utf-8)
            Example: u'I started using Bazaar today.\nI highly recommend it.\n'
        :return: (email_message, from_email, to_emails)
            email_message: is a MIME wrapper with the email headers setup. You
                can add more payload by using .attach()
            from_email: the email address extracted from from_address
            to_emails: the list of email addresses extracted from to_addresses
        """
        msg, from_email, to_emails = self._basic_message(from_address,
                                                         to_addresses, subject)
        payload = MIMEText(text.encode('utf-8'), 'plain', 'utf-8')
        msg.attach(payload)
        return msg, from_email, to_emails

    def send_email(self, email_message, from_email, to_emails):
        """Actually send an email to the server.

        If your requirements are simple, you can simply:
        smtp.send_email(*smtp.create_email(...))
        because the parameters passed to send_email() are the same as the
        parameters returned from create_email.

        :param email_message: An email.Message object. You can just pass the
            value from create_email().
        :param from_email: The email address to send from. Usually just the
            value returned from create_email()
        :param to_emails: A list of emails to send to.
        :return: None
        """
        self._connect()
        self._connection.sendmail(from_email, to_emails,
                                  email_message.as_string())

    def send_text_email(self, from_address, to_addresses, subject, message):
        """Send a single text-only email.

        This is a helper when you know you are just sending a simple text
        message. See create_email for an explanation of parameters.
        """
        msg, from_email, to_emails = self.create_email(from_address,
                                            to_addresses, subject, message)
        self.send_email(msg, from_email, to_emails)

    def send_text_and_attachment_email(self, from_address, to_addresses,
                                       subject, message, attachment_text,
                                       attachment_filename='patch.diff'):
        """Send a Unicode message and an 8-bit attachment.

        See create_email for common parameter definitions.
        :param attachment_text: This is assumed to be an 8-bit text attachment.
            This assumes you want the attachment to be shown in the email.
            So don't use this for binary file attachments.
        :param attachment_filename: The name for the attachement. This will
            give a default name for email programs to save the attachment.
        """
        msg, from_email, to_emails = self.create_email(from_address,
                                            to_addresses, subject, message)
        # Must be an 8-bit string
        assert isinstance(attachment_text, str)

        diff_payload = MIMEText(attachment_text, 'plain', '8-bit')
        # Override Content-Type so that we can include the name
        content_type = diff_payload['Content-Type']
        content_type += '; name="%s"' % (attachment_filename,)
        diff_payload.replace_header('Content-Type', content_type)
        diff_payload['Content-Disposition'] = ('inline; filename="%s"'
                                               % (attachment_filename,))
        msg.attach(diff_payload)
        self.send_email(msg, from_email, to_emails)
