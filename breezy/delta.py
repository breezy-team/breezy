# Copyright (C) 2005-2010 Canonical Ltd
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

from __future__ import absolute_import

from breezy import (
    osutils,
    )
from .sixish import (
    StringIO,
    )
from .trace import is_quiet


class TreeDelta(object):
    """Describes changes from one tree to another.

    Contains seven lists:

    added
        (path, id, kind)
    removed
        (path, id, kind)
    renamed
        (oldpath, newpath, id, kind, text_modified, meta_modified)
    kind_changed
        (path, id, old_kind, new_kind)
    modified
        (path, id, kind, text_modified, meta_modified)
    unchanged
        (path, id, kind)
    unversioned
        (path, None, kind)

    Each id is listed only once.

    Files that are both modified and renamed are listed only in
    renamed, with the text_modified flag true. The text_modified
    applies either to the content of the file or the target of the
    symbolic link, depending of the kind of file.

    Files are only considered renamed if their name has changed or
    their parent directory has changed.  Renaming a directory
    does not count as renaming all its contents.

    The lists are normally sorted when the delta is created.
    """

    def __init__(self):
        self.added = []
        self.removed = []
        self.renamed = []
        self.kind_changed = []
        self.modified = []
        self.unchanged = []
        self.unversioned = []
        self.missing = []

    def __eq__(self, other):
        if not isinstance(other, TreeDelta):
            return False
        return self.added == other.added \
            and self.removed == other.removed \
            and self.renamed == other.renamed \
            and self.modified == other.modified \
            and self.unchanged == other.unchanged \
            and self.kind_changed == other.kind_changed \
            and self.unversioned == other.unversioned

    def __ne__(self, other):
        return not (self == other)

    def __repr__(self):
        return "TreeDelta(added=%r, removed=%r, renamed=%r," \
            " kind_changed=%r, modified=%r, unchanged=%r," \
            " unversioned=%r)" % (self.added,
                                  self.removed, self.renamed, self.kind_changed, self.modified,
                                  self.unchanged, self.unversioned)

    def has_changed(self):
        return bool(self.modified
                    or self.added
                    or self.removed
                    or self.renamed
                    or self.kind_changed)

    def touches_file_id(self, file_id):
        """Return True if file_id is modified by this delta."""
        for l in self.added, self.removed, self.modified:
            for v in l:
                if v[1] == file_id:
                    return True
        for v in self.renamed:
            if v[2] == file_id:
                return True
        for v in self.kind_changed:
            if v[1] == file_id:
                return True
        return False

    def get_changes_as_text(self, show_ids=False, show_unchanged=False,
                            short_status=False):
        output = StringIO()
        report_delta(output, self, short_status, show_ids, show_unchanged)
        return output.getvalue()


def _compare_trees(old_tree, new_tree, want_unchanged, specific_files,
                   include_root, extra_trees=None,
                   require_versioned=False, want_unversioned=False):
    """Worker function that implements Tree.changes_from."""
    delta = TreeDelta()
    # mutter('start compare_trees')

    for (file_id, path, content_change, versioned, parent_id, name, kind,
         executable) in new_tree.iter_changes(old_tree, want_unchanged,
                                              specific_files, extra_trees=extra_trees,
                                              require_versioned=require_versioned,
                                              want_unversioned=want_unversioned):
        if versioned == (False, False):
            delta.unversioned.append((path[1], None, kind[1]))
            continue
        if not include_root and (None, None) == parent_id:
            continue
        fully_present = tuple((versioned[x] and kind[x] is not None) for
                              x in range(2))
        if fully_present[0] != fully_present[1]:
            if fully_present[1] is True:
                delta.added.append((path[1], file_id, kind[1]))
            else:
                delta.removed.append((path[0], file_id, kind[0]))
        elif fully_present[0] is False:
            delta.missing.append((path[1], file_id, kind[1]))
        elif name[0] != name[1] or parent_id[0] != parent_id[1]:
            # If the name changes, or the parent_id changes, we have a rename
            # (if we move a parent, that doesn't count as a rename for the
            # file)
            delta.renamed.append((path[0],
                                  path[1],
                                  file_id,
                                  kind[1],
                                  content_change,
                                  (executable[0] != executable[1])))
        elif kind[0] != kind[1]:
            delta.kind_changed.append((path[1], file_id, kind[0], kind[1]))
        elif content_change or executable[0] != executable[1]:
            delta.modified.append((path[1], file_id, kind[1],
                                   content_change,
                                   (executable[0] != executable[1])))
        else:
            delta.unchanged.append((path[1], file_id, kind[1]))

    delta.removed.sort()
    delta.added.sort()
    delta.renamed.sort()

    def missing_key(change):
        return (change[0] or '', change[1])
    delta.missing.sort(key=missing_key)
    # TODO: jam 20060529 These lists shouldn't need to be sorted
    #       since we added them in alphabetical order.
    delta.modified.sort()
    delta.unchanged.sort()
    delta.unversioned.sort()

    return delta


class _ChangeReporter(object):
    """Report changes between two trees"""

    def __init__(self, output=None, suppress_root_add=True,
                 output_file=None, unversioned_filter=None, view_info=None,
                 classify=True):
        """Constructor

        :param output: a function with the signature of trace.note, i.e.
            accepts a format and parameters.
        :param supress_root_add: If true, adding the root will be ignored
            (i.e. when a tree has just been initted)
        :param output_file: If supplied, a file-like object to write to.
            Only one of output and output_file may be supplied.
        :param unversioned_filter: A filter function to be called on
            unversioned files. This should return True to ignore a path.
            By default, no filtering takes place.
        :param view_info: A tuple of view_name,view_files if only
            items inside a view are to be reported on, or None for
            no view filtering.
        :param classify: Add special symbols to indicate file kind.
        """
        if output_file is not None:
            if output is not None:
                raise BzrError('Cannot specify both output and output_file')

            def output(fmt, *args):
                output_file.write((fmt % args) + '\n')
        self.output = output
        if self.output is None:
            from . import trace
            self.output = trace.note
        self.suppress_root_add = suppress_root_add
        self.modified_map = {'kind changed': 'K',
                             'unchanged': ' ',
                             'created': 'N',
                             'modified': 'M',
                             'deleted': 'D',
                             'missing': '!',
                             }
        self.versioned_map = {'added': '+',  # versioned target
                              'unchanged': ' ',  # versioned in both
                              'removed': '-',  # versioned in source
                              'unversioned': '?',  # versioned in neither
                              }
        self.unversioned_filter = unversioned_filter
        if classify:
            self.kind_marker = osutils.kind_marker
        else:
            self.kind_marker = lambda kind: ''
        if view_info is None:
            self.view_name = None
            self.view_files = []
        else:
            self.view_name = view_info[0]
            self.view_files = view_info[1]
            self.output("Operating on whole tree but only reporting on "
                        "'%s' view." % (self.view_name,))

    def report(self, file_id, paths, versioned, renamed, modified, exe_change,
               kind):
        """Report one change to a file

        :param file_id: The file_id of the file
        :param path: The old and new paths as generated by Tree.iter_changes.
        :param versioned: may be 'added', 'removed', 'unchanged', or
            'unversioned.
        :param renamed: may be True or False
        :param modified: may be 'created', 'deleted', 'kind changed',
            'modified' or 'unchanged'.
        :param exe_change: True if the execute bit has changed
        :param kind: A pair of file kinds, as generated by Tree.iter_changes.
            None indicates no file present.
        """
        if is_quiet():
            return
        if paths[1] == '' and versioned == 'added' and self.suppress_root_add:
            return
        if self.view_files and not osutils.is_inside_any(self.view_files,
                                                         paths[1]):
            return
        if versioned == 'unversioned':
            # skip ignored unversioned files if needed.
            if self.unversioned_filter is not None:
                if self.unversioned_filter(paths[1]):
                    return
            # dont show a content change in the output.
            modified = 'unchanged'
        # we show both paths in the following situations:
        # the file versioning is unchanged AND
        # ( the path is different OR
        #   the kind is different)
        if (versioned == 'unchanged' and
                (renamed or modified == 'kind changed')):
            if renamed:
                # on a rename, we show old and new
                old_path, path = paths
            else:
                # if it's not renamed, we're showing both for kind changes
                # so only show the new path
                old_path, path = paths[1], paths[1]
            # if the file is not missing in the source, we show its kind
            # when we show two paths.
            if kind[0] is not None:
                old_path += self.kind_marker(kind[0])
            old_path += " => "
        elif versioned == 'removed':
            # not present in target
            old_path = ""
            path = paths[0]
        else:
            old_path = ""
            path = paths[1]
        if renamed:
            rename = "R"
        else:
            rename = self.versioned_map[versioned]
        # we show the old kind on the new path when the content is deleted.
        if modified == 'deleted':
            path += self.kind_marker(kind[0])
        # otherwise we always show the current kind when there is one
        elif kind[1] is not None:
            path += self.kind_marker(kind[1])
        if exe_change:
            exe = '*'
        else:
            exe = ' '
        self.output("%s%s%s %s%s", rename, self.modified_map[modified], exe,
                    old_path, path)


def report_changes(change_iterator, reporter):
    """Report the changes from a change iterator.

    This is essentially a translation from low-level to medium-level changes.
    Further processing may be required to produce a human-readable output.
    Unfortunately, some tree-changing operations are very complex
    :change_iterator: an iterator or sequence of changes in the format
        generated by Tree.iter_changes
    :param reporter: The _ChangeReporter that will report the changes.
    """
    versioned_change_map = {
        (True, True): 'unchanged',
        (True, False): 'removed',
        (False, True): 'added',
        (False, False): 'unversioned',
        }

    def path_key(change):
        if change[1][0] is not None:
            path = change[1][0]
        else:
            path = change[1][1]
        return osutils.splitpath(path)
    for (file_id, path, content_change, versioned, parent_id, name, kind,
         executable) in sorted(change_iterator, key=path_key):
        exe_change = False
        # files are "renamed" if they are moved or if name changes, as long
        # as it had a value
        if None not in name and None not in parent_id and\
                (name[0] != name[1] or parent_id[0] != parent_id[1]):
            renamed = True
        else:
            renamed = False
        if kind[0] != kind[1]:
            if kind[0] is None:
                modified = "created"
            elif kind[1] is None:
                modified = "deleted"
            else:
                modified = "kind changed"
        else:
            if content_change:
                modified = "modified"
            elif kind[0] is None:
                modified = "missing"
            else:
                modified = "unchanged"
            if kind[1] == "file":
                exe_change = (executable[0] != executable[1])
        versioned_change = versioned_change_map[versioned]
        reporter.report(file_id, path, versioned_change, renamed, modified,
                        exe_change, kind)


def report_delta(to_file, delta, short_status=False, show_ids=False,
                 show_unchanged=False, indent='', predicate=None, classify=True):
    """Output this delta in status-like form to to_file.

    :param to_file: A file-like object where the output is displayed.

    :param delta: A TreeDelta containing the changes to be displayed

    :param short_status: Single-line status if True.

    :param show_ids: Output the file ids if True.

    :param show_unchanged: Output the unchanged files if True.

    :param indent: Added at the beginning of all output lines (for merged
        revisions).

    :param predicate: A callable receiving a path and a file id and
        returning True if the path should be displayed.

    :param classify: Add special symbols to indicate file kind.
    """

    def decorate_path(path, kind, meta_modified=None):
        if not classify:
            return path
        if kind == 'directory':
            path += '/'
        elif kind == 'symlink':
            path += '@'
        if meta_modified:
            path += '*'
        return path

    def show_more_renamed(item):
        (oldpath, file_id, kind,
         text_modified, meta_modified, newpath) = item
        dec_new_path = decorate_path(newpath, kind, meta_modified)
        to_file.write(' => %s' % dec_new_path)
        if text_modified or meta_modified:
            extra_modified.append((newpath, file_id, kind,
                                   text_modified, meta_modified))

    def show_more_kind_changed(item):
        (path, file_id, old_kind, new_kind) = item
        to_file.write(' (%s => %s)' % (old_kind, new_kind))

    def show_path(path, file_id, kind, meta_modified,
                  default_format, with_file_id_format):
        dec_path = decorate_path(path, kind, meta_modified)
        if show_ids:
            to_file.write(with_file_id_format % dec_path)
        else:
            to_file.write(default_format % dec_path)

    def show_list(files, long_status_name, short_status_letter,
                  default_format='%s', with_file_id_format='%-30s',
                  show_more=None):
        if files:
            header_shown = False
            if short_status:
                prefix = short_status_letter
            else:
                prefix = ''
            prefix = indent + prefix + '  '

            for item in files:
                path, file_id, kind = item[:3]
                if (predicate is not None and not predicate(path, file_id)):
                    continue
                if not header_shown and not short_status:
                    to_file.write(indent + long_status_name + ':\n')
                    header_shown = True
                meta_modified = None
                if len(item) == 5:
                    meta_modified = item[4]

                to_file.write(prefix)
                show_path(path, file_id, kind, meta_modified,
                          default_format, with_file_id_format)
                if show_more is not None:
                    show_more(item)
                if show_ids:
                    to_file.write(' %s' % file_id.decode('utf-8'))
                to_file.write('\n')

    show_list(delta.removed, 'removed', 'D')
    show_list(delta.added, 'added', 'A')
    show_list(delta.missing, 'missing', '!')
    extra_modified = []
    # Reorder delta.renamed tuples so that all lists share the same
    # order for their 3 first fields and that they also begin like
    # the delta.modified tuples
    renamed = [(p, i, k, tm, mm, np)
               for p, np, i, k, tm, mm in delta.renamed]
    show_list(renamed, 'renamed', 'R', with_file_id_format='%s',
              show_more=show_more_renamed)
    show_list(delta.kind_changed, 'kind changed', 'K',
              with_file_id_format='%s',
              show_more=show_more_kind_changed)
    show_list(delta.modified + extra_modified, 'modified', 'M')
    if show_unchanged:
        show_list(delta.unchanged, 'unchanged', 'S')

    show_list(delta.unversioned, 'unknown', ' ')
