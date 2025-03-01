# Copyright (C) 2006 Aaron Bentley
# <aaron@aaronbentley.com>
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

import re
from os.path import expanduser

import patiencediff

from . import terminal
from .patches import (
    ContextLine,
    Hunk,
    HunkLine,
    InsertLine,
    RemoveLine,
    hunk_from_header,
)

GLOBAL_COLORDIFFRC = "/etc/colordiffrc"


class LineParser:
    def parse_line(self, line):
        if line.startswith(b"@"):
            return hunk_from_header(line)
        elif line.startswith(b"+"):
            return InsertLine(line[1:])
        elif line.startswith(b"-"):
            return RemoveLine(line[1:])
        elif line.startswith(b" "):
            return ContextLine(line[1:])
        else:
            return line


def read_colordiffrc(path):
    colors = {}
    with open(path) as f:
        for line in f.readlines():
            try:
                key, val = line.split("=")
            except ValueError:
                continue

            key = key.strip()
            val = val.strip()

            tmp = val
            if val.startswith("dark"):
                tmp = val[4:]

            if tmp not in terminal.colors:
                continue

            colors[key] = val
    return colors


class DiffWriter:
    def __init__(self, target, check_style=False):
        self.target = target
        self.lp = LineParser()
        self.chunks = []
        self.colors = {
            "metaline": "darkyellow",
            "plain": "darkwhite",
            "newtext": "darkblue",
            "oldtext": "darkred",
            "diffstuff": "darkgreen",
            "trailingspace": "yellow",
            "leadingtabs": "magenta",
            "longline": "cyan",
        }
        if GLOBAL_COLORDIFFRC is not None:
            self._read_colordiffrc(GLOBAL_COLORDIFFRC)
        self._read_colordiffrc(expanduser("~/.colordiffrc"))
        self.added_leading_tabs = 0
        self.added_trailing_whitespace = 0
        self.spurious_whitespace = 0
        self.long_lines = 0
        self.max_line_len = 79
        self._new_lines = []
        self._old_lines = []
        self.check_style = check_style

    def _read_colordiffrc(self, path):
        try:
            self.colors.update(read_colordiffrc(path))
        except OSError:
            pass

    def colorstring(self, type, item, bad_ws_match):
        color = self.colors[type]
        if color is not None:
            if self.check_style and bad_ws_match:
                # highlight were needed
                item.contents = "".join(
                    terminal.colorstring(txt, color, bcol)
                    for txt, bcol in (
                        (
                            bad_ws_match.group(1).expandtabs(),
                            self.colors["leadingtabs"],
                        ),
                        (bad_ws_match.group(2)[0 : self.max_line_len], None),
                        (
                            bad_ws_match.group(2)[self.max_line_len :],
                            self.colors["longline"],
                        ),
                        (bad_ws_match.group(3), self.colors["trailingspace"]),
                    )
                ) + bad_ws_match.group(4)
            if not isinstance(item, bytes):
                item = item.as_bytes()
            string = terminal.colorstring(item, color)
        else:
            string = str(item)
        self.target.write(string)

    def write(self, text):
        newstuff = text.split(b"\n")
        for newchunk in newstuff[:-1]:
            self._writeline(b"".join(self.chunks + [newchunk, b"\n"]))
            self.chunks = []
        self.chunks = [newstuff[-1]]

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def _writeline(self, line):
        item = self.lp.parse_line(line)
        bad_ws_match = None
        if isinstance(item, Hunk):
            line_class = "diffstuff"
            self._analyse_old_new()
        elif isinstance(item, HunkLine):
            bad_ws_match = re.match(rb"^([\t]*)(.*?)([\t ]*)(\r?\n)$", item.contents)
            has_leading_tabs = bool(bad_ws_match.group(1))
            has_trailing_whitespace = bool(bad_ws_match.group(3))
            if isinstance(item, InsertLine):
                if has_leading_tabs:
                    self.added_leading_tabs += 1
                if has_trailing_whitespace:
                    self.added_trailing_whitespace += 1
                if len(
                    bad_ws_match.group(2)
                ) > self.max_line_len and not item.contents.startswith(b"++ "):
                    self.long_lines += 1
                line_class = "newtext"
                self._new_lines.append(item)
            elif isinstance(item, RemoveLine):
                line_class = "oldtext"
                self._old_lines.append(item)
            else:
                line_class = "plain"
        elif isinstance(item, bytes) and item.startswith(b"==="):
            line_class = "metaline"
            self._analyse_old_new()
        else:
            line_class = "plain"
            self._analyse_old_new()
        self.colorstring(line_class, item, bad_ws_match)

    def flush(self):
        self.target.flush()

    @staticmethod
    def _matched_lines(old, new):
        matcher = patiencediff.PatienceSequenceMatcher(None, old, new)
        matched_lines = sum(n for i, j, n in matcher.get_matching_blocks())
        return matched_lines

    def _analyse_old_new(self):
        if (self._old_lines, self._new_lines) == ([], []):
            return
        if not self.check_style:
            return
        old = [l.contents for l in self._old_lines]
        new = [l.contents for l in self._new_lines]
        ws_matched = self._matched_lines(old, new)
        old = [l.rstrip() for l in old]
        new = [l.rstrip() for l in new]
        no_ws_matched = self._matched_lines(old, new)
        if no_ws_matched < ws_matched:
            raise AssertionError
        if no_ws_matched > ws_matched:
            self.spurious_whitespace += no_ws_matched - ws_matched
            self.target.write("^ Spurious whitespace change above.\n")
        self._old_lines, self._new_lines = ([], [])
