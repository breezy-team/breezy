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

"""Merge logic for news_merge plugin."""


from bzrlib.plugins.news_merge.parser import simple_parse
from bzrlib import merge, merge3


magic_marker = '|NEWS-MERGE-MAGIC-MARKER|'


class NewsMerger(merge.AbstractPerFileMerger):
    """Merge bzr NEWS files.

    :ivar: affected_files.
    """

    def __init__(self, merger):
        super(NewsMerger, self).__init__(merger)
        self.affected_files = None

    def merge_contents(self, params):
        """Perform a simple 3-way merge of a bzr NEWS file.
        
        Each section of a bzr NEWS file is essentially an ordered set of bullet
        points, so we can simply take a set of bullet points, determine which
        bullets to add and which to remove, sort, and reserialize.
        """
        # First, check whether this custom merge logic should be used.  We
        # expect most files should not be merged by this file.
        if params.winner == 'other':
            # OTHER is a straight winner, rely on default merge.
            return 'not_applicable', None
        elif not params.is_file_merge():
            # THIS and OTHER aren't both files.
            return 'not_applicable', None
        elif not self.filename_matches_config(params):
            # The filename isn't listed in the 'news_merge_files' config
            # option.
            return 'not_applicable', None
        # Transform the different versions of the NEWS file into a bunch of
        # text lines where each line matches one part of the overall
        # structure, e.g. a heading or bullet.
        def munge(lines):
            return list(blocks_to_fakelines(simple_parse(''.join(lines))))
        this_lines = munge(params.this_lines)
        other_lines = munge(params.other_lines)
        base_lines = munge(params.base_lines)
        m3 = merge3.Merge3(base_lines, this_lines, other_lines)
        result_lines = []
        for group in m3.merge_groups():
            if group[0] == 'conflict':
                _, base, a, b = group
                # Are all the conflicting lines bullets?  If so, we can merge
                # this.
                for line_set in [base, a, b]:
                    for line in line_set:
                        if not line.startswith('bullet'):
                            # Something else :(
                            # Maybe the default merge can cope.
                            return 'not_applicable', None
                # Calculate additions and deletions.
                new_in_a = set(a).difference(base)
                new_in_b = set(b).difference(base)
                all_new = new_in_a.union(new_in_b)
                deleted_in_a = set(base).difference(a)
                deleted_in_b = set(base).difference(b)
                # Combine into the final set of bullet points.
                final = all_new.difference(deleted_in_a).difference(
                    deleted_in_b)
                # Sort, and emit.
                final = sorted(final, key=sort_key)
                result_lines.extend(final)
            else:
                result_lines.extend(group[1])
        # Transform the merged elements back into real blocks of lines.
        return 'success', list(fakelines_to_blocks(result_lines))

    def filename_matches_config(self, params):
        affected_files = self.affected_files
        if affected_files is None:
            config = self.merger.this_tree.branch.get_config()
            # Until bzr provides a better policy for caching the config, we
            # just add the part we're interested in to the params to avoid
            # reading the config files repeatedly (bazaar.conf, location.conf,
            # branch.conf).
            affected_files = config.get_user_option_as_list('news_merge_files')
            if affected_files is None:
                # If nothing was specified in the config, we have nothing to do,
                # but we use None in the params to start the caching.
                affected_files = []
            self.affected_files = affected_files
        if affected_files:
            filename = params.merger.this_tree.id2path(params.file_id)
            if filename in affected_files:
                return True
        return False


def blocks_to_fakelines(blocks):
    for kind, text in blocks:
        yield '%s%s%s' % (kind, magic_marker, text)


def fakelines_to_blocks(fakelines):
    fakelines = list(fakelines)
    # Strip out the magic_marker, and reinstate the \n\n between blocks
    for fakeline in fakelines[:-1]:
        yield fakeline.split(magic_marker, 1)[1] + '\n\n'
    # The final block doesn't have a trailing \n\n.
    for fakeline in fakelines[-1:]:
        yield fakeline.split(magic_marker, 1)[1]


def sort_key(s):
    return s.replace('`', '').lower()
