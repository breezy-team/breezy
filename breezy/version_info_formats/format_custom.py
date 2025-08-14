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
import contextlib

from breezy import errors
from breezy.version_info_formats import VersionInfoBuilder, create_date_str

from ..lazy_regex import lazy_compile
from ..revision import NULL_REVISION


class MissingTemplateVariable(errors.BzrError):
    """Exception raised when a template variable is not available.

    This error is raised when processing a template that references
    a variable that has not been defined.
    """

    _fmt = "Variable {%(name)s} is not available."

    def __init__(self, name):
        """Initialize MissingTemplateVariable exception.

        Args:
            name: The name of the missing template variable.
        """
        self.name = name


class NoTemplate(errors.BzrError):
    """Exception raised when no template is specified.

    This error is raised when attempting to generate output
    without having provided a template.
    """

    _fmt = "No template specified."


class Template:
    r"""A simple template engine.

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
    >>> print(list(t.process('{test}\\n')))
    ['xxx', '\n']
    >>> print(list(t.process('{test}\n')))
    ['xxx', '\n']
    """

    _tag_re = lazy_compile("{(\\w+)}")

    def __init__(self):
        """Initialize an empty Template instance."""
        self._data = {}

    def add(self, name, value):
        """Add a variable to the template.

        Args:
            name: The name of the variable to add.
            value: The value to assign to the variable.
        """
        self._data[name] = value

    def process(self, tpl):
        """Process a template string and substitute variables.

        Args:
            tpl: The template string containing {variable} placeholders.

        Yields:
            String segments of the processed template.

        Raises:
            MissingTemplateVariable: If a referenced variable is not defined.
        """
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
            except KeyError as err:
                raise MissingTemplateVariable(name) from err
            if not isinstance(data, str):
                data = str(data)
            yield data


class CustomVersionInfoBuilder(VersionInfoBuilder):
    """Create a version file based on a custom template."""

    def generate(self, to_file):
        """Generate version info based on the custom template.

        Args:
            to_file: File-like object to write the generated output to.

        Raises:
            NoTemplate: If no template has been specified.
        """
        if self._template is None:
            raise NoTemplate()

        info = Template()
        info.add("build_date", create_date_str())
        info.add("branch_nick", self._branch.nick)

        revision_id = self._get_revision_id()
        if revision_id == NULL_REVISION:
            info.add("revno", 0)
        else:
            with contextlib.suppress(errors.GhostRevisionsHaveNoRevno):
                info.add("revno", self._get_revno_str(revision_id))
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
