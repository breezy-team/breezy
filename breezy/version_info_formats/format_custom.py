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

"""A generator which creates a template-based output from the current
tree info.
"""

import codecs

from breezy import errors
from breezy.lazy_regex import lazy_compile
from breezy.revision import NULL_REVISION
from breezy.version_info_formats import VersionInfoBuilder, create_date_str


class MissingTemplateVariable(errors.BzrError):
    _fmt = "Variable {%(name)s} is not available."

    def __init__(self, name):
        self.name = name


class NoTemplate(errors.BzrError):
    _fmt = "No template specified."


class Template:
    """A simple template engine.

    >>> t = Template()
    >>> t.add('test', 'xxx')
    >>> print(list(t.process('{test}')))
    ['xxx']
    >>> print(list(t.process('{test} test')))
    ['xxx', ' test']
    >>> print(list(t.process('test {test}')))
    ['test ', 'xxx']
    >>> print(list(t.process('test {test} test')))
    ['test ', 'xxx', ' test']
    >>> print(list(t.process('{test}\\\\n')))
    ['xxx', '\\n']
    >>> print(list(t.process('{test}\\n')))
    ['xxx', '\\n']
    """

    _tag_re = lazy_compile("{(\\w+)}")

    def __init__(self):
        self._data = {}

    def add(self, name, value):
        self._data[name] = value

    def process(self, tpl):
        unicode_escape = codecs.getdecoder("unicode_escape")
        tpl = unicode_escape(tpl)[0]
        pos = 0
        while True:
            match = self._tag_re.search(tpl, pos)
            if not match:
                if pos < len(tpl):
                    yield tpl[pos:]
                break
            start, end = match.span()
            if start > 0:
                yield tpl[pos:start]
            pos = end
            name = match.group(1)
            try:
                data = self._data[name]
            except KeyError:
                raise MissingTemplateVariable(name)
            if not isinstance(data, str):
                data = str(data)
            yield data


class CustomVersionInfoBuilder(VersionInfoBuilder):
    """Create a version file based on a custom template."""

    def generate(self, to_file):
        if self._template is None:
            raise NoTemplate()

        info = Template()
        info.add("build_date", create_date_str())
        info.add("branch_nick", self._branch.nick)

        revision_id = self._get_revision_id()
        if revision_id == NULL_REVISION:
            info.add("revno", 0)
        else:
            try:
                info.add("revno", self._get_revno_str(revision_id))
            except errors.GhostRevisionsHaveNoRevno:
                pass
            info.add("revision_id", revision_id.decode("utf-8"))
            rev = self._branch.repository.get_revision(revision_id)
            info.add("date", create_date_str(rev.timestamp, rev.timezone))

        if self._check:
            self._extract_file_revisions()

        if self._check:
            if self._clean:
                info.add("clean", 1)
            else:
                info.add("clean", 0)

        to_file.writelines(info.process(self._template))
