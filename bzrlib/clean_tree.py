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


import errno
import os
import shutil
import sys

from bzrlib.osutils import has_symlinks, isdir
from bzrlib.trace import note
from bzrlib.workingtree import WorkingTree


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
    tree.lock_read()
    try:
        deletables = list(iter_deletables(tree, unknown=unknown,
            ignored=ignored, detritus=detritus))
        if len(deletables) == 0:
            note('Nothing to delete.')
            return 0
        if not no_prompt:
            for path, subp in deletables:
                print subp
            val = raw_input('Are you sure you wish to delete these [y/N]?')
            if val.lower() not in ('y', 'yes'):
                print 'Canceled'
                return 0
        delete_items(deletables, dry_run=dry_run)
    finally:
        tree.unlock()


def delete_items(deletables, dry_run=False):
    """Delete files in the deletables iterable"""
    has_deleted = False
    for path, subp in deletables:
        if not has_deleted:
            note("deleting paths:")
            has_deleted = True
        note('  ' + subp)
        if not dry_run:
            if isdir(path):
                shutil.rmtree(path)
            else:
                os.unlink(path)
    if not has_deleted:
        note("No files deleted.")
