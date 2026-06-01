# Copyright (C) 2005 Canonical Ltd
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

"""Documentation generation."""

import datetime
import os


def get_module(target):
    """Import and return a documentation generation module for the given target.

    Args:
        target: The target type for documentation generation (e.g., 'commands',
            'options'). This will be used to construct the module name
            'breezy.doc_generate.autodoc_{target}'.

    Returns:
        The imported module object for the specified documentation target.

    Raises:
        ImportError: If the autodoc module for the target doesn't exist.
        AttributeError: If module components cannot be found during traversal.
    """
    mod_name = f"breezy.doc_generate.autodoc_{target}"
    mod = __import__(mod_name)
    components = mod_name.split(".")
    for comp in components[1:]:
        mod = getattr(mod, comp)
    return mod


def get_autodoc_datetime():
    """Obtain the datetime to use for timestamps embedded in generated docs.

    :return: A `datetime` object
    """
    try:
        return datetime.datetime.fromtimestamp(
            int(os.environ["SOURCE_DATE_EPOCH"]), datetime.UTC
        )
    except (KeyError, ValueError):
        return datetime.datetime.utcnow()
