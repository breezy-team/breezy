#    dep3.py -- DEP-3 compatible patch formatting
#    Copyright (C) 2011 Canonical Ltd.
#
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

"""DEP-3 style patch formatting."""

from bzrlib import diff

import time


def dep3_patch_header(f, description=None, bugs=None, authors=None,
        revision_id=None, last_update=None):
    """Write a DEP3 patch header.

    :param f: File-like object to write to
    :param description: Description of the patch
    :param bugs: Set of bugs fixed in this patch
    :param authors: Authors of the patch
    :param revision_id: Relevant bzr revision id
    :param last_update: Last update timestamp
    """
    # FIXME: Description
    # FIXME: Origin
    # FIXME: Bug- or Bug:
    # FIXME: Forwarded
    if authors:
        for author in authors:
            f.write("Author: %s\n" % author)
    if last_update is not None:
        f.write("Last-Update: %s\n" % time.strftime("%Y-%m-%d", time.gmtime(last_update)))
    # FIXME: Applied-Upstream
    if revision_id is not None:
        f.write("X-Bzr-Revision-Id: %s\n" % revision_id)
    if description is not None:
        f.write("Description: %s\n" % description)
    f.write("\n")


def dep3_patch(f, old_tree, new_tree, bugs=None):
    """Write a DEP-3 compliant patch.

    """
    dep3_patch_header(f)
    diff.show_diff_trees(old_tree, new_tree, f, old_label='old/', new_label='new/')
