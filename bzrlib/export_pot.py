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
"""

import inspect
import os

from bzrlib import (
    commands as _mod_commands,
    errors,
    help_topics,
    plugin,
    )
from bzrlib.trace import (
    mutter,
    note,
    )


def _escape(s):
    s = (s.replace('\\', '\\\\')
        .replace('\n', '\\n')
        .replace('\r', '\\r')
        .replace('\t', '\\t')
        .replace('"', '\\"')
        )
    return s

def _normalize(s):
    # This converts the various Python string types into a format that
    # is appropriate for .po files, namely much closer to C style.
    lines = s.split('\n')
    if len(lines) == 1:
        s = '"' + _escape(s) + '"'
    else:
        if not lines[-1]:
            del lines[-1]
            lines[-1] = lines[-1] + '\n'
        lines = map(_escape, lines)
        lineterm = '\\n"\n"'
        s = '""\n"' + lineterm.join(lines) + '"'
    return s


_FOUND_MSGID = None # set by entry function.

def _poentry(outf, path, lineno, s, comment=None):
    if s in _FOUND_MSGID:
        return
    _FOUND_MSGID.add(s)
    if comment is None:
        comment = ''
    else:
        comment = "# %s\n" % comment
    mutter("Exporting msg %r at line %d in %r", s[:20], lineno, path)
    print >>outf, ('#: %s:%d\n' % (path, lineno) +
           comment+
           'msgid %s\n' % _normalize(s) +
           'msgstr ""\n')

def _poentry_per_paragraph(outf, path, lineno, msgid):
    paragraphs = msgid.split('\n\n')
    for p in paragraphs:
        _poentry(outf, path, lineno, p)
        lineno += p.count('\n') + 2

def _offset(src, doc, default):
    """Compute offset or issue a warning on stdout."""
    # Backslashes in doc appear doubled in src.
    end = src.find(doc.replace('\\', '\\\\'))
    if end == -1:
        return default
    else:
        return src.count('\n', 0, end)

def _standard_options(outf):
    from bzrlib.option import Option
    src = inspect.findsource(Option)[0]
    src = ''.join(src)
    path = 'bzrlib/option.py'

    for name in sorted(Option.OPTIONS.keys()):
        opt = Option.OPTIONS[name]
        if getattr(opt, 'hidden', False):
            continue
        if getattr(opt, 'title', None):
            lineno = _offset(src, opt.title, 0)
            _poentry(outf, path, lineno, opt.title,
                     'title of %r option' % name)
        if getattr(opt, 'help', None):
            lineno = _offset(src, opt.help, 0)
            _poentry(outf, path, lineno, opt.help,
                     'help of %r option' % name)

def _command_options(outf, path, cmd):
    src, default_lineno = inspect.findsource(cmd.__class__)
    src = ''.join(src)
    for opt in cmd.takes_options:
        if isinstance(opt, str):
            continue
        if getattr(opt, 'hidden', False):
            continue
        name = opt.name
        if getattr(opt, 'title', None):
            lineno = _offset(src, opt.title, default_lineno)
            _poentry(outf, path, lineno, opt.title,
                     'title of %r option of %r command' % (name, cmd.name()))
        if getattr(opt, 'help', None):
            lineno = _offset(src, opt.help, default_lineno)
            _poentry(outf, path, lineno, opt.help,
                     'help of %r option of %r command' % (name, cmd.name()))


def _write_command_help(outf, cmd_name, cmd):
    path = inspect.getfile(cmd.__class__)
    if path.endswith('.pyc'):
        path = path[:-1]
    path = os.path.relpath(path)
    lineno = inspect.findsource(cmd.__class__)[1]
    doc = inspect.getdoc(cmd)

    _poentry_per_paragraph(outf, path, lineno, doc)
    _command_options(outf, path, cmd)

def _command_helps(outf):
    """Extract docstrings from path.

    This respects the Bazaar cmdtable/table convention and will
    only extract docstrings from functions mentioned in these tables.
    """
    from glob import glob

    # builtin commands
    for cmd_name in _mod_commands.builtin_command_names():
        command = _mod_commands.get_cmd_object(cmd_name, False)
        if command.hidden:
            continue
        note("Exporting messages from builtin command: %s", cmd_name)
        _write_command_help(outf, cmd_name, command)

    plugin_path = plugin.get_core_plugin_path()
    core_plugins = glob(plugin_path + '/*/__init__.py')
    core_plugins = [os.path.basename(os.path.dirname(p))
                        for p in core_plugins]
    # core plugins
    for cmd_name in _mod_commands.plugin_command_names():
        command = _mod_commands.get_cmd_object(cmd_name, False)
        if command.hidden:
            continue
        if command.plugin_name() not in core_plugins:
            # skip non-core plugins
            # TODO: Support extracting from third party plugins.
            continue
        note("Exporting messages from plugin command: %s in %s",
             cmd_name, command.plugin_name())
        _write_command_help(outf, cmd_name, command)


def _error_messages(outf):
    """Extract fmt string from bzrlib.errors."""
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
            note("Exporting message from error: %s", name)
            _poentry(outf, 'bzrlib/errors.py',
                     inspect.findsource(klass)[1], fmt)

def _help_topics(outf):
    topic_registry = help_topics.topic_registry
    for key in topic_registry.keys():
        doc = topic_registry.get(key)
        if isinstance(doc, str):
            _poentry_per_paragraph(
                    outf,
                    'dummy/help_topics/'+key+'/detail.txt',
                    1, doc)

        summary = topic_registry.get_summary(key)
        if summary is not None:
            _poentry(outf, 'dummy/help_topics/'+key+'/summary.txt',
                     1, summary)

def export_pot(outf):
    global _FOUND_MSGID
    _FOUND_MSGID = set()
    _standard_options(outf)
    _command_helps(outf)
    _error_messages(outf)
    # disable exporting help topics until we decide  how to translate it.
    #_help_topics(outf)
