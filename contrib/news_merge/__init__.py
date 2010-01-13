# Copyright (C) 2010 Canonical Ltd
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

"""Merge hook for bzr's NEWS file.

Install this as a plugin, e.g:

    cp contrib/news-file-merge-hook.py ~/.bazaar/plugins/news_merge.py
"""

from .parser import simple_parse

from bzrlib.merge import Merger
from bzrlib.merge3 import Merge3


def news_merge_hook(params):
    if params.winner == 'other':
        # OTHER is a straight winner, rely on default merge.
        return 'not_applicable', None
    elif params.is_file_merge():
        # THIS and OTHER are both files.  That's a good start.
        filename = params.merger.this_tree.id2path(params.file_id)
        if filename != 'NEWS':
            return 'not_applicable', None
        return news_merger(params)
    else:
        return 'not_applicable', None

magic_marker = '|NEWS-MERGE-MAGIC-MARKER|'

def blocks_to_fakelines(blocks):
    for kind, text in blocks:
        yield '%s%s%s' % (kind, magic_marker, text)

def fakelines_to_lines(fakelines):
    for fakeline in fakelines:
        yield fakeline.split(magic_marker, 1)[1] + '\n'
        yield '\n'

def sort_key(s):
    return s.replace('`', '').lower()
    
def news_merger(params):
    def munge(lines):
        return list(blocks_to_fakelines(simple_parse(''.join(lines))))
    this_lines = munge(params.this_lines)
    other_lines = munge(params.other_lines)
    base_lines = munge(params.base_lines)
    m3 = Merge3(base_lines, this_lines, other_lines)
    result_lines = []
    for group in m3.merge_groups():
        if group[0] == 'conflict':
            _, base, a, b = group
            # are all the conflicting lines bullets?  If so, we can merge this.
            for line_set in [base, a, b]:
                for line in line_set:
                    if not line.startswith('bullet'):
                        # Something else :(
                        # Maybe the default merge can cope.
                        return 'not_applicable', None
            new_in_a = set(a).difference(base)
            new_in_b = set(b).difference(base)
            all_new = new_in_a.union(new_in_b)
            deleted_in_a = set(base).difference(a)
            deleted_in_b = set(base).difference(b)
            final = all_new.difference(deleted_in_a).difference(deleted_in_b)
            final = sorted(final, key=sort_key)
            result_lines.extend(final)
        else:
            result_lines.extend(group[1])
    return 'success', list(fakelines_to_lines(result_lines))


Merger.hooks.install_named_hook(
    'merge_file_content', news_merge_hook, 'NEWS file merge')

