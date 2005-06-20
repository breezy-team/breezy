#!/usr/bin/env python
"""\
Read in a changeset output, and process it into a Changeset object.
"""

import bzrlib, bzrlib.changeset
import common

class BadChangeset(Exception): pass
class MalformedHeader(BadChangeset): pass
class MalformedPatches(BadChangeset): pass
class MalformedFooter(BadChangeset): pass

def _unescape(name):
    """Now we want to find the filename effected.
    Unfortunately the filename is written out as
    repr(filename), which means that it surrounds
    the name with quotes which may be single or double
    (single is preferred unless there is a single quote in
    the filename). And some characters will be escaped.

    TODO:   There has to be some pythonic way of undo-ing the
            representation of a string rather than using eval.
    """
    delimiter = name[0]
    if name[-1] != delimiter:
        raise BadChangeset('Could not properly parse the'
                ' filename: %r' % name)
    # We need to handle escaped hexadecimals too.
    return name[1:-1].replace('\"', '"').replace("\'", "'")

class ChangesetInfo(object):
    """This is the intermediate class that gets filled out as
    the file is read.
    """
    def __init__(self):
        self.committer = None
        self.date = None
        self.revno = None
        self.revision = None
        self.revision_sha1 = None
        self.precursor = None
        self.precursor_sha1 = None
        self.precursor_revno = None

        self.tree_root_id = None
        self.file_ids = None
        self.old_file_ids = None

        self.actions = [] #this is the list of things that happened
        self.id2path = {} # A mapping from file id to path name
        self.path2id = {} # The reverse mapping
        self.id2parent = {} # A mapping from a given id to it's parent id

        self.old_id2path = {}
        self.old_path2id = {}
        self.old_id2parent = {}

    def __str__(self):
        import pprint
        return pprint.pformat(self.__dict__)

    def create_maps(self):
        """Go through the individual id sections, and generate the 
        id2path and path2id maps.
        """
        # Rather than use an empty path, the changeset code seems 
        # to like to use "./." for the tree root.
        self.id2path[self.tree_root_id] = './.'
        self.path2id['./.'] = self.tree_root_id
        self.id2parent[self.tree_root_id] = bzrlib.changeset.NULL_ID
        self.old_id2path = self.id2path.copy()
        self.old_path2id = self.path2id.copy()
        self.old_id2parent = self.id2parent.copy()

        if self.file_ids:
            for info in self.file_ids:
                path, f_id, parent_id = info.split('\t')
                self.id2path[f_id] = path
                self.path2id[path] = f_id
                self.id2parent[f_id] = parent_id
        if self.old_file_ids:
            for info in self.old_file_ids:
                path, f_id, parent_id = info.split('\t')
                self.old_id2path[f_id] = path
                self.old_path2id[path] = f_id
                self.old_id2parent[f_id] = parent_id

    def create_changeset(self):
        """Create a changeset from the data contained within."""
        from bzrlib.changeset import Changeset, ChangesetEntry, \
            PatchApply, ReplaceContents
        cset = Changeset()
        
        for info, lines in self.actions:
            print 'handling action', info
            parts = info.split(' ')
            action = parts[0]
            kind = parts[1]
            extra = ' '.join(parts[2:])
            if action == 'renamed':
                old_path, new_path = extra.split(' => ')
                old_path = _unescape(old_path)
                new_path = _unescape(new_path)

                new_id = self.path2id[new_path]
                old_id = self.old_path2id[old_path]
                assert old_id == new_id

                new_parent = self.id2parent[new_id]
                old_parent = self.old_id2parent[old_id]

                entry = ChangesetEntry(old_id, old_parent, old_path)
                entry.new_path = new_path
                entry.new_parent = new_parent
                if lines:
                    entry.contents_change = PatchApply(''.join(lines))
            elif action == 'removed':
                old_path = _unescape(extra)
                old_id = self.old_path2id[old_path]
                old_parent = self.old_id2parent[old_id]
                entry = ChangesetEntry(old_id, old_parent, old_path)
                entry.new_path = None
                entry.new_parent = None
                if lines:
                    # Technically a removed should be a ReplaceContents()
                    # Where you need to have the old contents
                    # But at most we have a remove style patch.
                    #entry.contents_change = ReplaceContents()
                    pass
            elif action == 'added':
                new_path = _unescape(extra)
                new_id = self.path2id[new_path]
                new_parent = self.id2parent[new_id]
                entry = ChangesetEntry(new_id, new_parent, new_path)
                entry.path = None
                entry.parent = None
                if lines:
                    # Technically an added should be a ReplaceContents()
                    # Where you need to have the old contents
                    # But at most we have an add style patch.
                    #entry.contents_change = ReplaceContents()
                    entry.contents_change = PatchApply(''.join(lines))
            elif action == 'modified':
                new_path = _unescape(extra)
                new_id = self.path2id[new_path]
                new_parent = self.id2parent[new_id]
                entry = ChangesetEntry(new_id, new_parent, new_path)
                entry.path = None
                entry.parent = None
                if lines:
                    # Technically an added should be a ReplaceContents()
                    # Where you need to have the old contents
                    # But at most we have an add style patch.
                    #entry.contents_change = ReplaceContents()
                    entry.contents_change = PatchApply(''.join(lines))
            else:
                raise BadChangeset('Unrecognized action: %r' % action)
            cset.add_entry(entry)
        return cset

class ChangesetReader(object):
    """This class reads in a changeset from a file, and returns
    a Changeset object, which can then be applied against a tree.
    """
    def __init__(self, from_file):
        """Read in the changeset from the file.

        :param from_file: A file-like object (must have iterator support).
        """
        object.__init__(self)
        self.from_file = from_file
        
        self.info = ChangesetInfo()
        # We put the actual inventory ids in the footer, so that the patch
        # is easier to read for humans.
        # Unfortunately, that means we need to read everything before we
        # can create a proper changeset.
        self._read_header()
        next_line = self._read_patches()
        if next_line is not None:
            self._read_footer(next_line)

    def get_changeset(self):
        """Create the actual changeset object.
        """
        self.info.create_maps()
        return self.info.create_changeset()

    def _read_header(self):
        """Read the bzr header"""
        header = common.get_header()
        for head_line, line in zip(header, self.from_file):
            if (line[:2] != '# '
                    or line[-1] != '\n'
                    or line[2:-1] != head_line):
                raise MalformedHeader('Did not read the opening'
                    ' header information.')

        for line in self.from_file:
            if self._handle_info_line(line) is not None:
                break

    def _handle_info_line(self, line, in_footer=False):
        """Handle reading a single line.

        This may call itself, in the case that we read_multi,
        and then had a dangling line on the end.
        """
        # The bzr header is terminated with a blank line
        # which does not start with #
        next_line = None
        if line[:1] == '\n':
            return 'break'
        if line[:2] != '# ':
            raise MalformedHeader('Opening bzr header did not start with #')

        line = line[2:-1] # Remove the '# '
        if not line:
            return # Ignore blank lines

        if in_footer and line in ('BEGIN BZR FOOTER', 'END BZR FOOTER'):
            return

        loc = line.find(': ')
        if loc != -1:
            key = line[:loc]
            value = line[loc+2:]
            if not value:
                value, next_line = self._read_many()
        else:
            if line[-1:] == ':':
                key = line[:-1]
                value, next_line = self._read_many()
            else:
                raise MalformedHeader('While looking for key: value pairs,'
                        ' did not find the colon %r' % (line))

        key = key.replace(' ', '_')
        if hasattr(self.info, key):
            if getattr(self.info, key) is None:
                setattr(self.info, key, value)
            else:
                raise MalformedHeader('Duplicated Key: %s' % key)
        else:
            # What do we do with a key we don't recognize
            raise MalformedHeader('Unknown Key: %s' % key)
        
        if next_line:
            self._handle_info_line(next_line, in_footer=in_footer)

    def _read_many(self):
        """If a line ends with no entry, that means that it should be
        followed with multiple lines of values.

        This detects the end of the list, because it will be a line that
        does not start with '#    '. Because it has to read that extra
        line, it returns the tuple: (values, next_line)
        """
        values = []
        for line in self.from_file:
            if line[:5] != '#    ':
                return values, line
            values.append(line[5:-1])
        return values, None

    def _read_one_patch(self, first_line=None):
        """Read in one patch, return the complete patch, along with
        the next line.

        :return: action, lines, next_line, do_continue
        """
        first = True
        action = None

        def parse_firstline(line):
            if line[:1] == '#':
                return None
            if line[:3] != '***':
                raise MalformedPatches('The first line of all patches'
                    ' should be a bzr meta line "***"')
            return line[4:-1]

        if first_line is not None:
            action = parse_firstline(first_line)
            first = False
            if action is None:
                return None, [], first_line, False

        lines = []
        for line in self.from_file:
            if first:
                action = parse_firstline(line)
                first = False
                if action is None:
                    return None, [], line, False
            else:
                if line[:3] == '***':
                    return action, lines, line, True
                elif line[:1] == '#':
                    return action, lines, line, False
                lines.append(line)
        return action, lines, None, False
            
    def _read_patches(self):
        next_line = None
        do_continue = True
        while do_continue:
            action, lines, next_line, do_continue = \
                    self._read_one_patch(next_line)
            if action is not None:
                self.info.actions.append((action, lines))
        return next_line

    def _read_footer(self, first_line=None):
        """Read the rest of the meta information.

        :param first_line:  The previous step iterates past what it
                            can handle. That extra line is given here.
        """
        if first_line is not None:
            if self._handle_info_line(first_line, in_footer=True) is not None:
                return
        for line in self.from_file:
            if self._handle_info_line(line, in_footer=True) is not None:
                break


def read_changeset(from_file):
    """Read in a changeset from a filelike object (must have "readline" support), and
    parse it into a Changeset object.
    """
    cr = ChangesetReader(from_file)
    cset = cr.get_changeset()
    for file_id in cset.entries:
        print file_id
        print cset.entries[file_id]

