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
import tempfile

from bzrlib import (
    email_message,
    errors,
    msgeditor,
    urlutils,
    )


class MailClient(object):
    """A mail client that can send messages with attachements."""

    def __init__(self, config):
        self.config = config

    def compose(self, prompt, to, subject, attachment, mime_subtype,
                extension):
        raise NotImplementedError

    def compose_merge_request(self, to, subject, directive):
        prompt = self._get_merge_prompt("Please describe these changes:", to,
                                        subject, directive)
        self.compose(prompt, to, subject, directive,
            'x-patch', '.patch')

    def _get_merge_prompt(self, prompt, to, subject, attachment):
        return ''


class Editor(MailClient):
    """DIY mail client that uses commit message editor"""

    def _get_merge_prompt(self, prompt, to, subject, attachment):
        return "%s\n\nTo: %s\nSubject: %s\n\n%s" % (prompt, to, subject,
                attachment.decode('utf-8', 'replace'))

    def compose(self, prompt, to, subject, attachment, mime_subtype,
                extension):
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


class Evolution(MailClient):
    """Evolution mail client."""

    _client_commands = ['evolution']

    def compose(self, prompt, to, subject, attachment, mime_subtype,
                extension):
        fd, pathname = tempfile.mkstemp(extension, 'bzr-mail-')
        try:
            os.write(fd, attachment)
        finally:
            os.close(fd)
        for name in self._client_commands:
            cmdline = [name]
            cmdline.extend(self._get_compose_commandline(to, subject,
                                                         pathname))
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
        message_options = {}
        if subject is not None:
            message_options['subject'] = subject
        if attach_path is not None:
            message_options['attach'] = attach_path
        options_list = ['%s=%s' % (k, urlutils.escape(v)) for (k, v) in
                        message_options.iteritems()]
        return ['mailto:%s?%s' % (to or '', '&'.join(options_list))]


class Thunderbird(Evolution):
    """Mozilla Thunderbird (or Icedove)

    Note that Thunderbird 1.5 is buggy and does not support setting
    "to" simultaneously with including a attachment.

    There is a workaround if no attachment is present, but we always need to
    send attachments.
    """

    _client_commands = ['thunderbird', 'mozilla-thunderbird', 'icedove']

    def _get_compose_commandline(self, to, subject, attach_path):
        message_options = {}
        if to is not None:
            message_options['to'] = to
        if subject is not None:
            message_options['subject'] = subject
        if attach_path is not None:
            message_options['attachment'] = urlutils.local_path_to_url(
                attach_path)
        options_list = ["%s='%s'" % (k, v) for k, v in
                        sorted(message_options.iteritems())]
        return ['-compose', ','.join(options_list)]


class KMail(Evolution):
    """KDE mail client."""

    _client_commands = ['kmail']

    def _get_compose_commandline(self, to, subject, attach_path):
        message_options = []
        if subject is not None:
            message_options.extend( ['-s', subject ] )
        if attach_path is not None:
            message_options.extend( ['--attach', attach_path] )
        if to is not None:
            message_options.extend( [ to ] )

        return message_options


class XDGEmail(Evolution):
    """xdg-email attempts to invoke the user's preferred mail client"""

    _client_commands = ['xdg-email']

    def _get_compose_commandline(self, to, subject, attach_path):
        commandline = [to]
        if subject is not None:
            commandline.extend(['--subject', subject])
        if attach_path is not None:
            commandline.extend(['--attach', attach_path])
        return commandline


class DefaultMail(MailClient):
    """Default mail handling.  Tries XDGEmail, falls back to Editor"""

    def compose(self, prompt, to, subject, attachment, mime_subtype,
                extension):
        try:
            return XDGEmail(self.config).compose(prompt, to, subject,
                            attachment, mimie_subtype, extension)
        except errors.MailClientNotFound:
            return Editor(self.config).compose(prompt, to, subject,
                          attachment, mimie_subtype, extension)

    def compose_merge_request(self, to, subject, directive):
        try:
            return XDGEmail(self.config).compose_merge_request(to, subject,
                            directive)
        except errors.MailClientNotFound:
            return Editor(self.config).compose_merge_request(to, subject,
                          directive)
