# Copyright (C) 2011 Canonical Ltd
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

# The normalize function is taken from pygettext which is distributed
# with Python under the Python License, which is GPL compatible.

"""Extract docstrings from Bazaar commands.

This module only handles breezy objects that use strings not directly wrapped
by a gettext() call. To generate a complete translation template file, this
output needs to be combined with that of xgettext or a similar command for
extracting those strings, as is done in the bzr Makefile. Sorting the output
is also left to that stage of the process.
"""

import inspect
import os

import breezy

from . import commands as _mod_commands
from . import errors, help_topics, option
from . import plugin as _mod_plugin
from .i18n import gettext
from .trace import mutter, note


def _escape(s):
    s = (
        s.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
        .replace('"', '\\"')
    )
    return s


def _normalize(s):
    # This converts the various Python string types into a format that
    # is appropriate for .po files, namely much closer to C style.
    lines = s.split("\n")
    if len(lines) == 1:
        s = '"' + _escape(s) + '"'
    else:
        if not lines[-1]:
            del lines[-1]
            lines[-1] = lines[-1] + "\n"
        lineterm = '\\n"\n"'
        s = '""\n"' + lineterm.join(map(_escape, lines)) + '"'
    return s


def _parse_source(source_text, filename="<unknown>"):
    """Get object to lineno mappings from given source_text."""
    import ast

    cls_to_lineno = {}
    str_to_lineno = {}
    for node in ast.walk(ast.parse(source_text, filename)):
        # TODO: worry about duplicates?
        if isinstance(node, ast.ClassDef):
            # TODO: worry about nesting?
            cls_to_lineno[node.name] = node.lineno
        elif isinstance(node, ast.Str):
            # Python AST gives location of string literal as the line the
            # string terminates on. It's more useful to have the line the
            # string begins on. Unfortunately, counting back newlines is
            # only an approximation as the AST is ignorant of escaping.
            str_to_lineno[node.s] = node.lineno
    return cls_to_lineno, str_to_lineno


class _ModuleContext:
    """Record of the location within a source tree."""

    def __init__(self, path, lineno=1, _source_info=None):
        self.path = path
        self.lineno = lineno
        if _source_info is not None:
            self._cls_to_lineno, self._str_to_lineno = _source_info

    @classmethod
    def from_module(cls, module):
        """Get new context from module object and parse source for linenos."""
        sourcepath = inspect.getsourcefile(module)
        # TODO: fix this to do the right thing rather than rely on cwd
        relpath = os.path.relpath(sourcepath)
        return cls(
            relpath,
            _source_info=_parse_source(
                "".join(inspect.findsource(module)[0]), module.__file__
            ),
        )

    def from_class(self, cls):
        """Get new context with same details but lineno of class in source."""
        try:
            lineno = self._cls_to_lineno[cls.__name__]
        except (AttributeError, KeyError):
            mutter("Definition of %r not found in %r", cls, self.path)
            return self
        return self.__class__(
            self.path, lineno, (self._cls_to_lineno, self._str_to_lineno)
        )

    def from_string(self, string):
        """Get new context with same details but lineno of string in source."""
        try:
            lineno = self._str_to_lineno[string]
        except (AttributeError, KeyError):
            mutter("String %r not found in %r", string[:20], self.path)
            return self
        return self.__class__(
            self.path, lineno, (self._cls_to_lineno, self._str_to_lineno)
        )


class _PotExporter:
    """Write message details to output stream in .pot file format."""

    def __init__(self, outf, include_duplicates=False):
        self.outf = outf
        if include_duplicates:
            self._msgids = None
        else:
            self._msgids = set()
        self._module_contexts = {}

    def poentry(self, path, lineno, s, comment=None):
        if self._msgids is not None:
            if s in self._msgids:
                return
            self._msgids.add(s)
        comment = "" if comment is None else f"# {comment}\n"
        mutter("Exporting msg %r at line %d in %r", s[:20], lineno, path)
        line = f'#: {path}:{lineno}\n{comment}msgid {_normalize(s)}\nmsgstr ""\n\n'
        self.outf.write(line)

    def poentry_in_context(self, context, string, comment=None):
        context = context.from_string(string)
        self.poentry(context.path, context.lineno, string, comment)

    def poentry_per_paragraph(self, path, lineno, msgid, include=None):
        # TODO: How to split long help?
        paragraphs = msgid.split("\n\n")
        if include is not None:
            paragraphs = filter(include, paragraphs)
        for p in paragraphs:
            self.poentry(path, lineno, p)
            lineno += p.count("\n") + 2

    def get_context(self, obj):
        module = inspect.getmodule(obj)
        try:
            context = self._module_contexts[module.__name__]
        except KeyError:
            context = _ModuleContext.from_module(module)
            self._module_contexts[module.__name__] = context
        if inspect.isclass(obj):
            context = context.from_class(obj)
        return context


def _write_option(exporter, context, opt, note):
    if getattr(opt, "hidden", False):
        return
    optname = opt.name
    if getattr(opt, "title", None):
        exporter.poentry_in_context(context, opt.title, f"title of {optname!r} {note}")
    for name, _, _, helptxt in opt.iter_switches():
        if name != optname:
            if opt.is_hidden(name):
                continue
            name = "=".join([optname, name])
        if helptxt:
            exporter.poentry_in_context(context, helptxt, f"help of {name!r} {note}")


def _standard_options(exporter):
    OPTIONS = option.Option.OPTIONS
    context = exporter.get_context(option)
    for name in sorted(OPTIONS):
        opt = OPTIONS[name]
        _write_option(exporter, context.from_string(name), opt, "option")


def _command_options(exporter, context, cmd):
    note = f"option of {cmd.name()!r} command"
    for opt in cmd.takes_options:
        # String values in Command option lists are for global options
        if not isinstance(opt, str):
            _write_option(exporter, context, opt, note)


def _write_command_help(exporter, cmd):
    context = exporter.get_context(cmd.__class__)
    rawdoc = cmd.__doc__
    dcontext = context.from_string(rawdoc)
    doc = inspect.cleandoc(rawdoc)

    def exclude_usage(p):
        # ':Usage:' has special meaning in help topics.
        # This is usage example of command and should not be translated.
        if p.splitlines()[0] != ":Usage:":
            return True

    exporter.poentry_per_paragraph(dcontext.path, dcontext.lineno, doc, exclude_usage)
    _command_options(exporter, context, cmd)


def _command_helps(exporter, plugin_name=None):
    """Extract docstrings from path.

    This respects the Bazaar cmdtable/table convention and will
    only extract docstrings from functions mentioned in these tables.
    """
    # builtin commands
    for cmd_name in _mod_commands.builtin_command_names():
        command = _mod_commands.get_cmd_object(cmd_name, False)
        if command.hidden:
            continue
        if plugin_name is not None:
            # only export builtins if we are not exporting plugin commands
            continue
        note(gettext("Exporting messages from builtin command: %s"), cmd_name)
        _write_command_help(exporter, command)

    plugins = _mod_plugin.plugins()
    if plugin_name is not None and plugin_name not in plugins:
        raise errors.BzrError(gettext("Plugin {} is not loaded").format(plugin_name))
    core_plugins = {
        name for name in plugins if plugins[name].path().startswith(breezy.__path__[0])
    }
    # plugins
    for cmd_name in _mod_commands.plugin_command_names():
        command = _mod_commands.get_cmd_object(cmd_name, False)
        if command.hidden:
            continue
        if plugin_name is not None and command.plugin_name() != plugin_name:
            # if we are exporting plugin commands, skip plugins we have not
            # specified.
            continue
        if plugin_name is None and command.plugin_name() not in core_plugins:
            # skip non-core plugins
            # TODO: Support extracting from third party plugins.
            continue
        note(
            gettext("Exporting messages from plugin command: {0} in {1}").format(
                cmd_name, command.plugin_name()
            )
        )
        _write_command_help(exporter, command)


def _error_messages(exporter):
    """Extract fmt string from breezy.errors."""
    context = exporter.get_context(errors)
    base_klass = errors.BzrError
    for name in dir(errors):
        klass = getattr(errors, name)
        if not inspect.isclass(klass):
            continue
        if not issubclass(klass, base_klass):
            continue
        if klass is base_klass:
            continue
        if klass.internal_error:
            continue
        fmt = getattr(klass, "_fmt", None)
        if fmt:
            note(gettext("Exporting message from error: %s"), name)
            exporter.poentry_in_context(context, fmt)


def _help_topics(exporter):
    topic_registry = help_topics.topic_registry
    for key in topic_registry.keys():
        doc = topic_registry.get(key)
        if isinstance(doc, str):
            exporter.poentry_per_paragraph(
                "dummy/help_topics/" + key + "/detail.txt", 1, doc
            )
        elif callable(doc):  # help topics from files
            exporter.poentry_per_paragraph(
                "en/help_topics/" + key + ".txt", 1, doc(key)
            )
        summary = topic_registry.get_summary(key)
        if summary is not None:
            exporter.poentry("dummy/help_topics/" + key + "/summary.txt", 1, summary)


def export_pot(outf, plugin=None, include_duplicates=False):
    exporter = _PotExporter(outf, include_duplicates)
    if plugin is None:
        _standard_options(exporter)
        _command_helps(exporter)
        _error_messages(exporter)
        _help_topics(exporter)
    else:
        _command_helps(exporter, plugin)
