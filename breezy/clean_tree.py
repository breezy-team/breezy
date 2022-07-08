# Copyright (C) 2009, 2010 Canonical Ltd
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

import errno
import os
import shutil

from . import (
    controldir,
    errors,
    ui,
    )
from .osutils import isdir
from .trace import note
from .workingtree import WorkingTree
from .i18n import gettext


def is_detritus(subp):
    """Return True if the supplied path is detritus, False otherwise"""
    return subp.endswith('.THIS') or subp.endswith('.BASE') or\
        subp.endswith('.OTHER') or subp.endswith('~') or subp.endswith('.tmp')


def iter_deletables(tree, unknown=False, ignored=False, detritus=False):
    """Iterate through files that may be deleted"""
    for subp in tree.extras():
        if detritus and is_detritus(subp):
            yield tree.abspath(subp), subp
            continue
        if tree.is_ignored(subp):
            if ignored:
                yield tree.abspath(subp), subp
        else:
            if unknown:
                yield tree.abspath(subp), subp


def clean_tree(directory, unknown=False, ignored=False, detritus=False,
               dry_run=False, no_prompt=False):
    """Remove files in the specified classes from the tree"""
    tree = WorkingTree.open_containing(directory)[0]
    with tree.lock_read():
        deletables = list(iter_deletables(tree, unknown=unknown,
                                          ignored=ignored, detritus=detritus))
        deletables = _filter_out_nested_controldirs(deletables)
        if len(deletables) == 0:
            note(gettext('Nothing to delete.'))
            return 0
        if not no_prompt:
            for path, subp in deletables:
                ui.ui_factory.note(subp)
            prompt = gettext('Are you sure you wish to delete these')
            if not ui.ui_factory.get_boolean(prompt):
                ui.ui_factory.note(gettext('Canceled'))
                return 0
        delete_items(deletables, dry_run=dry_run)


def _filter_out_nested_controldirs(deletables):
    result = []
    for path, subp in deletables:
        # bzr won't recurse into unknowns/ignored directories by default
        # so we don't pay a penalty for checking subdirs of path for nested
        # control dir.
        # That said we won't detect the branch in the subdir of non-branch
        # directory and therefore delete it. (worth to FIXME?)
        if isdir(path):
            try:
                controldir.ControlDir.open(path)
            except errors.NotBranchError:
                result.append((path, subp))
            else:
                # TODO may be we need to notify user about skipped directories?
                pass
        else:
            result.append((path, subp))
    return result


def delete_items(deletables, dry_run=False):
    """Delete files in the deletables iterable"""
    def onerror(function, path, excinfo):
        """Show warning for errors seen by rmtree.
        """
        # Handle only permission error while removing files.
        # Other errors are re-raised.
        if function is not os.remove or excinfo[1].errno != errno.EACCES:
            raise
        ui.ui_factory.show_warning(gettext('unable to remove %s') % path)
    has_deleted = False
    for path, subp in deletables:
        if not has_deleted:
            note(gettext("deleting paths:"))
            has_deleted = True
        if not dry_run:
            if isdir(path):
                shutil.rmtree(path, onerror=onerror)
            else:
                try:
                    os.unlink(path)
                    note('  ' + subp)
                except OSError as e:
                    # We handle only permission error here
                    if e.errno != errno.EACCES:
                        raise e
                    ui.ui_factory.show_warning(gettext(
                        'unable to remove "{0}": {1}.').format(
                        path, e.strerror))
        else:
            note('  ' + subp)
    if not has_deleted:
        note(gettext("No files deleted."))
