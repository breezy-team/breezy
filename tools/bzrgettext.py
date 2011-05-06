#!/usr/bin/env python
#
# bzrgettext - extract docstrings for Bazaar commands
#
# Copyright 2009 Matt Mackall <mpm@selenic.com> and others
# Copyright 2011 Canonical Ltd
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

# This script is copied from mercurial/i18n/hggettext and modified
# for Bazaar.

# The normalize function is taken from pygettext which is distributed
# with Python under the Python License, which is GPL compatible.


"""Extract docstrings from Bazaar commands.
"""

import os, sys, inspect


def escape(s):
    s = (s.replace('\\', '\\\\')
        .replace('\n', '\\n')
        .replace('\r', '\\r')
        .replace('\t', '\\t')
        .replace('"', '\\"')
        )
    return s


def normalize(s):
    # This converts the various Python string types into a format that
    # is appropriate for .po files, namely much closer to C style.
    lines = s.split('\n')
    if len(lines) == 1:
        s = '"' + escape(s) + '"'
    else:
        if not lines[-1]:
            del lines[-1]
            lines[-1] = lines[-1] + '\n'
        lines = map(escape, lines)
        lineterm = '\\n"\n"'
        s = '""\n"' + lineterm.join(lines) + '"'
    return s


MSGID_FOUND = set()

def poentry(path, lineno, s, comment=None):
    if s in MSGID_FOUND:
        return
    MSGID_FOUND.add(s)
    if comment is None:
        comment = ''
    else:
        comment = "# %s\n" % comment
    print ('#: %s:%d\n' % (path, lineno) +
           comment+
           'msgid %s\n' % normalize(s) +
           'msgstr ""\n')

def poentry_per_paragraph(path, lineno, msgid):
    paragraphs = msgid.split('\n\n')
    for p in paragraphs:
        poentry(path, lineno, p)
        lineno += p.count('\n') + 2

def offset(src, doc, name, default):
    """Compute offset or issue a warning on stdout."""
    # Backslashes in doc appear doubled in src.
    end = src.find(doc.replace('\\', '\\\\'))
    if end == -1:
        # This can happen if the docstring contains unnecessary escape
        # sequences such as \" in a triple-quoted string. The problem
        # is that \" is turned into " and so doc wont appear in src.
        sys.stderr.write("warning: unknown offset in %s, assuming %d lines\n"
                         % (name, default))
        return default
    else:
        return src.count('\n', 0, end)


def importpath(path):
    """Import a path like foo/bar/baz.py and return the baz module."""
    if path.endswith('.py'):
        path = path[:-3]
    if path.endswith('/__init__'):
        path = path[:-9]
    path = path.replace('/', '.')
    mod = __import__(path)
    for comp in path.split('.')[1:]:
        mod = getattr(mod, comp)
    return mod

def options(path, lineno, cmdklass):
    cmd = cmdklass()
    for name, opt in cmd.options().iteritems():
        poentry(path, lineno, opt.help,
                "help of '%s' option of '%s' command" % (name, cmd.name()))


def docstrings(path):
    """Extract docstrings from path.

    This respects the Bazaar cmdtable/table convention and will
    only extract docstrings from functions mentioned in these tables.
    """
    from bzrlib.commands import Command as cmd_klass
    try:
        mod = importpath(path)
    except Exception:
        # some module raises exception (ex. bzrlib.transport.ftp._gssapi
        return
    for name in dir(mod):
        if not name.startswith('cmd_'):
            continue
        obj = getattr(mod, name)
        try:
            doc = obj.__doc__
            if doc:
                doc = inspect.cleandoc(doc)
            else:
                continue
        except AttributeError:
            continue
        if (inspect.isclass(obj) and issubclass(obj, cmd_klass)
                and not obj is cmd_klass):
            lineno = inspect.findsource(obj)[1]
            poentry_per_paragraph(path, lineno, doc)
            options(path, lineno, obj)

def bzrerrors():
    """Extract fmt string from bzrlib.errors."""
    from bzrlib import errors
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
            poentry('bzrlib/erros.py', inspect.findsource(klass)[1], fmt)


def rawtext(path):
    src = open(path).read()
    poentry_per_paragraph(path, 1, src)


if __name__ == "__main__":
    # It is very important that we import the Bazaar modules from
    # the source tree where bzrgettext is executed. Otherwise we might
    # accidentally import and extract strings from a Bazaar
    # installation mentioned in PYTHONPATH.
    sys.path.insert(0, os.getcwd())
    import bzrlib.lazy_import
    for path in sys.argv[1:]:
        if path.endswith('.txt'):
            rawtext(path)
        else:
            docstrings(path)
    bzrerrors()
