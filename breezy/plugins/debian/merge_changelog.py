#!/usr/bin/env python
# Copyright ? 2008 Canonical Ltd.
# Author: Scott James Remnant <scott@ubuntu.com>.
# Hacked up by: Bryce Harrington <bryce@ubuntu.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of version 3 of the GNU General Public License as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import errno
import logging
import os.path
import re
import subprocess
import tempfile

from ... import (
    merge,
    osutils,
)

# A logger in the 'bzr' hierarchy.  By default messages will be propagated to
# the standard bzr logger, but tests can easily intercept just this logger if
# they wish.
_logger = logging.getLogger(__name__)


class ChangeLogFileMerge(merge.ConfigurableFileMerger):
    name_prefix = "deb_changelog"
    default_files = ["debian/changelog"]

    def merge_text(self, params):
        return merge_changelog(params.this_lines, params.other_lines, params.base_lines)


def merge_changelog(this_lines, other_lines, base_lines=None):
    """Merge a changelog file."""
    # Write the BASE, THIS and OTHER versions to files in a temporary
    # directory, and use dpkg-mergechangelogs to merge them.
    if base_lines is None:
        base_lines = []
    with tempfile.TemporaryDirectory("deb_changelog_merge") as tmpdir:

        def writelines(filename, lines):
            with open(filename, "wb") as f:
                for line in lines:
                    f.write(line)

        base_filename = os.path.join(tmpdir, "changelog.base")
        this_filename = os.path.join(tmpdir, "changelog.this")
        other_filename = os.path.join(tmpdir, "changelog.other")
        writelines(base_filename, base_lines)
        writelines(this_filename, this_lines)
        writelines(other_filename, other_lines)
        try:
            proc = subprocess.Popen(
                ["dpkg-mergechangelogs", base_filename, this_filename, other_filename],  # noqa: S607
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as e:
            if e.errno == errno.ENOENT:
                # No dpkg-mergechangelogs command available
                return "not_applicable", ""
            raise
        stdout, stderr = proc.communicate()
        retcode = proc.returncode
        if stderr:
            # Relay the warning from dpkg-mergechangelogs to the user.  We
            # don't decorate the messages at all, as dpkg-mergechangelogs
            # warnings are already prefixed with "dpkg-mergechangelogs:
            # warning:" which makes the origin of the messages quite clear.
            encoding = osutils.get_user_encoding()
            # Errors are output using the locale, and log needs unicode.
            _logger.warning("%s", stderr.decode(encoding, "replace"))
        if retcode == 1:
            # dpkg-mergechangelogs reports a conflict.  Unfortunately it uses
            # slightly non-standard conflict markers (<http://pad.lv/815700>:
            # "<<<<<<" rather than "<<<<<<<", i.e. 6 chars instead of 7), so we
            # correct that here to make the results of this plugin as
            # consistent with regular bzr usage as possible.  Note that
            # conflict markers are never valid lines in a changelog file, so
            # it's reasonable for us to assume that any line that looks like a
            # conflict marker is a conflict marker (rather than valid content).
            # At worst a conflicted merge of an invalid changelog file that
            # already contained a non-standard conflict marker will have that
            # conflict marker made standard, which is more like a feature than
            # a bug!
            def replace_func(match_obj):
                match_text = match_obj.group(0)
                return match_text[0] * 7

            stdout = re.sub(b"(?m)^[<=>]{6}$", replace_func, stdout)
            return "conflicted", stdout.splitlines(True)
        elif retcode != 0:
            # dpkg-mergechangelogs exited with an error. There is probably no
            # output at all, but regardless the merge should fall back to
            # another method.
            _logger.warning("dpkg-mergechangelogs failed with status %d", retcode)
            return "not_applicable", stdout.splitlines(True)
        else:
            return "success", stdout.splitlines(True)
