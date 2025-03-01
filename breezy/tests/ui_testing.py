# Copyright (C) 2005-2016 Canonical Ltd, 2017 Bazaar developers
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

import io

from .. import ui
from ..ui import text as ui_text


class StringIOWithEncoding(io.StringIO):
    encoding = "ascii"

    def write(self, string):
        if isinstance(string, bytes):
            string = string.decode(self.encoding)
        io.StringIO.write(self, string)


class BytesIOWithEncoding(io.BytesIO):
    encoding = "ascii"


class StringIOAsTTY(StringIOWithEncoding):
    """A helper class which makes a StringIO look like a terminal."""

    def isatty(self):
        return True


class TextUIFactory(ui_text.TextUIFactory):
    def __init__(self, stdin=None, stdout=None, stderr=None):
        if isinstance(stdin, bytes):
            stdin = stdin.decode()
        if isinstance(stdin, str):
            stdin = StringIOWithEncoding(stdin)
        if stdout is None:
            stdout = StringIOWithEncoding()
        if stderr is None:
            stderr = StringIOWithEncoding()
        super().__init__(stdin, stdout, stderr)

    def _setup_streams(self):
        self.raw_stdin = self.stdin
        self.raw_stdout = self.stdout
        self.raw_stderr = self.stderr


class TestUIFactory(TextUIFactory):
    """A UI Factory for testing.

    Hide the progress bar but emit note()s.
    Redirect stdin.
    Allows get_password to be tested without real tty attached.

    See also CannedInputUIFactory which lets you provide programmatic input in
    a structured way.
    """

    # TODO: Capture progress events at the model level and allow them to be
    # observed by tests that care.
    #
    # XXX: Should probably unify more with CannedInputUIFactory or a
    # particular configuration of TextUIFactory, or otherwise have a clearer
    # idea of how they're supposed to be different.
    # See https://bugs.launchpad.net/bzr/+bug/408213

    def get_non_echoed_password(self):
        """Get password from stdin without trying to handle the echo mode."""
        password = self.stdin.readline()
        if not password:
            raise EOFError
        if password[-1] == "\n":
            password = password[:-1]
        return password

    def make_progress_view(self):
        return ui.NullProgressView()
