#!/usr/bin/env python
"""\
Just some work for generating a changeset.
"""

import bzrlib, bzrlib.errors

import common

from bzrlib.inventory import ROOT_ID

try:
    set
except NameError:
    from sets import Set as set

def _canonicalize_revision(branch, revno):
    """Turn some sort of revision information into a single
    set of from-to revision ids.

    A revision id can be None if there is no associated revison.

    :return: (old, new)
    """
    # This is a little clumsy because revision parsing may return
    # a single entry, or a list
    if revno is None:
        new = branch.last_patch()
    else:
        new = branch.lookup_revision(revno)

    if new is None:
        raise BzrCommandError('Cannot generate a changset with no commits in tree.')

    old = branch.get_revision(new).precursor

    return old, new

def _get_trees(branch, revisions):
    """Get the old and new trees based on revision.
    """
    if revisions[0] is None:
        if hasattr(branch, 'get_root_id'): # Watch out for trees with labeled ROOT ids
            old_tree = EmptyTree(branch.get_root_id) 
        else:
            old_tree = EmptyTree()
    else:
        old_tree = branch.revision_tree(revisions[0])

    if revisions[1] is None:
        # This is for the future, once we support rollup revisions
        # Or working tree revisions
        new_tree = branch.working_tree()
    else:
        new_tree = branch.revision_tree(revisions[1])
    return old_tree, new_tree

def _fake_working_revision(branch):
    """Fake a Revision object for the working tree.
    
    This is for the future, to support changesets against the working tree.
    """
    from bzrlib.revision import Revision
    import time
    from bzrlib.osutils import local_time_offset, \
            username

    precursor = branch.last_patch()
    precursor_sha1 = branch.get_revision_sha1(precursor)

    return Revision(timestamp=time.time(),
            timezone=local_time_offset(),
            committer=username(),
            precursor=precursor,
            precursor_sha1=precursor_sha1)


class MetaInfoHeader(object):
    """Maintain all of the header information about this
    changeset.
    """

    def __init__(self, branch, revisions, delta,
            full_remove=False, full_rename=False,
            external_diff_options = None,
            new_tree=None, old_tree=None,
            old_label = '', new_label = ''):
        """
        :param full_remove: Include the full-text for a delete
        :param full_rename: Include an add+delete patch for a rename
        """
        self.branch = branch
        self.delta = delta
        self.full_remove=full_remove
        self.full_rename=full_rename
        self.external_diff_options = external_diff_options
        self.old_label = old_label
        self.new_label = new_label
        self.old_tree = old_tree
        self.new_tree = new_tree
        self.to_file = None
        self.revno = None
        self.precursor_revno = None

        self._get_revision_list(revisions)

    def _get_revision_list(self, revisions):
        """This generates the list of all revisions from->to.

        This is for the future, when we support having a rollup changeset.
        For now, the list should only be one long.
        """
        old_revno = None
        new_revno = None
        rh = self.branch.revision_history()
        for revno, rev in enumerate(rh):
            if rev == revisions[0]:
                old_revno = revno
            if rev == revisions[1]:
                new_revno = revno

        self.revision_list = []
        if old_revno is None:
            self.base_revision = None # Effectively the EmptyTree()
            old_revno = 0
        else:
            self.base_revision = self.branch.get_revision(rh[old_revno])
        if new_revno is None:
            # For the future, when we support working tree changesets.
            for rev_id in rh[old_revno+1:]:
                self.revision_list.append(self.branch.get_revision(rev_id))
            self.revision_list.append(_fake_working_revision(self.branch))
        else:
            for rev_id in rh[old_revno+1:new_revno+1]:
                self.revision_list.append(self.branch.get_revision(rev_id))
        self.precursor_revno = old_revno
        self.revno = new_revno

    def _write(self, txt, key=None):
        if key:
            self.to_file.write('# ' + key + ': ' + txt + '\n')
        else:
            self.to_file.write('# ' + txt + '\n')

    def write_meta_info(self, to_file):
        """Write out the meta-info portion to the supplied file.

        :param to_file: Write out the meta information to the supplied
                        file
        """
        self.to_file = to_file

        self._write_header()
        self._write_diffs()
        self._write_footer()

    def _write_header(self):
        """Write the stuff that comes before the patches."""
        from bzrlib.osutils import username, format_date
        write = self._write

        for line in common.get_header():
            write(line)

        # This grabs the current username, what we really want is the
        # username from the actual patches.
        #write(username(), key='committer')
        assert len(self.revision_list) == 1
        rev = self.revision_list[0]
        write(rev.committer, key='committer')
        write(format_date(rev.timestamp, offset=rev.timezone), key='date')
        write(str(self.revno), key='revno')
        write(rev.revision_id, key='revision')

        if self.base_revision:
            write(self.base_revision.revision_id, key='precursor')
            write(str(self.precursor_revno), key='precursor revno')


        write('')
        self.to_file.write('\n')

    def _write_footer(self):
        """Write the stuff that comes after the patches.

        This is meant to be more meta-information, which people probably don't want
        to read, but which is required for proper bzr operation.
        """
        write = self._write

        write('BEGIN BZR FOOTER')

        assert len(self.revision_list) == 1 # We only handle single revision entries
        write(self.branch.get_revision_sha1(self.revision_list[0].revision_id), key='revision sha1')
        if self.base_revision:
            write(self.branch.get_revision_sha1(self.base_revision.revision_id), 'precursor sha1')

        self._write_ids()

        write('END BZR FOOTER')

    def _write_revisions(self):
        """Not used. Used for writing multiple revisions."""
        first = True
        for rev in self.revision_list:
            if rev.revision_id is not None:
                if first:
                    self._write('revisions:')
                    first = False
                self._write(' '*4 + rev.revision_id + '\t' + self.branch.get_revision_sha1(rev.revision_id))


    def _write_ids(self):
        if hasattr(self.branch, 'get_root_id'):
            root_id = self.branch.get_root_id()
        else:
            root_id = ROOT_ID
        seen_ids = set([root_id])
        need_ids = set()

        to_file = self.to_file

        def _write_entry(file_id, path=None):
            if file_id in self.new_tree.inventory:
                ie = self.new_tree.inventory[file_id]
            elif file_id in self.old_tree.inventory:
                ie = self.new_tree.inventory[file_id]
            else:
                ie = None
            if not path and ie:
                path = ie.name
            to_file.write(path.encode('utf-8'))
            to_file.write('\t')
            to_file.write(file_id.encode('utf-8'))
            if ie and ie.parent_id:
                to_file.write('\t')
                to_file.write(ie.parent_id.encode('utf-8'))
                if ie.parent_id not in seen_ids:
                    need_ids.add(ie.parent_id)
            seen_ids.add(ie.file_id)
            to_file.write('\n')

        class _write_kind(object):
            def __init__(self, kind):
                self.first = True
                self.kind = kind
            def __call__(self, info):
                if self.first:
                    self.first = False
                    to_file.write('# %s ids:\n' % self.kind)
                to_file.write('#    ')
                _write_entry(info[1], info[0])

        def _write_all(kind):
            writer = _write_kind(kind)
            for info in self.delta.removed:
                if info[2] == kind:
                    writer(info)
            for info in self.delta.added:
                if info[2] == kind:
                    writer(info)
            for info in self.delta.renamed:
                if info[3] == kind:
                    writer(info[1:3])
            for info in self.delta.modified:
                if info[2] == kind:
                    writer(info)

        self._write(root_id, key='tree root id')

        _write_all('file')
        _write_all('directory')

        first = True
        while len(need_ids) > 0:
            file_id = need_ids.pop()
            if file_id in seen_ids:
                continue
            seen_ids.add(file_id)
            if first:
                self.to_file.write('# parent ids: ')
                first = False
            else:
                to_file.write('#             ')
            _write_entry(file_id)


    def _write_diffs(self):
        """Write out the specific diffs"""
        from bzrlib.diff import internal_diff, external_diff
        DEVNULL = '/dev/null'

        if self.external_diff_options:
            assert isinstance(self.external_diff_options, basestring)
            opts = self.external_diff_options.split()
            def diff_file(olab, olines, nlab, nlines, to_file):
                external_diff(olab, olines, nlab, nlines, to_file, opts)
        else:
            diff_file = internal_diff

        for path, file_id, kind in self.delta.removed:
            print >>self.to_file, '*** removed %s %r' % (kind, path)
            if kind == 'file' and self.full_remove:
                diff_file(self.old_label + path,
                          self.old_tree.get_file(file_id).readlines(),
                          DEVNULL, 
                          [],
                          self.to_file)
    
        for path, file_id, kind in self.delta.added:
            print >>self.to_file, '*** added %s %r' % (kind, path)
            if kind == 'file':
                diff_file(DEVNULL,
                          [],
                          self.new_label + path,
                          self.new_tree.get_file(file_id).readlines(),
                          self.to_file)
    
        for old_path, new_path, file_id, kind, text_modified in self.delta.renamed:
            print >>self.to_file, '*** renamed %s %r => %r' % (kind, old_path, new_path)
            if self.full_rename and kind == 'file':
                diff_file(self.old_label + old_path,
                          self.old_tree.get_file(file_id).readlines(),
                          DEVNULL, 
                          [],
                          self.to_file)
                diff_file(DEVNULL,
                          [],
                          self.new_label + new_path,
                          self.new_tree.get_file(file_id).readlines(),
                          self.to_file)
            elif text_modified:
                    diff_file(self.old_label + old_path,
                              self.old_tree.get_file(file_id).readlines(),
                              self.new_label + new_path,
                              self.new_tree.get_file(file_id).readlines(),
                              self.to_file)
    
        for path, file_id, kind in self.delta.modified:
            print >>self.to_file, '*** modified %s %r' % (kind, path)
            if kind == 'file':
                diff_file(self.old_label + path,
                          self.old_tree.get_file(file_id).readlines(),
                          self.new_label + path,
                          self.new_tree.get_file(file_id).readlines(),
                          self.to_file)

def show_changeset(branch, revision=None, specific_files=None,
        external_diff_options=None, to_file=None,
        include_full_diff=False):
    from bzrlib.diff import compare_trees

    if to_file is None:
        import sys
        to_file = sys.stdout
    revisions = _canonicalize_revision(branch, revision)

    old_tree, new_tree = _get_trees(branch, revisions)

    delta = compare_trees(old_tree, new_tree, want_unchanged=False,
                          specific_files=specific_files)

    meta = MetaInfoHeader(branch, revisions, delta,
            external_diff_options=external_diff_options,
            old_tree=old_tree, new_tree=new_tree)
    meta.write_meta_info(to_file)


