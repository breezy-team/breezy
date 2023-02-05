# Copyright (C) 2008, 2010 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
"""Classify a commit based on the types of files it changed."""

import os.path

from ... import urlutils
from ...trace import mutter


def classify_filename(name):
    """Classify a file based on its name.

    :param name: File path.
    :return: One of code, documentation, translation or art.
        None if determining the file type failed.
    """
    # FIXME: Use mime types? Ohcount?
    # TODO: It will be better move those filters to properties file
    # and have possibility to determining own types !?
    extension = os.path.splitext(name)[1]
    if extension in (".c", ".h", ".py", ".cpp", ".rb", ".pm", ".pl", ".ac",
                     ".java", ".cc", ".proto", ".yy", ".l"):
        return "code"
    if extension in (".html", ".xml", ".txt", ".rst", ".TODO"):
        return "documentation"
    if extension in (".po",):
        return "translation"
    if extension in (".svg", ".png", ".jpg"):
        return "art"
    if not extension:
        basename = urlutils.basename(name)
        if basename in ("README", "NEWS", "TODO",
                        "AUTHORS", "COPYING"):
            return "documentation"
        if basename in ("Makefile",):
            return "code"

    mutter("don't know how to classify %s", name)
    return None


def classify_delta(delta):
    """Determine what sort of changes a delta contains.

    :param delta: A TreeDelta to inspect
    :return: List with classes found (see classify_filename)
    """
    # TODO: This is inaccurate, since it doesn't look at the
    # number of lines changed in a file.
    types = []
    for d in delta.added + delta.modified:
        types.append(classify_filename(d.path[1] or d.path[0]))
    return types
