# Copyright (C) 2005-2011 Canonical Ltd
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

"""Commit message editor support."""

import codecs
import contextlib
import os
import sys
from io import BytesIO, StringIO
from subprocess import call

from . import bedding, cmdline, config, osutils, trace, transport, ui
from .errors import BzrError
from .hooks import Hooks


class BadCommitMessageEncoding(BzrError):
    """Exception raised when commit message contains unsupported characters.

    This error occurs when the commit message contains characters that cannot
    be encoded using the current system's encoding.
    """

    _fmt = (
        "The specified commit message contains characters unsupported by "
        "the current encoding."
    )


def _get_editor():
    """Return sequence of possible editor binaries for the current platform."""
    with contextlib.suppress(KeyError):
        yield os.environ["BRZ_EDITOR"], "$BRZ_EDITOR"

    e = config.GlobalStack().get("editor")
    if e is not None:
        yield e, bedding.config_path()

    for varname in "VISUAL", "EDITOR":
        if varname in os.environ:
            yield os.environ[varname], "$" + varname

    if sys.platform == "win32":
        for editor in "wordpad.exe", "notepad.exe":
            yield editor, None
    else:
        for editor in ["/usr/bin/editor", "vi", "pico", "nano", "joe"]:
            yield editor, None


def _run_editor(filename):
    """Try to execute an editor to edit the commit message."""
    for candidate, candidate_source in _get_editor():
        edargs = cmdline.split(candidate)
        try:
            x = call(edargs + [filename])
        except OSError as e:
            if candidate_source is not None:
                # We tried this editor because some user configuration (an
                # environment variable or config file) said to try it.  Let
                # the user know their configuration is broken.
                trace.warning(
                    f'Could not start editor "{candidate}" (specified by {candidate_source}): {e!s}\n'
                )
            continue
            raise
        if x == 0:
            return True
        elif x == 127:
            continue
        else:
            break
    raise BzrError(
        "Could not start any editor.\nPlease specify one with:\n"
        " - $BRZ_EDITOR\n - editor=/some/path in {}\n"
        " - $VISUAL\n - $EDITOR".format(bedding.config_path())
    )


DEFAULT_IGNORE_LINE = "{bar} {msg} {bar}".format(
    bar="-" * 14, msg="This line and the following will be ignored"
)


def edit_commit_message(infotext, ignoreline=DEFAULT_IGNORE_LINE, start_message=None):
    """Let the user edit a commit message in a temp file.

    This is run if they don't give a message or
    message-containing file on the command line.

    :param infotext:    Text to be displayed at bottom of message
                        for the user's reference;
                        currently similar to 'bzr status'.

    :param ignoreline:  The separator to use above the infotext.

    :param start_message:   The text to place above the separator, if any.
                            This will not be removed from the message
                            after the user has edited it.

    :return:    commit message or None.
    """
    if start_message is not None:
        start_message = start_message.encode(osutils.get_user_encoding())
    infotext = infotext.encode(osutils.get_user_encoding(), "replace")
    return edit_commit_message_encoded(infotext, ignoreline, start_message)


def edit_commit_message_encoded(
    infotext, ignoreline=DEFAULT_IGNORE_LINE, start_message=None
):
    """Let the user edit a commit message in a temp file.

    This is run if they don't give a message or
    message-containing file on the command line.

    :param infotext:    Text to be displayed at bottom of message
                        for the user's reference;
                        currently similar to 'bzr status'.
                        The string is already encoded

    :param ignoreline:  The separator to use above the infotext.

    :param start_message:   The text to place above the separator, if any.
                            This will not be removed from the message
                            after the user has edited it.
                            The string is already encoded

    :return:    commit message or None.
    """
    msgfilename = None
    try:
        msgfilename, hasinfo = _create_temp_file_with_commit_template(
            infotext, ignoreline, start_message
        )
        if not msgfilename:
            return None
        basename = osutils.basename(msgfilename)
        msg_transport = transport.get_transport_from_path(osutils.dirname(msgfilename))
        reference_content = msg_transport.get_bytes(basename)
        if not _run_editor(msgfilename):
            return None
        edited_content = msg_transport.get_bytes(basename)
        if edited_content == reference_content and not ui.ui_factory.confirm_action(
            "Commit message was not edited, use anyway",
            "breezy.msgeditor.unchanged",
            {},
        ):
            # Returning "" makes cmd_commit raise 'empty commit message
            # specified' which is a reasonable error, given the user has
            # rejected using the unedited template.
            return ""
        started = False
        msg = []
        lastline, nlines = 0, 0
        with codecs.open(
            msgfilename, mode="rb", encoding=osutils.get_user_encoding()
        ) as f:
            try:
                for line in f:
                    stripped_line = line.strip()
                    # strip empty line before the log message starts
                    if not started:
                        if stripped_line != "":
                            started = True
                        else:
                            continue
                    # check for the ignore line only if there
                    # is additional information at the end
                    if hasinfo and stripped_line == ignoreline:
                        break
                    nlines += 1
                    # keep track of the last line that had some content
                    if stripped_line != "":
                        lastline = nlines
                    msg.append(line)
            except UnicodeDecodeError as e:
                raise BadCommitMessageEncoding() from e

        if len(msg) == 0:
            return ""
        # delete empty lines at the end
        del msg[lastline:]
        # add a newline at the end, if needed
        if not msg[-1].endswith("\n"):
            return f"{''.join(msg)}\n"
        else:
            return "".join(msg)
    finally:
        # delete the msg file in any case
        if msgfilename is not None:
            try:
                os.unlink(msgfilename)
            except OSError as e:
                trace.warning("failed to unlink %s: %s; ignored", msgfilename, e)


def _create_temp_file_with_commit_template(
    infotext, ignoreline=DEFAULT_IGNORE_LINE, start_message=None, tmpdir=None
):
    """Create temp file and write commit template in it.

    :param infotext: Text to be displayed at bottom of message for the
        user's reference; currently similar to 'bzr status'.  The text is
        already encoded.

    :param ignoreline:  The separator to use above the infotext.

    :param start_message: The text to place above the separator, if any.
        This will not be removed from the message after the user has edited
        it.  The string is already encoded

    :return:    2-tuple (temp file name, hasinfo)
    """
    import tempfile

    tmp_fileno, msgfilename = tempfile.mkstemp(prefix="bzr_log.", dir=tmpdir, text=True)
    with os.fdopen(tmp_fileno, "wb") as msgfile:
        if start_message is not None:
            msgfile.write(b"%s\n" % start_message)

        if infotext is not None and infotext != "":
            hasinfo = True
            trailer = b"\n\n%s\n\n%s" % (
                ignoreline.encode(osutils.get_user_encoding()),
                infotext,
            )
            msgfile.write(trailer)
        else:
            hasinfo = False

    return (msgfilename, hasinfo)


def make_commit_message_template(working_tree, specific_files):
    """Prepare a template file for a commit into a branch.

    Returns a unicode string containing the template.
    """
    # TODO: make provision for this to be overridden or modified by a hook
    #
    # TODO: Rather than running the status command, should prepare a draft of
    # the revision to be committed, then pause and ask the user to
    # confirm/write a message.
    from .status import show_tree_status

    status_tmp = StringIO()
    show_tree_status(
        working_tree, specific_files=specific_files, to_file=status_tmp, verbose=True
    )
    return status_tmp.getvalue()


def make_commit_message_template_encoded(
    working_tree, specific_files, diff=None, output_encoding="utf-8"
):
    """Prepare a template file for a commit into a branch.

    Returns an encoded string.
    """
    # TODO: make provision for this to be overridden or modified by a hook
    #
    # TODO: Rather than running the status command, should prepare a draft of
    # the revision to be committed, then pause and ask the user to
    # confirm/write a message.
    from .diff import show_diff_trees

    template = make_commit_message_template(working_tree, specific_files)
    template = template.encode(output_encoding, "replace")

    if diff:
        stream = BytesIO()
        show_diff_trees(
            working_tree.basis_tree(),
            working_tree,
            stream,
            specific_files,
            path_encoding=output_encoding,
        )
        template = template + b"\n" + stream.getvalue()

    return template


class MessageEditorHooks(Hooks):
    """A dictionary mapping hook name to a list of callables for message editor hooks.

    e.g. ['commit_message_template'] is the list of items to be called to
    generate a commit message template
    """

    def __init__(self):
        """Create the default hooks.

        These are all empty initially.
        """
        Hooks.__init__(self, "breezy.msgeditor", "hooks")
        self.add_hook(
            "set_commit_message",
            "Set a fixed commit message. "
            "set_commit_message is called with the "
            "breezy.commit.Commit object (so you can also change e.g. "
            "revision properties by editing commit.builder._revprops) and the "
            "message so far. set_commit_message must return the message to "
            "use or None if it should use the message editor as normal.",
            (2, 4),
        )
        self.add_hook(
            "commit_message_template",
            "Called when a commit message is being generated. "
            "commit_message_template is called with the breezy.commit.Commit "
            "object and the message that is known so far. "
            "commit_message_template must return a new message to use (which "
            "could be the same as it was given). When there are multiple "
            "hooks registered for commit_message_template, they are chained "
            "with the result from the first passed into the second, and so "
            "on.",
            (1, 10),
        )


hooks = MessageEditorHooks()


def set_commit_message(commit, start_message=None):
    """Sets the commit message.

    :param commit: Commit object for the active commit.
    :return: The commit message or None to continue using the message editor.
    """
    start_message = None
    for hook in hooks["set_commit_message"]:
        start_message = hook(commit, start_message)
    return start_message


def generate_commit_message_template(commit, start_message=None):
    """Generate a commit message template.

    :param commit: Commit object for the active commit.
    :param start_message: Message to start with.
    :return: A start commit message or None for an empty start commit message.
    """
    start_message = None
    for hook in hooks["commit_message_template"]:
        start_message = hook(commit, start_message)
    return start_message
