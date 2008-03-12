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

import errno
import os
import subprocess
import sys
import tempfile

import bzrlib
from bzrlib import (
    email_message,
    errors,
    msgeditor,
    osutils,
    urlutils,
    )


class MailClient(object):
    """A mail client that can send messages with attachements."""

    def __init__(self, config):
        self.config = config

    def compose(self, prompt, to, subject, attachment, mime_subtype,
                extension, basename=None):
        """Compose (and possibly send) an email message

        Must be implemented by subclasses.

        :param prompt: A message to tell the user what to do.  Supported by
            the Editor client, but ignored by others
        :param to: The address to send the message to
        :param subject: The contents of the subject line
        :param attachment: An email attachment, as a bytestring
        :param mime_subtype: The attachment is assumed to be a subtype of
            Text.  This allows the precise subtype to be specified, e.g.
            "plain", "x-patch", etc.
        :param extension: The file extension associated with the attachment
            type, e.g. ".patch"
        :param basename: The name to use for the attachment, e.g.
            "send-nick-3252"
        """
        raise NotImplementedError

    def compose_merge_request(self, to, subject, directive, basename=None):
        """Compose (and possibly send) a merge request

        :param to: The address to send the request to
        :param subject: The subject line to use for the request
        :param directive: A merge directive representing the merge request, as
            a bytestring.
        :param basename: The name to use for the attachment, e.g.
            "send-nick-3252"
        """
        prompt = self._get_merge_prompt("Please describe these changes:", to,
                                        subject, directive)
        self.compose(prompt, to, subject, directive,
            'x-patch', '.patch', basename)

    def _get_merge_prompt(self, prompt, to, subject, attachment):
        """Generate a prompt string.  Overridden by Editor.

        :param prompt: A string suggesting what user should do
        :param to: The address the mail will be sent to
        :param subject: The subject line of the mail
        :param attachment: The attachment that will be used
        """
        return ''


class Editor(MailClient):
    """DIY mail client that uses commit message editor"""

    def _get_merge_prompt(self, prompt, to, subject, attachment):
        """See MailClient._get_merge_prompt"""
        return (u"%s\n\n"
                u"To: %s\n"
                u"Subject: %s\n\n"
                u"%s" % (prompt, to, subject,
                         attachment.decode('utf-8', 'replace')))

    def compose(self, prompt, to, subject, attachment, mime_subtype,
                extension, basename=None):
        """See MailClient.compose"""
        if not to:
            raise errors.NoMailAddressSpecified()
        body = msgeditor.edit_commit_message(prompt)
        if body == '':
            raise errors.NoMessageSupplied()
        email_message.EmailMessage.send(self.config,
                                        self.config.username(),
                                        to,
                                        subject,
                                        body,
                                        attachment,
                                        attachment_mime_subtype=mime_subtype)


class ExternalMailClient(MailClient):
    """An external mail client."""

    def _get_client_commands(self):
        """Provide a list of commands that may invoke the mail client"""
        if sys.platform == 'win32':
            import win32utils
            return [win32utils.get_app_path(i) for i in self._client_commands]
        else:
            return self._client_commands

    def compose(self, prompt, to, subject, attachment, mime_subtype,
                extension, basename=None):
        """See MailClient.compose.

        Writes the attachment to a temporary file, invokes _compose.
        """
        if basename is None:
            basename = 'attachment'
        pathname = tempfile.mkdtemp(prefix='bzr-mail-')
        attach_path = osutils.pathjoin(pathname, basename + extension)
        outfile = open(attach_path, 'wb')
        try:
            outfile.write(attachment)
        finally:
            outfile.close()
        self._compose(prompt, to, subject, attach_path, mime_subtype,
                      extension)

    def _compose(self, prompt, to, subject, attach_path, mime_subtype,
                extension):
        """Invoke a mail client as a commandline process.

        Overridden by MAPIClient.
        :param to: The address to send the mail to
        :param subject: The subject line for the mail
        :param pathname: The path to the attachment
        :param mime_subtype: The attachment is assumed to have a major type of
            "text", but the precise subtype can be specified here
        :param extension: A file extension (including period) associated with
            the attachment type.
        """
        for name in self._get_client_commands():
            cmdline = [self._encode_path(name, 'executable')]
            cmdline.extend(self._get_compose_commandline(to, subject,
                                                         attach_path))
            try:
                subprocess.call(cmdline)
            except OSError, e:
                if e.errno != errno.ENOENT:
                    raise
            else:
                break
        else:
            raise errors.MailClientNotFound(self._client_commands)

    def _get_compose_commandline(self, to, subject, attach_path):
        """Determine the commandline to use for composing a message

        Implemented by various subclasses
        :param to: The address to send the mail to
        :param subject: The subject line for the mail
        :param attach_path: The path to the attachment
        """
        raise NotImplementedError

    def _encode_safe(self, u):
        """Encode possible unicode string argument to 8-bit string
        in user_encoding. Unencodable characters will be replaced
        with '?'.

        :param  u:  possible unicode string.
        :return:    encoded string if u is unicode, u itself otherwise.
        """
        if isinstance(u, unicode):
            return u.encode(osutils.get_user_encoding(), 'replace')
        return u

    def _encode_path(self, path, kind):
        """Encode unicode path in user encoding.

        :param  path:   possible unicode path.
        :param  kind:   path kind ('executable' or 'attachment').
        :return:        encoded path if path is unicode,
                        path itself otherwise.
        :raise:         UnableEncodePath.
        """
        if isinstance(path, unicode):
            try:
                return path.encode(osutils.get_user_encoding())
            except UnicodeEncodeError:
                raise errors.UnableEncodePath(path, kind)
        return path


class Evolution(ExternalMailClient):
    """Evolution mail client."""

    _client_commands = ['evolution']

    def _get_compose_commandline(self, to, subject, attach_path):
        """See ExternalMailClient._get_compose_commandline"""
        message_options = {}
        if subject is not None:
            message_options['subject'] = subject
        if attach_path is not None:
            message_options['attach'] = attach_path
        options_list = ['%s=%s' % (k, urlutils.escape(v)) for (k, v) in
                        sorted(message_options.iteritems())]
        return ['mailto:%s?%s' % (self._encode_safe(to or ''),
            '&'.join(options_list))]


class Mutt(ExternalMailClient):
    """Mutt mail client."""

    _client_commands = ['mutt']

    def _get_compose_commandline(self, to, subject, attach_path):
        """See ExternalMailClient._get_compose_commandline"""
        message_options = []
        if subject is not None:
            message_options.extend(['-s', self._encode_safe(subject)])
        if attach_path is not None:
            message_options.extend(['-a',
                self._encode_path(attach_path, 'attachment')])
        if to is not None:
            message_options.append(self._encode_safe(to))
        return message_options


class Thunderbird(ExternalMailClient):
    """Mozilla Thunderbird (or Icedove)

    Note that Thunderbird 1.5 is buggy and does not support setting
    "to" simultaneously with including a attachment.

    There is a workaround if no attachment is present, but we always need to
    send attachments.
    """

    _client_commands = ['thunderbird', 'mozilla-thunderbird', 'icedove',
        '/Applications/Mozilla/Thunderbird.app/Contents/MacOS/thunderbird-bin']

    def _get_compose_commandline(self, to, subject, attach_path):
        """See ExternalMailClient._get_compose_commandline"""
        message_options = {}
        if to is not None:
            message_options['to'] = self._encode_safe(to)
        if subject is not None:
            message_options['subject'] = self._encode_safe(subject)
        if attach_path is not None:
            message_options['attachment'] = urlutils.local_path_to_url(
                attach_path)
        options_list = ["%s='%s'" % (k, v) for k, v in
                        sorted(message_options.iteritems())]
        return ['-compose', ','.join(options_list)]


class KMail(ExternalMailClient):
    """KDE mail client."""

    _client_commands = ['kmail']

    def _get_compose_commandline(self, to, subject, attach_path):
        """See ExternalMailClient._get_compose_commandline"""
        message_options = []
        if subject is not None:
            message_options.extend(['-s', self._encode_safe(subject)])
        if attach_path is not None:
            message_options.extend(['--attach',
                self._encode_path(attach_path, 'attachment')])
        if to is not None:
            message_options.extend([self._encode_safe(to)])
        return message_options


class XDGEmail(ExternalMailClient):
    """xdg-email attempts to invoke the user's preferred mail client"""

    _client_commands = ['xdg-email']

    def _get_compose_commandline(self, to, subject, attach_path):
        """See ExternalMailClient._get_compose_commandline"""
        if not to:
            raise errors.NoMailAddressSpecified()
        commandline = [self._encode_safe(to)]
        if subject is not None:
            commandline.extend(['--subject', self._encode_safe(subject)])
        if attach_path is not None:
            commandline.extend(['--attach',
                self._encode_path(attach_path, 'attachment')])
        return commandline


class MAPIClient(ExternalMailClient):
    """Default Windows mail client launched using MAPI."""

    def _compose(self, prompt, to, subject, attach_path, mime_subtype,
                 extension):
        """See ExternalMailClient._compose.

        This implementation uses MAPI via the simplemapi ctypes wrapper
        """
        from bzrlib.util import simplemapi
        try:
            simplemapi.SendMail(to or '', subject or '', '', attach_path)
        except simplemapi.MAPIError, e:
            if e.code != simplemapi.MAPI_USER_ABORT:
                raise errors.MailClientNotFound(['MAPI supported mail client'
                                                 ' (error %d)' % (e.code,)])


class DefaultMail(MailClient):
    """Default mail handling.  Tries XDGEmail (or MAPIClient on Windows),
    falls back to Editor"""

    def _mail_client(self):
        """Determine the preferred mail client for this platform"""
        if osutils.supports_mapi():
            return MAPIClient(self.config)
        else:
            return XDGEmail(self.config)

    def compose(self, prompt, to, subject, attachment, mime_subtype,
                extension, basename=None):
        """See MailClient.compose"""
        try:
            return self._mail_client().compose(prompt, to, subject,
                                               attachment, mimie_subtype,
                                               extension, basename)
        except errors.MailClientNotFound:
            return Editor(self.config).compose(prompt, to, subject,
                          attachment, mimie_subtype, extension)

    def compose_merge_request(self, to, subject, directive):
        """See MailClient.compose_merge_request"""
        try:
            return self._mail_client().compose_merge_request(to, subject,
                                                             directive)
        except errors.MailClientNotFound:
            return Editor(self.config).compose_merge_request(to, subject,
                          directive)
