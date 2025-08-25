# Copyright (C) 2007-2010 Canonical Ltd
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

"""Mail client implementations for sending emails with attachments.

This module provides various mail client implementations that can be used to send
email messages with attachments through different mail applications and services.
Supported clients include Evolution, Mutt, Thunderbird, KMail, and others.
"""

import os
import subprocess
import sys
import tempfile

from . import config as _mod_config
from . import email_message, errors, msgeditor, osutils, registry, urlutils


class MailClientNotFound(errors.BzrError):
    """Exception raised when no suitable mail client can be found."""

    _fmt = (
        "Unable to find mail client with the following names:"
        " %(mail_command_list_string)s"
    )

    def __init__(self, mail_command_list):
        """Initialize the exception with the list of mail commands that were tried.

        Args:
            mail_command_list: List of mail client command names that were attempted.
        """
        mail_command_list_string = ", ".join(mail_command_list)
        errors.BzrError.__init__(
            self,
            mail_command_list=mail_command_list,
            mail_command_list_string=mail_command_list_string,
        )


class NoMessageSupplied(errors.BzrError):
    """Exception raised when no message body is supplied for an email."""

    _fmt = "No message supplied."


class NoMailAddressSpecified(errors.BzrError):
    """Exception raised when no mail-to address is specified."""

    _fmt = "No mail-to address (--mail-to) or output (-o) specified."


class MailClient:
    """A mail client that can send messages with attachements."""

    def __init__(self, config):
        """Initialize the mail client with configuration.

        Args:
            config: Configuration object containing mail settings.
        """
        self.config = config

    def compose(
        self,
        prompt,
        to,
        subject,
        attachment,
        mime_subtype,
        extension,
        basename=None,
        body=None,
    ):
        """Compose (and possibly send) an email message.

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

    def compose_merge_request(self, to, subject, directive, basename=None, body=None):
        """Compose (and possibly send) a merge request.

        :param to: The address to send the request to
        :param subject: The subject line to use for the request
        :param directive: A merge directive representing the merge request, as
            a bytestring.
        :param basename: The name to use for the attachment, e.g.
            "send-nick-3252"
        """
        prompt = self._get_merge_prompt(
            "Please describe these changes:", to, subject, directive
        )
        self.compose(
            prompt, to, subject, directive, "x-patch", ".patch", basename, body
        )

    def _get_merge_prompt(self, prompt, to, subject, attachment):
        """Generate a prompt string.  Overridden by Editor.

        :param prompt: A string suggesting what user should do
        :param to: The address the mail will be sent to
        :param subject: The subject line of the mail
        :param attachment: The attachment that will be used
        """
        return ""


mail_client_registry = registry.Registry[str, type[MailClient], None]()


class Editor(MailClient):
    """DIY mail client that uses commit message editor.

    This mail client opens the user's configured editor to compose the email
    message body and then sends the email using the built-in email facilities.
    """

    supports_body = True

    def _get_merge_prompt(self, prompt, to, subject, attachment):
        """See MailClient._get_merge_prompt."""
        return "{}\n\nTo: {}\nSubject: {}\n\n{}".format(
            prompt, to, subject, attachment.decode("utf-8", "replace")
        )

    def compose(
        self,
        prompt,
        to,
        subject,
        attachment,
        mime_subtype,
        extension,
        basename=None,
        body=None,
    ):
        """See MailClient.compose."""
        if not to:
            raise NoMailAddressSpecified()
        body = msgeditor.edit_commit_message(prompt, start_message=body)
        if body == "":
            raise NoMessageSupplied()
        email_message.EmailMessage.send(
            self.config,
            self.config.get("email"),
            to,
            subject,
            body,
            attachment,
            attachment_mime_subtype=mime_subtype,
        )


mail_client_registry.register("editor", Editor, help=Editor.__doc__)


class BodyExternalMailClient(MailClient):
    """Base class for external mail clients that support message body text.

    This class provides common functionality for mail clients that can handle
    both email attachments and body text when composing messages.
    """

    supports_body = True

    def _get_client_commands(self):
        """Provide a list of commands that may invoke the mail client."""
        if sys.platform == "win32":
            import win32utils

            return [win32utils.get_app_path(i) for i in self._client_commands]
        else:
            return self._client_commands

    def compose(
        self,
        prompt,
        to,
        subject,
        attachment,
        mime_subtype,
        extension,
        basename=None,
        body=None,
    ):
        """See MailClient.compose.

        Writes the attachment to a temporary file, invokes _compose.
        """
        if basename is None:
            basename = "attachment"
        pathname = tempfile.mkdtemp(prefix="bzr-mail-")
        attach_path = osutils.pathjoin(pathname, basename + extension)
        with open(attach_path, "wb") as outfile:
            outfile.write(attachment)
        kwargs = {"body": body} if body is not None else {}
        self._compose(
            prompt, to, subject, attach_path, mime_subtype, extension, **kwargs
        )

    def _compose(
        self,
        prompt,
        to,
        subject,
        attach_path,
        mime_subtype,
        extension,
        body=None,
        from_=None,
    ):
        """Invoke a mail client as a commandline process.

        Overridden by MAPIClient.
        :param to: The address to send the mail to
        :param subject: The subject line for the mail
        :param pathname: The path to the attachment
        :param mime_subtype: The attachment is assumed to have a major type of
            "text", but the precise subtype can be specified here
        :param extension: A file extension (including period) associated with
            the attachment type.
        :param body: Optional body text.
        :param from_: Optional From: header.
        """
        for name in self._get_client_commands():
            cmdline = [self._encode_path(name, "executable")]
            kwargs = {"body": body} if body is not None else {}
            if from_ is not None:
                kwargs["from_"] = from_
            cmdline.extend(
                self._get_compose_commandline(to, subject, attach_path, **kwargs)
            )
            try:
                subprocess.call(cmdline)
            except FileNotFoundError:
                pass
            else:
                break
        else:
            raise MailClientNotFound(self._client_commands)

    def _get_compose_commandline(self, to, subject, attach_path, body):
        """Determine the commandline to use for composing a message.

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
        return u

    def _encode_path(self, path, kind):
        """Encode unicode path in user encoding.

        :param  path:   possible unicode path.
        :param  kind:   path kind ('executable' or 'attachment').
        :return:        encoded path if path is unicode,
                        path itself otherwise.
        :raise:         UnableEncodePath.
        """
        return path


class ExternalMailClient(BodyExternalMailClient):
    """An external mail client.

    Base class for external mail clients that do not support message body text
    in their command-line interface.
    """

    supports_body = False


class Evolution(BodyExternalMailClient):
    """Evolution mail client.

    Integrates with the Evolution email client using mailto URLs with
    parameters for subject, attachments, and body content.
    """

    _client_commands = ["evolution"]

    def _get_compose_commandline(self, to, subject, attach_path, body=None):
        """See ExternalMailClient._get_compose_commandline."""
        message_options = {}
        if subject is not None:
            message_options["subject"] = subject
        if attach_path is not None:
            message_options["attach"] = attach_path
        if body is not None:
            message_options["body"] = body
        options_list = [
            f"{k}={urlutils.escape(v)}" for (k, v) in sorted(message_options.items())
        ]
        return [f"mailto:{self._encode_safe(to or '')}?{'&'.join(options_list)}"]


mail_client_registry.register("evolution", Evolution, help=Evolution.__doc__)


class Mutt(BodyExternalMailClient):
    """Mutt mail client.

    Integrates with the Mutt email client using command-line options
    for composing messages with attachments and body text.
    """

    _client_commands = ["mutt"]

    def _get_compose_commandline(self, to, subject, attach_path, body=None):
        """See ExternalMailClient._get_compose_commandline."""
        message_options = []
        if subject is not None:
            message_options.extend(["-s", self._encode_safe(subject)])
        if attach_path is not None:
            message_options.extend(["-a", self._encode_path(attach_path, "attachment")])
        if body is not None:
            # Store the temp file object in self, so that it does not get
            # garbage collected and delete the file before mutt can read it.
            self._temp_file = tempfile.NamedTemporaryFile(
                prefix="mutt-body-", suffix=".txt", mode="w+"
            )
            self._temp_file.write(body)
            self._temp_file.flush()
            message_options.extend(["-i", self._temp_file.name])
        if to is not None:
            message_options.extend(["--", self._encode_safe(to)])
        return message_options


mail_client_registry.register("mutt", Mutt, help=Mutt.__doc__)


class Thunderbird(BodyExternalMailClient):
    """Mozilla Thunderbird (or Icedove) mail client.

    Integrates with Mozilla Thunderbird or Icedove using the -compose command-line
    option with URL-encoded parameters.

    Note:
        Thunderbird 1.5 is buggy and does not support setting "to" simultaneously
        with including an attachment. There is a workaround if no attachment is
        present, but we always need to send attachments.
    """

    _client_commands = [
        "thunderbird",
        "mozilla-thunderbird",
        "icedove",
        "/Applications/Mozilla/Thunderbird.app/Contents/MacOS/thunderbird-bin",
        "/Applications/Thunderbird.app/Contents/MacOS/thunderbird-bin",
    ]

    def _get_compose_commandline(self, to, subject, attach_path, body=None):
        """See ExternalMailClient._get_compose_commandline."""
        message_options = {}
        if to is not None:
            message_options["to"] = self._encode_safe(to)
        if subject is not None:
            message_options["subject"] = self._encode_safe(subject)
        if attach_path is not None:
            message_options["attachment"] = urlutils.local_path_to_url(attach_path)
        if body is not None:
            options_list = [f"body={urlutils.quote(self._encode_safe(body))}"]
        else:
            options_list = []
        options_list.extend([f"{k}='{v}'" for k, v in sorted(message_options.items())])
        return ["-compose", ",".join(options_list)]


mail_client_registry.register("thunderbird", Thunderbird, help=Thunderbird.__doc__)


class KMail(ExternalMailClient):
    """KDE mail client.

    Integrates with KMail using command-line options for subject,
    attachments, and recipient addresses.
    """

    _client_commands = ["kmail"]

    def _get_compose_commandline(self, to, subject, attach_path):
        """See ExternalMailClient._get_compose_commandline."""
        message_options = []
        if subject is not None:
            message_options.extend(["-s", self._encode_safe(subject)])
        if attach_path is not None:
            message_options.extend(
                ["--attach", self._encode_path(attach_path, "attachment")]
            )
        if to is not None:
            message_options.extend([self._encode_safe(to)])
        return message_options


mail_client_registry.register("kmail", KMail, help=KMail.__doc__)


class Claws(ExternalMailClient):
    """Claws mail client.

    Integrates with Claws Mail using mailto URLs and the --compose and
    --attach command-line options.
    """

    supports_body = True

    _client_commands = ["claws-mail"]

    def _get_compose_commandline(self, to, subject, attach_path, body=None, from_=None):
        """See ExternalMailClient._get_compose_commandline."""
        compose_url = []
        if from_ is not None:
            compose_url.append("from=" + urlutils.quote(from_))
        if subject is not None:
            # Don't use urlutils.quote_plus because Claws doesn't seem
            # to recognise spaces encoded as "+".
            compose_url.append("subject=" + urlutils.quote(self._encode_safe(subject)))
        if body is not None:
            compose_url.append("body=" + urlutils.quote(self._encode_safe(body)))
        # to must be supplied for the claws-mail --compose syntax to work.
        if to is None:
            raise NoMailAddressSpecified()
        compose_url = f"mailto:{self._encode_safe(to)}?{'&'.join(compose_url)}"
        # Collect command-line options.
        message_options = ["--compose", compose_url]
        if attach_path is not None:
            message_options.extend(
                ["--attach", self._encode_path(attach_path, "attachment")]
            )
        return message_options

    def _compose(
        self,
        prompt,
        to,
        subject,
        attach_path,
        mime_subtype,
        extension,
        body=None,
        from_=None,
    ):
        """See ExternalMailClient._compose."""
        if from_ is None:
            from_ = self.config.get("email")
        super()._compose(
            prompt, to, subject, attach_path, mime_subtype, extension, body, from_
        )


mail_client_registry.register("claws", Claws, help=Claws.__doc__)


class XDGEmail(BodyExternalMailClient):
    """XDG email integration.

    Uses the xdg-email command to invoke the user's preferred mail client
    as configured in their desktop environment.
    """

    _client_commands = ["xdg-email"]

    def _get_compose_commandline(self, to, subject, attach_path, body=None):
        """See ExternalMailClient._get_compose_commandline."""
        if not to:
            raise NoMailAddressSpecified()
        commandline = [self._encode_safe(to)]
        if subject is not None:
            commandline.extend(["--subject", self._encode_safe(subject)])
        if attach_path is not None:
            commandline.extend(
                ["--attach", self._encode_path(attach_path, "attachment")]
            )
        if body is not None:
            commandline.extend(["--body", self._encode_safe(body)])
        return commandline


mail_client_registry.register("xdg-email", XDGEmail, help=XDGEmail.__doc__)


class EmacsMail(ExternalMailClient):
    """Emacs-based mail client integration.

    Uses emacsclient to invoke Emacs for composing email messages. This works
    with all mail agents registered against `mail-user-agent` in Emacs.

    Requirements:
        - Emacs >= 22.1 (for -e/--eval support)
        - Properly configured `mail-user-agent` in Emacs

    This implementation works with all GNU Emacs mail user agents without
    needing separate client implementations for each one.
    """

    _client_commands = ["emacsclient"]

    def __init__(self, config):
        """Initialize the Emacs mail client.

        Args:
            config: Configuration object containing mail settings.
        """
        super().__init__(config)
        self.elisp_tmp_file = None

    def _prepare_send_function(self):
        """Write our wrapper function into a temporary file.

        This temporary file will be loaded at runtime in
        _get_compose_commandline function.

        This function does not remove the file.  That's a wanted
        behaviour since _get_compose_commandline won't run the send
        mail function directly but return the eligible command line.
        Removing our temporary file here would prevent our sendmail
        function to work.  (The file is deleted by some elisp code
        after being read by Emacs.)
        """
        _defun = rb"""(defun bzr-add-mime-att (file)
  "Attach FILE to a mail buffer as a MIME attachment."
  (let ((agent mail-user-agent))
    (if (and file (file-exists-p file))
        (cond
         ((eq agent 'sendmail-user-agent)
          (progn
            (mail-text)
            (newline)
            (if (functionp 'etach-attach)
              (etach-attach file)
              (mail-attach-file file))))
         ((or (eq agent 'message-user-agent)
              (eq agent 'gnus-user-agent)
              (eq agent 'mh-e-user-agent))
          (progn
            (mml-attach-file file "text/x-patch" "BZR merge" "inline")))
         ((eq agent 'mew-user-agent)
          (progn
            (mew-draft-prepare-attachments)
            (mew-attach-link file (file-name-nondirectory file))
            (let* ((nums (mew-syntax-nums))
                   (syntax (mew-syntax-get-entry mew-encode-syntax nums)))
              (mew-syntax-set-cd syntax "BZR merge")
              (mew-encode-syntax-print mew-encode-syntax))
            (mew-header-goto-body)))
         (t
          (message "Unhandled MUA, report it on bazaar@lists.canonical.com")))
      (error "File %s does not exist." file))))
"""

        fd, temp_file = tempfile.mkstemp(prefix="emacs-bzr-send-", suffix=".el")
        try:
            os.write(fd, _defun)
        finally:
            os.close(fd)  # Just close the handle but do not remove the file.
        return temp_file

    def _get_compose_commandline(self, to, subject, attach_path):
        commandline = ["--eval"]

        _to = "nil"
        _subject = "nil"

        if to is not None:
            _to = '"{}"'.format(self._encode_safe(to).replace('"', '\\"'))
        if subject is not None:
            _subject = '"{}"'.format(self._encode_safe(subject).replace('"', '\\"'))

        # Funcall the default mail composition function
        # This will work with any mail mode including default mail-mode
        # User must tweak mail-user-agent variable to tell what function
        # will be called inside compose-mail.
        mail_cmd = f"(compose-mail {_to} {_subject})"
        commandline.append(mail_cmd)

        # Try to attach a MIME attachment using our wrapper function
        if attach_path is not None:
            # Do not create a file if there is no attachment
            elisp = self._prepare_send_function()
            self.elisp_tmp_file = elisp
            lmmform = f'(load "{elisp}")'
            mmform = '(bzr-add-mime-att "{}")'.format(
                self._encode_path(attach_path, "attachment")
            )
            rmform = f'(delete-file "{elisp}")'
            commandline.append(lmmform)
            commandline.append(mmform)
            commandline.append(rmform)

        return commandline


mail_client_registry.register("emacsclient", EmacsMail, help=EmacsMail.__doc__)


class MAPIClient(BodyExternalMailClient):
    """Windows MAPI mail client integration.

    Uses the Windows MAPI (Messaging Application Programming Interface)
    to invoke the default mail client configured in Windows.
    """

    def _compose(
        self, prompt, to, subject, attach_path, mime_subtype, extension, body=None
    ):
        """See ExternalMailClient._compose.

        This implementation uses MAPI via the simplemapi ctypes wrapper
        """
        from .util import simplemapi

        try:
            simplemapi.SendMail(to or "", subject or "", body or "", attach_path)
        except simplemapi.MAPIError as e:
            if e.code != simplemapi.MAPI_USER_ABORT:
                raise MailClientNotFound(
                    ["MAPI supported mail client (error %d)" % (e.code,)]
                ) from e


mail_client_registry.register("mapi", MAPIClient, help=MAPIClient.__doc__)


class MailApp(BodyExternalMailClient):
    """MacOS Mail.app integration.

    Integrates with macOS Mail.app by generating and executing AppleScript
    code through osascript. This allows composing emails with attachments
    and body text.

    Note:
        We use AppleScript instead of appscript because appscript is not
        installed with the shipped Python installations. The AppleScript
        is generated and executed using osascript(1).
    """

    _client_commands = ["osascript"]

    def _get_compose_commandline(self, to, subject, attach_path, body=None, from_=None):
        """See ExternalMailClient._get_compose_commandline."""
        fd, self.temp_file = tempfile.mkstemp(prefix="bzr-send-", suffix=".scpt")
        try:
            os.write(fd, 'tell application "Mail"\n')
            os.write(fd, "set newMessage to make new outgoing message\n")
            os.write(fd, "tell newMessage\n")
            if to is not None:
                os.write(
                    fd,
                    'make new to recipient with properties {{address:"{}"}}\n'.format(
                        to
                    ),
                )
            if from_ is not None:
                # though from_ doesn't actually seem to be used
                os.write(fd, 'set sender to "{}"\n'.format(from_.replace('"', '\\"')))
            if subject is not None:
                os.write(
                    fd, 'set subject to "{}"\n'.format(subject.replace('"', '\\"'))
                )
            if body is not None:
                # FIXME: would be nice to prepend the body to the
                # existing content (e.g., preserve signature), but
                # can't seem to figure out the right applescript
                # incantation.
                os.write(
                    fd,
                    'set content to "{}\\n\n"\n'.format(
                        body.replace('"', '\\"').replace("\n", "\\n")
                    ),
                )

            if attach_path is not None:
                # FIXME: would be nice to first append a newline to
                # ensure the attachment is on a new paragraph, but
                # can't seem to figure out the right applescript
                # incantation.
                os.write(
                    fd,
                    "tell content to make new attachment"
                    ' with properties {{file name:"{}"}}'
                    " at after the last paragraph\n".format(
                        self._encode_path(attach_path, "attachment")
                    ),
                )
            os.write(fd, "set visible to true\n")
            os.write(fd, "end tell\n")
            os.write(fd, "end tell\n")
        finally:
            os.close(fd)  # Just close the handle but do not remove the file.
        return [self.temp_file]


mail_client_registry.register("mail.app", MailApp, help=MailApp.__doc__)


class DefaultMail(MailClient):
    """Default mail handling with fallback strategy.

    Attempts to use the platform's preferred mail client (XDGEmail on Unix-like
    systems, MAPIClient on Windows), and falls back to the Editor client if
    no external mail client is available.
    """

    supports_body = True

    def _mail_client(self):
        """Determine the preferred mail client for this platform."""
        if sys.platform == "win32":
            return MAPIClient(self.config)
        else:
            return XDGEmail(self.config)

    def compose(
        self,
        prompt,
        to,
        subject,
        attachment,
        mime_subtype,
        extension,
        basename=None,
        body=None,
    ):
        """See MailClient.compose."""
        try:
            return self._mail_client().compose(
                prompt, to, subject, attachment, mime_subtype, extension, basename, body
            )
        except MailClientNotFound:
            return Editor(self.config).compose(
                prompt, to, subject, attachment, mime_subtype, extension, body
            )

    def compose_merge_request(self, to, subject, directive, basename=None, body=None):
        """See MailClient.compose_merge_request."""
        try:
            return self._mail_client().compose_merge_request(
                to, subject, directive, basename=basename, body=body
            )
        except MailClientNotFound:
            return Editor(self.config).compose_merge_request(
                to, subject, directive, basename=basename, body=body
            )


mail_client_registry.register("default", DefaultMail, help=DefaultMail.__doc__)
mail_client_registry.default_key = "default"

opt_mail_client = _mod_config.RegistryOption(
    "mail_client", mail_client_registry, help="E-mail client to use.", invalid="error"
)
