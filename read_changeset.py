#!/usr/bin/env python
"""\
Read in a changeset output, and process it into a Changeset object.
"""

import bzrlib, bzrlib.changeset
import pprint
import common

from bzrlib.trace import mutter

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

class RevisionInfo(object):
    """Gets filled out for each revision object that is read.
    """
    def __init__(self, rev_id):
        self.rev_id = rev_id
        self.sha1 = None
        self.committer = None
        self.date = None
        self.timestamp = None
        self.timezone = None
        self.inventory_id = None
        self.inventory_sha1 = None

        self.parents = None
        self.message = None

    def __str__(self):
        return pprint.pformat(self.__dict__)

    def as_revision(self):
        from bzrlib.revision import Revision, RevisionReference
        rev = Revision(revision_id=self.rev_id,
            committer=self.committer,
            timestamp=float(self.timestamp),
            timezone=int(self.timezone),
            inventory_id=self.inventory_id,
            inventory_sha1=self.inventory_sha1,
            message='\n'.join(self.message))

        if self.parents:
            for parent in self.parents:
                rev_id, sha1 = parent.split('\t')
                rev.parents.append(RevisionReference(rev_id, sha1))

        return rev

class ChangesetInfo(object):
    """This contains the meta information. Stuff that allows you to
    recreate the revision or inventory XML.
    """
    def __init__(self):
        self.committer = None
        self.date = None
        self.message = None
        self.base = None
        self.base_sha1 = None

        # A list of RevisionInfo objects
        self.revisions = []

        self.actions = []

        # The next entries are created during complete_info() and
        # other post-read functions.

        # A list of real Revision objects
        self.real_revisions = []
        self.text_ids = {} # file_id => text_id

        self.timestamp = None
        self.timezone = None

    def __str__(self):
        return pprint.pformat(self.__dict__)

    def complete_info(self):
        """This makes sure that all information is properly
        split up, based on the assumptions that can be made
        when information is missing.
        """
        # Put in all of the guessable information.
        if not self.timestamp and self.date:
            self.timestamp, self.timezone = common.unpack_highres_date(self.date)

        self.real_revisions = []
        for rev in self.revisions:
            if rev.timestamp is None:
                if rev.date is not None:
                    rev.timestamp, rev.timezone = \
                            common.unpack_highres_date(rev.date)
                else:
                    rev.timestamp = self.timestamp
                    rev.timezone = self.timezone
            if rev.message is None and self.message:
                rev.message = self.message
            if rev.committer is None and self.committer:
                rev.committer = self.committer
            if rev.inventory_id is None:
                rev.inventory_id = rev.rev_id
            self.real_revisions.append(rev.as_revision())

        if self.base is None:
            # When we don't have a base, then the real base
            # is the first parent of the first revision listed
            rev = self.real_revisions[0]
            if len(rev.parents) == 0:
                # There is no base listed, and
                # the lowest revision doesn't have a parent
                # so this is probably against the empty tree
                # and thus base truly is None
                self.base = None
                self.base_sha1 = None
            else:
                self.base = rev.parents[0].revision_id
                # In general, if self.base is None, self.base_sha1 should
                # also be None
                if self.base_sha1 is not None:
                    assert self.base_sha1 == rev.parents[0].revision_sha1
                self.base_sha1 = rev.parents[0].revision_sha1



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
        self._next_line = None
        
        self.info = ChangesetInfo()
        # We put the actual inventory ids in the footer, so that the patch
        # is easier to read for humans.
        # Unfortunately, that means we need to read everything before we
        # can create a proper changeset.
        self._read_header()
        self._read_patches()
        self._read_footer()

    def get_info_and_tree(self, branch):
        """Return the meta information, and a Changeset tree which can
        be used to populate the local stores and working tree, respectively.
        """
        self.info.complete_info()
        if self.info.base:
            store_base_sha1 = branch.get_revision_sha1(self.info.base) 
        else:
            store_base_sha1 = None
        if store_base_sha1 != self.info.base_sha1:
            raise BzrError('Base revision sha1 hash in store'
                    ' does not match the one read in the changeset'
                    ' (%s != %s)' % (store_base_sha1, self.info.base_sha1))
        tree = ChangesetTree(branch.revision_tree(self.info.base))
        self._update_tree(tree)

        return self.info, tree

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

    def _read_header(self):
        """Read the bzr header"""
        header = common.get_header()
        found = False
        for line in self._next():
            if found:
                if (line[:2] != '# ' or line[-1:] != '\n'
                        or line[2:-1] != header[0]):
                    raise MalformedHeader('Found a header, but it'
                        ' was improperly formatted')
                header.pop(0) # We read this line.
                if not header:
                    break # We found everything.
            elif (line[:1] == '#' and line[-1:] == '\n'):
                line = line[1:-1].strip()
                if line[:len(common.header_str)] == common.header_str:
                    if line == header[0]:
                        found = True
                    else:
                        raise MalformedHeader('Found what looks like'
                                ' a header, but did not match')
                    header.pop(0)
        else:
            raise MalformedHeader('Did not find an opening header')

        for line in self._next():
            # The bzr header is terminated with a blank line
            # which does not start with '#'
            if line == '\n':
                break
            self._handle_next(line)

    def _read_next_entry(self, line, indent=1):
        """Read in a key-value pair
        """
        if line[:1] != '#':
            raise MalformedHeader('Bzr header did not start with #')
        line = line[1:-1] # Remove the '#' and '\n'
        if line[:indent] == ' '*indent:
            line = line[indent:]
        if not line:
            return None, None# Ignore blank lines

        loc = line.find(': ')
        if loc != -1:
            key = line[:loc]
            value = line[loc+2:]
            if not value:
                value = self._read_many(indent=indent+3)
        elif line[-1:] == ':':
            key = line[:-1]
            value = self._read_many(indent=indent+3)
        else:
            raise MalformedHeader('While looking for key: value pairs,'
                    ' did not find the colon %r' % (line))

        key = key.replace(' ', '_')
        #mutter('found %s: %s' % (key, value))
        return key, value

    def _handle_next(self, line):
        key, value = self._read_next_entry(line, indent=1)
        if key is None:
            return

        if key == 'revision':
            self._read_revision(value)
        elif hasattr(self.info, key):
            if getattr(self.info, key) is None:
                setattr(self.info, key, value)
            else:
                raise MalformedHeader('Duplicated Key: %s' % key)
        else:
            # What do we do with a key we don't recognize
            raise MalformedHeader('Unknown Key: %s' % key)
        
    def _read_many(self, indent):
        """If a line ends with no entry, that means that it should be
        followed with multiple lines of values.

        This detects the end of the list, because it will be a line that
        does not start properly indented.
        """
        values = []
        start = '#' + (' '*indent)

        if self._next_line is None or self._next_line[:len(start)] != start:
            return values

        for line in self._next():
            values.append(line[len(start):-1])
            if self._next_line is None or self._next_line[:len(start)] != start:
                break
        return values

    def _read_one_patch(self):
        """Read in one patch, return the complete patch, along with
        the next line.

        :return: action, lines, do_continue
        """
        #mutter('_read_one_patch: %r' % self._next_line)
        # Peek and see if there are no patches
        if self._next_line is None or self._next_line[:1] == '#':
            return None, [], False

        line = self._next().next()
        if line[:3] != '***':
            raise MalformedPatches('The first line of all patches'
                ' should be a bzr meta line "***"'
                ': %r' % line)
        action = line[4:-1]

        if self._next_line is None or self._next_line[:1] == '#':
            return action, [], False
        lines = []
        for line in self._next():
            lines.append(line)

            if self._next_line is not None and self._next_line[:3] == '***':
                return action, lines, True
            elif self._next_line is None or self._next_line[:1] == '#':
                return action, lines, False
        return action, lines, False
            
    def _read_patches(self):
        do_continue = True
        while do_continue:
            action, lines, do_continue = self._read_one_patch()
            if action is not None:
                self.info.actions.append((action, lines))

    def _read_revision(self, rev_id):
        """Revision entries have extra information associated.
        """
        rev_info = RevisionInfo(rev_id)
        start = '#    '
        for line in self._next():
            key,value = self._read_next_entry(line, indent=4)
            #if key is None:
            #    continue
            if hasattr(rev_info, key):
                if getattr(rev_info, key) is None:
                    setattr(rev_info, key, value)
                else:
                    raise MalformedHeader('Duplicated Key: %s' % key)
            else:
                # What do we do with a key we don't recognize
                raise MalformedHeader('Unknown Key: %s' % key)

            if self._next_line is None or self._next_line[:len(start)] != start:
                break

        self.info.revisions.append(rev_info)

    def _read_footer(self):
        """Read the rest of the meta information.

        :param first_line:  The previous step iterates past what it
                            can handle. That extra line is given here.
        """
        for line in self._next():
            self._handle_next(line)
            if self._next_line is None or self._next_line[:1] != '#':
                break

    def _update_tree(self, tree):
        """This fills out a ChangesetTree based on the information
        that was read in.

        :param tree: A ChangesetTree to update with the new information.
        """
        from bzrlib.errors import BzrError
        from common import decode

        def get_text_id(info, file_id):
            if info is not None:
                if info[:8] != 'text-id:':
                    raise BzrError("Text ids should be prefixed with 'text-id:'"
                        ': %r' % info)
                text_id = decode(info[8:])
            elif self.info.text_ids.has_key(file_id):
                return self.info.text_ids[file_id]
            else:
                # If text_id was not explicitly supplied
                # then it should be whatever we would guess it to be
                # based on the base revision, and what we know about
                # the target revision
                text_id = common.guess_text_id(tree.base_tree, 
                        file_id, self.info.base, True)
            if (self.info.text_ids.has_key(file_id)
                    and self.info.text_ids[file_id] != text_id):
                raise BzrError('Mismatched text_ids for file_id {%s}'
                        ': %s != %s' % (file_id,
                                        self.info.text_ids[file_id],
                                        text_id))
            # The Info object makes more sense for where
            # to store something like text_id, since it is
            # what will be used to generate stored inventory
            # entries.
            # The problem is that we are parsing the
            # ChangesetTree right now, we really modifying
            # the ChangesetInfo object
            self.info.text_ids[file_id] = text_id
            return text_id

        def renamed(kind, extra, lines):
            info = extra.split('\t')
            if len(info) < 2:
                raise BzrError('renamed action lines need both a from and to'
                        ': %r' % extra)
            old_path = decode(info[0])
            if info[1][:3] == '=> ':
                new_path = decode(info[1][3:])
            else:
                new_path = decode(info[1][3:])

            file_id = tree.path2id(new_path)
            if len(info) > 2:
                text_id = get_text_id(info[2], file_id)
            else:
                text_id = get_text_id(None, file_id)
            tree.note_rename(old_path, new_path)
            if lines:
                tree.note_patch(new_path, lines)

        def removed(kind, extra, lines):
            info = extra.split('\t')
            if len(info) > 1:
                # TODO: in the future we might allow file ids to be
                # given for removed entries
                raise BzrError('removed action lines should only have the path'
                        ': %r' % extra)
            path = decode(info[0])
            tree.note_deletion(path)

        def added(kind, extra, lines):
            info = extra.split('\t')
            if len(info) <= 1:
                raise BzrError('add action lines require the path and file id'
                        ': %r' % extra)
            elif len(info) > 3:
                raise BzrError('add action lines have fewer than 3 entries.'
                        ': %r' % extra)
            path = decode(info[0])
            if info[1][:8] != 'file-id:':
                raise BzrError('The file-id should follow the path for an add'
                        ': %r' % extra)
            file_id = decode(info[1][8:])

            if len(info) > 2:
                text_id = get_text_id(info[2], file_id)
            else:
                text_id = get_text_id(None, file_id)
            tree.note_id(file_id, path)
            tree.note_patch(path, lines)

        def modified(kind, extra, lines):
            info = extra.split('\t')
            if len(info) < 1:
                raise BzrError('modified action lines have at least'
                        'the path in them: %r' % extra)
            path = decode(info[0])

            file_id = tree.path2id(path)
            if len(info) > 1:
                text_id = get_text_id(info[1], file_id)
            else:
                text_id = get_text_id(None, file_id)
            tree.note_patch(path, lines)
            

        valid_actions = {
            'renamed':renamed,
            'removed':removed,
            'added':added,
            'modified':modified
        }
        for action_line, lines in self.info.actions:
            first = action_line.find(' ')
            if first == -1:
                raise BzrError('Bogus action line'
                        ' (no opening space): %r' % action_line)
            second = action_line.find(' ', first+1)
            if second == -1:
                raise BzrError('Bogus action line'
                        ' (missing second space): %r' % action_line)
            action = action_line[:first]
            kind = action_line[first+1:second]
            if kind not in ('file', 'directory'):
                raise BzrError('Bogus action line'
                        ' (invalid object kind %r): %r' % (kind, action_line))
            extra = action_line[second+1:]

            if action not in valid_actions:
                raise BzrError('Bogus action line'
                        ' (unrecognized action): %r' % action_line)
            valid_actions[action](kind, extra, lines)

def read_changeset(from_file, branch):
    """Read in a changeset from a iterable object (such as a file object)

    :param from_file: A file-like object to read the changeset information.
    :param branch: This will be used to build the changeset tree, it needs
                   to contain the base of the changeset. (Which you probably
                   won't know about until after the changeset is parsed.)
    """
    cr = ChangesetReader(from_file)
    return cr.get_info_and_tree(branch)

class ChangesetTree:
    def __init__(self, base_tree=None):
        self.base_tree = base_tree
        self._renamed = {} # Mapping from old_path => new_path
        self._renamed_r = {} # new_path => old_path
        self._new_id = {} # new_path => new_id
        self._new_id_r = {} # new_id => new_path
        self.patches = {}
        self.deleted = []
        self.contents_by_id = True

    def __str__(self):
        return pprint.pformat(self.__dict__)

    def note_rename(self, old_path, new_path):
        """A file/directory has been renamed from old_path => new_path"""
        assert not self._renamed.has_key(old_path)
        assert not self._renamed_r.has_key(new_path)
        self._renamed[new_path] = old_path
        self._renamed_r[old_path] = new_path

    def note_id(self, new_id, new_path):
        """Files that don't exist in base need a new id."""
        self._new_id[new_path] = new_id
        self._new_id_r[new_id] = new_path

    def note_patch(self, new_path, patch):
        """There is a patch for a given filename."""
        self.patches[new_path] = patch

    def note_deletion(self, old_path):
        """The file at old_path has been deleted."""
        self.deleted.append(old_path)

    def old_path(self, new_path):
        """Get the old_path (path in the base_tree) for the file at new_path"""
        import os.path
        old_path = self._renamed.get(new_path)
        if old_path is not None:
            return old_path
        dirname,basename = os.path.split(new_path)
        # dirname is not '' doesn't work, because
        # dirname may be a unicode entry, and is
        # requires the objects to be identical
        if dirname != '':
            old_dir = self.old_path(dirname)
            if old_dir is None:
                old_path = None
            else:
                old_path = os.path.join(old_dir, basename)
        else:
            old_path = new_path
        #If the new path wasn't in renamed, the old one shouldn't be in
        #renamed_r
        if self._renamed_r.has_key(old_path):
            return None
        return old_path 


    def new_path(self, old_path):
        """Get the new_path (path in the target_tree) for the file at old_path
        in the base tree.
        """
        import os.path
        new_path = self._renamed_r.get(old_path)
        if new_path is not None:
            return new_path
        if self._renamed.has_key(new_path):
            return None
        dirname,basename = os.path.split(old_path)
        if dirname is not '':
            new_dir = self.new_path(dirname)
            if new_dir is None:
                new_path = None
            else:
                new_path = os.path.join(new_dir, basename)
        else:
            new_path = old_path
        #If the old path wasn't in renamed, the new one shouldn't be in
        #renamed_r
        if self._renamed.has_key(new_path):
            return None
        return new_path 

    def path2id(self, path):
        """Return the id of the file present at path in the target tree."""
        file_id = self._new_id.get(path)
        if file_id is not None:
            return file_id
        old_path = self.old_path(path)
        if old_path is None:
            return None
        if old_path in self.deleted:
            return None
        return self.base_tree.inventory.path2id(old_path)

    def id2path(self, file_id):
        """Return the new path in the target tree of the file with id file_id"""
        path = self._new_id_r.get(file_id)
        if path is not None:
            return path
        old_path = self.base_tree.id2path(file_id)
        if old_path is None:
            return None
        if old_path in self.deleted:
            return None
        return self.new_path(old_path)

    def old_contents_id(self, file_id):
        """Return the id in the base_tree for the given file_id,
        or None if the file did not exist in base.

        FIXME:  Something doesn't seem right here. It seems like this function
                should always either return None or file_id. Even if
                you are doing the by-path lookup, you are doing a
                id2path lookup, just to do the reverse path2id lookup.
        """
        if self.contents_by_id:
            if self.base_tree.has_id(file_id):
                return file_id
            else:
                return None
        new_path = self.id2path(file_id)
        return self.base_tree.path2id(new_path)
        
    def get_file(self, file_id):
        """Return a file-like object containing the new contents of the
        file given by file_id.

        TODO:   It might be nice if this actually generated an entry
                in the text-store, so that the file contents would
                then be cached.
        """
        base_id = self.old_contents_id(file_id)
        if base_id is not None:
            patch_original = self.base_tree.get_file(base_id)
        else:
            patch_original = None
        file_patch = self.patches.get(self.id2path(file_id))
        if file_patch is None:
            return patch_original
        return patched_file(file_patch, patch_original)

    def __iter__(self):
        for file_id in self._new_id_r.iterkeys():
            yield file_id
        for file_id in self.base_tree:
            if self.id2path(file_id) is None:
                continue
            yield file_id


def patched_file(file_patch, original):
    from bzrlib.patch import patch
    from tempfile import mkdtemp
    from shutil import rmtree
    from StringIO import StringIO
    from bzrlib.osutils import pumpfile
    import os.path
    temp_dir = mkdtemp()
    try:
        original_path = os.path.join(temp_dir, "originalfile")
        temp_original = file(original_path, "wb")
        if original is not None:
            pumpfile(original, temp_original)
        temp_original.close()
        patched_path = os.path.join(temp_dir, "patchfile")
        assert patch(file_patch, original_path, patched_path) == 0
        result = StringIO()
        temp_patched = file(patched_path, "rb")
        pumpfile(temp_patched, result)
        temp_patched.close()
        result.seek(0,0)

    finally:
        rmtree(temp_dir)

    return result

def test():
    import unittest
    from StringIO import StringIO
    from bzrlib.diff import internal_diff
    class MockTree(object):
        def __init__(self):
            object.__init__(self)
            self.paths = {}
            self.ids = {}
            self.contents = {}

        def __iter__(self):
            return self.paths.iterkeys()

        def add_dir(self, file_id, path):
            self.paths[file_id] = path
            self.ids[path] = file_id
        
        def add_file(self, file_id, path, contents):
            self.add_dir(file_id, path)
            self.contents[file_id] = contents

        def path2id(self, path):
            return self.ids.get(path)

        def id2path(self, file_id):
            return self.paths.get(file_id)

        def has_id(self, file_id):
            return self.id2path(file_id) is not None

        def get_file(self, file_id):
            result = StringIO()
            result.write(self.contents[file_id])
            result.seek(0,0)
            return result

    class CTreeTester(unittest.TestCase):

        def make_tree_1(self):
            mtree = MockTree()
            mtree.add_dir("a", "grandparent")
            mtree.add_dir("b", "grandparent/parent")
            mtree.add_file("c", "grandparent/parent/file", "Hello\n")
            mtree.add_dir("d", "grandparent/alt_parent")
            return ChangesetTree(mtree), mtree
            
        def test_renames(self):
            """Ensure that file renames have the proper effect on children"""
            ctree = self.make_tree_1()[0]
            self.assertEqual(ctree.old_path("grandparent"), "grandparent")
            self.assertEqual(ctree.old_path("grandparent/parent"), "grandparent/parent")
            self.assertEqual(ctree.old_path("grandparent/parent/file"),
                "grandparent/parent/file")

            self.assertEqual(ctree.id2path("a"), "grandparent")
            self.assertEqual(ctree.id2path("b"), "grandparent/parent")
            self.assertEqual(ctree.id2path("c"), "grandparent/parent/file")

            self.assertEqual(ctree.path2id("grandparent"), "a")
            self.assertEqual(ctree.path2id("grandparent/parent"), "b")
            self.assertEqual(ctree.path2id("grandparent/parent/file"), "c")

            self.assertEqual(ctree.path2id("grandparent2"), None)
            self.assertEqual(ctree.path2id("grandparent2/parent"), None)
            self.assertEqual(ctree.path2id("grandparent2/parent/file"), None)

            ctree.note_rename("grandparent", "grandparent2")
            self.assertEqual(ctree.old_path("grandparent"), None)
            self.assertEqual(ctree.old_path("grandparent/parent"), None)
            self.assertEqual(ctree.old_path("grandparent/parent/file"), None)

            self.assertEqual(ctree.id2path("a"), "grandparent2")
            self.assertEqual(ctree.id2path("b"), "grandparent2/parent")
            self.assertEqual(ctree.id2path("c"), "grandparent2/parent/file")

            self.assertEqual(ctree.path2id("grandparent2"), "a")
            self.assertEqual(ctree.path2id("grandparent2/parent"), "b")
            self.assertEqual(ctree.path2id("grandparent2/parent/file"), "c")

            self.assertEqual(ctree.path2id("grandparent"), None)
            self.assertEqual(ctree.path2id("grandparent/parent"), None)
            self.assertEqual(ctree.path2id("grandparent/parent/file"), None)

            ctree.note_rename("grandparent/parent", "grandparent2/parent2")
            self.assertEqual(ctree.id2path("a"), "grandparent2")
            self.assertEqual(ctree.id2path("b"), "grandparent2/parent2")
            self.assertEqual(ctree.id2path("c"), "grandparent2/parent2/file")

            self.assertEqual(ctree.path2id("grandparent2"), "a")
            self.assertEqual(ctree.path2id("grandparent2/parent2"), "b")
            self.assertEqual(ctree.path2id("grandparent2/parent2/file"), "c")

            self.assertEqual(ctree.path2id("grandparent2/parent"), None)
            self.assertEqual(ctree.path2id("grandparent2/parent/file"), None)

            ctree.note_rename("grandparent/parent/file", 
                              "grandparent2/parent2/file2")
            self.assertEqual(ctree.id2path("a"), "grandparent2")
            self.assertEqual(ctree.id2path("b"), "grandparent2/parent2")
            self.assertEqual(ctree.id2path("c"), "grandparent2/parent2/file2")

            self.assertEqual(ctree.path2id("grandparent2"), "a")
            self.assertEqual(ctree.path2id("grandparent2/parent2"), "b")
            self.assertEqual(ctree.path2id("grandparent2/parent2/file2"), "c")

            self.assertEqual(ctree.path2id("grandparent2/parent2/file"), None)

        def test_moves(self):
            """Ensure that file moves have the proper effect on children"""
            ctree = self.make_tree_1()[0]
            ctree.note_rename("grandparent/parent/file", 
                              "grandparent/alt_parent/file")
            self.assertEqual(ctree.id2path("c"), "grandparent/alt_parent/file")
            self.assertEqual(ctree.path2id("grandparent/alt_parent/file"), "c")
            self.assertEqual(ctree.path2id("grandparent/parent/file"), None)

        def unified_diff(self, old, new):
            out = StringIO()
            internal_diff("old", old, "new", new, out)
            out.seek(0,0)
            return out.read()

        def make_tree_2(self):
            ctree = self.make_tree_1()[0]
            ctree.note_rename("grandparent/parent/file", 
                              "grandparent/alt_parent/file")
            self.assertEqual(ctree.id2path("e"), None)
            self.assertEqual(ctree.path2id("grandparent/parent/file"), None)
            ctree.note_id("e", "grandparent/parent/file")
            return ctree

        def test_adds(self):
            """File/inventory adds"""
            ctree = self.make_tree_2()
            add_patch = self.unified_diff([], ["Extra cheese\n"])
            ctree.note_patch("grandparent/parent/file", add_patch)
            self.adds_test(ctree)

        def adds_test(self, ctree):
            self.assertEqual(ctree.id2path("e"), "grandparent/parent/file")
            self.assertEqual(ctree.path2id("grandparent/parent/file"), "e")
            self.assertEqual(ctree.get_file("e").read(), "Extra cheese\n")

        def test_adds2(self):
            """File/inventory adds, with patch-compatibile renames"""
            ctree = self.make_tree_2()
            ctree.contents_by_id = False
            add_patch = self.unified_diff(["Hello\n"], ["Extra cheese\n"])
            ctree.note_patch("grandparent/parent/file", add_patch)
            self.adds_test(ctree)

        def make_tree_3(self):
            ctree, mtree = self.make_tree_1()
            mtree.add_file("e", "grandparent/parent/topping", "Anchovies\n")
            ctree.note_rename("grandparent/parent/file", 
                              "grandparent/alt_parent/file")
            ctree.note_rename("grandparent/parent/topping", 
                              "grandparent/alt_parent/stopping")
            return ctree

        def get_file_test(self, ctree):
            self.assertEqual(ctree.get_file("e").read(), "Lemon\n")
            self.assertEqual(ctree.get_file("c").read(), "Hello\n")

        def test_get_file(self):
            """Get file contents"""
            ctree = self.make_tree_3()
            mod_patch = self.unified_diff(["Anchovies\n"], ["Lemon\n"])
            ctree.note_patch("grandparent/alt_parent/stopping", mod_patch)
            self.get_file_test(ctree)

        def test_get_file2(self):
            """Get file contents, with patch-compatibile renames"""
            ctree = self.make_tree_3()
            ctree.contents_by_id = False
            mod_patch = self.unified_diff([], ["Lemon\n"])
            ctree.note_patch("grandparent/alt_parent/stopping", mod_patch)
            mod_patch = self.unified_diff([], ["Hello\n"])
            ctree.note_patch("grandparent/alt_parent/file", mod_patch)
            self.get_file_test(ctree)

        def test_delete(self):
            "Deletion by changeset"
            ctree = self.make_tree_1()[0]
            self.assertEqual(ctree.get_file("c").read(), "Hello\n")
            ctree.note_deletion("grandparent/parent/file")
            self.assertEqual(ctree.id2path("c"), None)
            self.assertEqual(ctree.path2id("grandparent/parent/file"), None)

        def sorted_ids(self, tree):
            ids = list(tree)
            ids.sort()
            return ids

        def test_iteration(self):
            """Ensure that iteration through ids works properly"""
            ctree = self.make_tree_1()[0]
            self.assertEqual(self.sorted_ids(ctree), ['a', 'b', 'c', 'd'])
            ctree.note_deletion("grandparent/parent/file")
            ctree.note_id("e", "grandparent/alt_parent/fool")
            self.assertEqual(self.sorted_ids(ctree), ['a', 'b', 'd', 'e'])
            

    patchesTestSuite = unittest.makeSuite(CTreeTester,'test_')
    runner = unittest.TextTestRunner()
    runner.run(patchesTestSuite)

