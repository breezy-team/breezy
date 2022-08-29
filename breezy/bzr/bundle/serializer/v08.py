# Copyright (C) 2005, 2006, 2009 Canonical Ltd
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

"""Serializer factory for reading and writing bundles.
"""

from .... import (
    errors,
    transport as _mod_transport,
    ui,
    )
from . import (
    BundleSerializer,
    _get_bundle_header,
    binary_diff,
    )
from ..bundle_data import (
    RevisionInfo,
    BundleInfo,
    )
from ....diff import internal_diff
from ....revision import NULL_REVISION
from ...testament import StrictTestament
from ....timestamp import (
    format_highres_date,
    )
from ....textfile import text_file
from ....trace import mutter

bool_text = {True: 'yes', False: 'no'}


class Action(object):
    """Represent an action"""

    def __init__(self, name, parameters=None, properties=None):
        self.name = name
        if parameters is None:
            self.parameters = []
        else:
            self.parameters = parameters
        if properties is None:
            self.properties = []
        else:
            self.properties = properties

    def add_utf8_property(self, name, value):
        """Add a property whose value is currently utf8 to the action."""
        self.properties.append((name, value.decode('utf8')))

    def add_property(self, name, value):
        """Add a property to the action"""
        self.properties.append((name, value))

    def add_bool_property(self, name, value):
        """Add a boolean property to the action"""
        self.add_property(name, bool_text[value])

    def write(self, to_file):
        """Write action as to a file"""
        p_texts = [' '.join([self.name] + self.parameters)]
        for prop in self.properties:
            if len(prop) == 1:
                p_texts.append(prop[0])
            else:
                p_texts.append('%s:%s' % prop)
        text = ['=== ']
        text.append(' // '.join(p_texts))
        text_line = ''.join(text).encode('utf-8')
        available = 79
        while len(text_line) > available:
            to_file.write(text_line[:available])
            text_line = text_line[available:]
            to_file.write(b'\n... ')
            available = 79 - len(b'... ')
        to_file.write(text_line + b'\n')


class BundleSerializerV08(BundleSerializer):

    def read(self, f):
        """Read the rest of the bundles from the supplied file.

        :param f: The file to read from
        :return: A list of bundles
        """
        return BundleReader(f).info

    def check_compatible(self):
        if self.source.supports_rich_root():
            raise errors.IncompatibleBundleFormat('0.8', repr(self.source))

    def write(self, source, revision_ids, forced_bases, f):
        """Write the bundless to the supplied files.

        :param source: A source for revision information
        :param revision_ids: The list of revision ids to serialize
        :param forced_bases: A dict of revision -> base that overrides default
        :param f: The file to output to
        """
        self.source = source
        self.revision_ids = revision_ids
        self.forced_bases = forced_bases
        self.to_file = f
        self.check_compatible()
        with source.lock_read():
            self._write_main_header()
            with ui.ui_factory.nested_progress_bar() as pb:
                self._write_revisions(pb)

    def write_bundle(self, repository, revision_id, base_revision_id, out):
        """Helper function for translating write_bundle to write"""
        forced_bases = {revision_id: base_revision_id}
        if base_revision_id is NULL_REVISION:
            base_revision_id = None
        graph = repository.get_graph()
        revision_ids = graph.find_unique_ancestors(revision_id,
                                                   [base_revision_id])
        revision_ids = list(repository.get_graph().iter_topo_order(
            revision_ids))
        revision_ids.reverse()
        self.write(repository, revision_ids, forced_bases, out)
        return revision_ids

    def _write_main_header(self):
        """Write the header for the changes"""
        f = self.to_file
        f.write(_get_bundle_header('0.8'))
        f.write(b'#\n')

    def _write(self, key, value, indent=1, trailing_space_when_empty=False):
        """Write out meta information, with proper indenting, etc.

        :param trailing_space_when_empty: To work around a bug in earlier
            bundle readers, when writing an empty property, we use "prop: \n"
            rather than writing "prop:\n".
            If this parameter is True, and value is the empty string, we will
            write an extra space.
        """
        if indent < 1:
            raise ValueError('indentation must be greater than 0')
        f = self.to_file
        f.write(b'#' + (b' ' * indent))
        f.write(key.encode('utf-8'))
        if not value:
            if trailing_space_when_empty and value == '':
                f.write(b': \n')
            else:
                f.write(b':\n')
        elif isinstance(value, bytes):
            f.write(b': ')
            f.write(value)
            f.write(b'\n')
        elif isinstance(value, str):
            f.write(b': ')
            f.write(value.encode('utf-8'))
            f.write(b'\n')
        else:
            f.write(b':\n')
            for entry in value:
                f.write(b'#' + (b' ' * (indent + 2)))
                if isinstance(entry, bytes):
                    f.write(entry)
                else:
                    f.write(entry.encode('utf-8'))
                f.write(b'\n')

    def _write_revisions(self, pb):
        """Write the information for all of the revisions."""

        # Optimize for the case of revisions in order
        last_rev_id = None
        last_rev_tree = None

        i_max = len(self.revision_ids)
        for i, rev_id in enumerate(self.revision_ids):
            pb.update("Generating revision data", i, i_max)
            rev = self.source.get_revision(rev_id)
            if rev_id == last_rev_id:
                rev_tree = last_rev_tree
            else:
                rev_tree = self.source.revision_tree(rev_id)
            if rev_id in self.forced_bases:
                explicit_base = True
                base_id = self.forced_bases[rev_id]
                if base_id is None:
                    base_id = NULL_REVISION
            else:
                explicit_base = False
                if rev.parent_ids:
                    base_id = rev.parent_ids[-1]
                else:
                    base_id = NULL_REVISION

            if base_id == last_rev_id:
                base_tree = last_rev_tree
            else:
                base_tree = self.source.revision_tree(base_id)
            force_binary = (i != 0)
            self._write_revision(rev, rev_tree, base_id, base_tree,
                                 explicit_base, force_binary)

            last_rev_id = base_id
            last_rev_tree = base_tree

    def _testament_sha1(self, revision_id):
        return StrictTestament.from_revision(self.source,
                                             revision_id).as_sha1()

    def _write_revision(self, rev, rev_tree, base_rev, base_tree,
                        explicit_base, force_binary):
        """Write out the information for a revision."""
        def w(key, value):
            self._write(key, value, indent=1)

        w('message', rev.message.split('\n'))
        w('committer', rev.committer)
        w('date', format_highres_date(rev.timestamp, rev.timezone))
        self.to_file.write(b'\n')

        self._write_delta(rev_tree, base_tree, rev.revision_id, force_binary)

        w('revision id', rev.revision_id)
        w('sha1', self._testament_sha1(rev.revision_id))
        w('inventory sha1', rev.inventory_sha1)
        if rev.parent_ids:
            w('parent ids', rev.parent_ids)
        if explicit_base:
            w('base id', base_rev)
        if rev.properties:
            self._write('properties', None, indent=1)
            for name, value in sorted(rev.properties.items()):
                self._write(name, value, indent=3,
                            trailing_space_when_empty=True)

        # Add an extra blank space at the end
        self.to_file.write(b'\n')

    def _write_action(self, name, parameters, properties=None):
        if properties is None:
            properties = []
        p_texts = ['%s:%s' % v for v in properties]
        self.to_file.write(b'=== ')
        self.to_file.write(' '.join([name] + parameters).encode('utf-8'))
        self.to_file.write(' // '.join(p_texts).encode('utf-8'))
        self.to_file.write(b'\n')

    def _write_delta(self, new_tree, old_tree, default_revision_id,
                     force_binary):
        """Write out the changes between the trees."""
        DEVNULL = '/dev/null'
        old_label = ''
        new_label = ''

        def do_diff(file_id, old_path, new_path, action, force_binary):
            def tree_lines(tree, path, require_text=False):
                try:
                    tree_file = tree.get_file(path)
                except _mod_transport.NoSuchFile:
                    return []
                else:
                    if require_text is True:
                        tree_file = text_file(tree_file)
                    return tree_file.readlines()

            try:
                if force_binary:
                    raise errors.BinaryFile()
                old_lines = tree_lines(old_tree, old_path, require_text=True)
                new_lines = tree_lines(new_tree, new_path, require_text=True)
                action.write(self.to_file)
                internal_diff(old_path, old_lines, new_path, new_lines,
                              self.to_file)
            except errors.BinaryFile:
                old_lines = tree_lines(old_tree, old_path, require_text=False)
                new_lines = tree_lines(new_tree, new_path, require_text=False)
                action.add_property('encoding', 'base64')
                action.write(self.to_file)
                binary_diff(old_path, old_lines, new_path, new_lines,
                            self.to_file)

        def finish_action(action, file_id, kind, meta_modified, text_modified,
                          old_path, new_path):
            entry = new_tree.root_inventory.get_entry(file_id)
            if entry.revision != default_revision_id:
                action.add_utf8_property('last-changed', entry.revision)
            if meta_modified:
                action.add_bool_property('executable', entry.executable)
            if text_modified and kind == "symlink":
                action.add_property('target', entry.symlink_target)
            if text_modified and kind == "file":
                do_diff(file_id, old_path, new_path, action, force_binary)
            else:
                action.write(self.to_file)

        delta = new_tree.changes_from(old_tree, want_unchanged=True,
                                      include_root=True)
        for change in delta.removed:
            action = Action('removed', [change.kind[0], change.path[0]]).write(self.to_file)

        # TODO(jelmer): Treat copied specially here?
        for change in delta.added + delta.copied:
            action = Action(
                'added', [change.kind[1], change.path[1]],
                [('file-id', change.file_id.decode('utf-8'))])
            meta_modified = (change.kind[1] == 'file' and
                             change.executable[1])
            finish_action(action, change.file_id, change.kind[1], meta_modified, change.changed_content,
                          DEVNULL, change.path[1])

        for change in delta.renamed:
            action = Action('renamed', [change.kind[1], change.path[0]], [(change.path[1],)])
            finish_action(action, change.file_id, change.kind[1], change.meta_modified(), change.changed_content,
                          change.path[0], change.path[1])

        for change in delta.modified:
            action = Action('modified', [change.kind[1], change.path[1]])
            finish_action(action, change.file_id, change.kind[1], change.meta_modified(), change.changed_content,
                          change.path[0], change.path[1])

        for change in delta.unchanged:
            new_rev = new_tree.get_file_revision(change.path[1])
            if new_rev is None:
                continue
            old_rev = old_tree.get_file_revision(change.path[0])
            if new_rev != old_rev:
                action = Action('modified', [change.kind[1], change.path[1]])
                action.add_utf8_property('last-changed', new_rev)
                action.write(self.to_file)


class BundleReader(object):
    """This class reads in a bundle from a file, and returns
    a Bundle object, which can then be applied against a tree.
    """

    def __init__(self, from_file):
        """Read in the bundle from the file.

        :param from_file: A file-like object (must have iterator support).
        """
        object.__init__(self)
        self.from_file = iter(from_file)
        self._next_line = None

        self.info = self._get_info()
        # We put the actual inventory ids in the footer, so that the patch
        # is easier to read for humans.
        # Unfortunately, that means we need to read everything before we
        # can create a proper bundle.
        self._read()
        self._validate()

    def _get_info(self):
        return BundleInfo08()

    def _read(self):
        next(self._next())
        while self._next_line is not None:
            if not self._read_revision_header():
                break
            if self._next_line is None:
                break
            self._read_patches()
            self._read_footer()

    def _validate(self):
        """Make sure that the information read in makes sense
        and passes appropriate checksums.
        """
        # Fill in all the missing blanks for the revisions
        # and generate the real_revisions list.
        self.info.complete_info()

    def _next(self):
        """yield the next line, but secretly
        keep 1 extra line for peeking.
        """
        for line in self.from_file:
            last = self._next_line
            self._next_line = line
            if last is not None:
                #mutter('yielding line: %r' % last)
                yield last
        last = self._next_line
        self._next_line = None
        #mutter('yielding line: %r' % last)
        yield last

    def _read_revision_header(self):
        found_something = False
        self.info.revisions.append(RevisionInfo(None))
        for line in self._next():
            # The bzr header is terminated with a blank line
            # which does not start with '#'
            if line is None or line == b'\n':
                break
            if not line.startswith(b'#'):
                continue
            found_something = True
            self._handle_next(line)
        if not found_something:
            # Nothing was there, so remove the added revision
            self.info.revisions.pop()
        return found_something

    def _read_next_entry(self, line, indent=1):
        """Read in a key-value pair
        """
        if not line.startswith(b'#'):
            raise errors.MalformedHeader('Bzr header did not start with #')
        line = line[1:-1].decode('utf-8')  # Remove the '#' and '\n'
        if line[:indent] == ' ' * indent:
            line = line[indent:]
        if not line:
            return None, None  # Ignore blank lines

        loc = line.find(': ')
        if loc != -1:
            key = line[:loc]
            value = line[loc + 2:]
            if not value:
                value = self._read_many(indent=indent + 2)
        elif line[-1:] == ':':
            key = line[:-1]
            value = self._read_many(indent=indent + 2)
        else:
            raise errors.MalformedHeader('While looking for key: value pairs,'
                                         ' did not find the colon %r' % (line))

        key = key.replace(' ', '_')
        #mutter('found %s: %s' % (key, value))
        return key, value

    def _handle_next(self, line):
        if line is None:
            return
        key, value = self._read_next_entry(line, indent=1)
        mutter('_handle_next %r => %r' % (key, value))
        if key is None:
            return

        revision_info = self.info.revisions[-1]
        if key in revision_info.__dict__:
            if getattr(revision_info, key) is None:
                if key in ('file_id', 'revision_id', 'base_id'):
                    value = value.encode('utf8')
                elif key in ('parent_ids'):
                    value = [v.encode('utf8') for v in value]
                elif key in ('testament_sha1', 'inventory_sha1', 'sha1'):
                    value = value.encode('ascii')
                setattr(revision_info, key, value)
            else:
                raise errors.MalformedHeader('Duplicated Key: %s' % key)
        else:
            # What do we do with a key we don't recognize
            raise errors.MalformedHeader('Unknown Key: "%s"' % key)

    def _read_many(self, indent):
        """If a line ends with no entry, that means that it should be
        followed with multiple lines of values.

        This detects the end of the list, because it will be a line that
        does not start properly indented.
        """
        values = []
        start = b'#' + (b' ' * indent)

        if self._next_line is None or not self._next_line.startswith(start):
            return values

        for line in self._next():
            values.append(line[len(start):-1].decode('utf-8'))
            if self._next_line is None or not self._next_line.startswith(start):
                break
        return values

    def _read_one_patch(self):
        """Read in one patch, return the complete patch, along with
        the next line.

        :return: action, lines, do_continue
        """
        #mutter('_read_one_patch: %r' % self._next_line)
        # Peek and see if there are no patches
        if self._next_line is None or self._next_line.startswith(b'#'):
            return None, [], False

        first = True
        lines = []
        for line in self._next():
            if first:
                if not line.startswith(b'==='):
                    raise errors.MalformedPatches('The first line of all patches'
                                                  ' should be a bzr meta line "==="'
                                                  ': %r' % line)
                action = line[4:-1].decode('utf-8')
            elif line.startswith(b'... '):
                action += line[len(b'... '):-1].decode('utf-8')

            if (self._next_line is not None and
                    self._next_line.startswith(b'===')):
                return action, lines, True
            elif self._next_line is None or self._next_line.startswith(b'#'):
                return action, lines, False

            if first:
                first = False
            elif not line.startswith(b'... '):
                lines.append(line)

        return action, lines, False

    def _read_patches(self):
        do_continue = True
        revision_actions = []
        while do_continue:
            action, lines, do_continue = self._read_one_patch()
            if action is not None:
                revision_actions.append((action, lines))
        if self.info.revisions[-1].tree_actions is not None:
            raise AssertionError()
        self.info.revisions[-1].tree_actions = revision_actions

    def _read_footer(self):
        """Read the rest of the meta information.

        :param first_line:  The previous step iterates past what it
                            can handle. That extra line is given here.
        """
        for line in self._next():
            self._handle_next(line)
            if self._next_line is None:
                break
            if not self._next_line.startswith(b'#'):
                # Consume the trailing \n and stop processing
                next(self._next())
                break


class BundleInfo08(BundleInfo):

    def _update_tree(self, bundle_tree, revision_id):
        bundle_tree.note_last_changed('', revision_id)
        BundleInfo._update_tree(self, bundle_tree, revision_id)

    def _testament_sha1_from_revision(self, repository, revision_id):
        testament = StrictTestament.from_revision(repository, revision_id)
        return testament.as_sha1()

    def _testament(self, revision, tree):
        return StrictTestament(revision, tree)
