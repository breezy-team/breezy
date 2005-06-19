#!/usr/bin/env python
"""\
Read in a changeset output, and process it into a Changeset object.
"""

import bzrlib, bzrlib.changeset
import common

class BadChangeset(Exception):
    pass
class MalformedHeader(BadChangeset):
    pass
class MalformedFooter(BadChangeset):
    pass


class ChangesetInfo(object):
    """This is the intermediate class that gets filled out as the file is read.
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
        self.directory_ids = None
        self.parent_ids = None

        self.actions = [] #this is the list of things that happened
        self.id2path = {} # A mapping from file id to path name
        self.path2id = {} # The reverse mapping
        self.id2parent = {} # A mapping from a given id to it's parent id

    def __str__(self):
        import pprint
        return pprint.pformat(self.__dict__)

    def create_maps(self):
        """Go through the individual id sections, and generate the id2path and path2id maps.
        """
        self.id2path[self.tree_root_id] = ''
        self.path2id[''] = self.tree_root_id
        self.id2parent[self.tree_root_id] = None # There is no parent for the tree_root_id
        for var in (self.file_ids, self.directory_ids, self.parent_ids):
            if var is not None:
                for info in var:
                    path, f_id, parent_id = info.split('\t')
                    self.id2path[f_id] = path
                    self.path2id[path] = f_id
                    self.id2parent[f_id] = parent_id


class ChangesetReader(object):
    """This class reads in a changeset from a file, and returns a Changeset object,
    which can then be applied against a tree.
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
        self._read_footer(next_line)

    def get_changeset(self):
        """Create the actual changeset object.
        """
        self.info.create_maps()
        return self.info

    def _read_header(self):
        """Read the bzr header"""
        header = common.get_header()
        for head_line, line in zip(header, self.from_file):
            if line[:2] != '# ' or line[-1] != '\n' or line[2:-1] != head_line:
                raise MalformedHeader('Did not read the opening header information.')

        for line in self.from_file:
            if self._handle_info_line(line) is not None:
                break

    def _handle_info_line(self, line, in_footer=False):
        """Handle reading a single line.

        This may call itself, in the case that we read_multi, and then had a dangling
        line on the end.
        """
        # The bzr header is terminated with a blank line which does not start with #
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
        else:
            if line[-1:] == ':':
                key = line[:-1]
                value, next_line = self._read_many()
            else:
                raise MalformedHeader('While looking for key: value pairs, did not find the : %r' % (line))

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
        """If a line ends with no entry, that means that it should be followed with
        multiple lines of values.

        This detects the end of the list, because it will be a line that does not
        start with '#    '. Because it has to read that extra line, it returns the
        tuple: (values, next_line)
        """
        values = []
        for line in self.from_file:
            if line[:5] != '#    ':
                return values, line
            values.append(line[5:-1])
        return values, None

    def _read_patches(self):
        for line in self.from_file:
            if line[0] == '#':
                return line

    def _read_footer(self, first_line=None):
        """Read the rest of the meta information.

        :param first_line:  The previous step may iterate passed what it can handle.
                            That extra line can be passed here.
        """
        if first_line is not None:
            self._handle_info_line(first_line, in_footer=True)
        for line in self.from_file:
            if self._handle_info_line(line, in_footer=True) is not None:
                break


def read_changeset(from_file):
    """Read in a changeset from a filelike object (must have "readline" support), and
    parse it into a Changeset object.
    """
    cr = ChangesetReader(from_file)
    print cr.get_changeset()

