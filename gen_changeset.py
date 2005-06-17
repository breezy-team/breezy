#!/usr/bin/env python
"""\
Just some work for generating a changeset.
"""

import bzrlib, bzrlib.errors

try:
    set
except NameError:
    from sets import Set as set

def _canonicalize_revision(branch, revision=None):
    """Turn some sort of revision information into a single
    set of from-to revision ids.

    A revision id can be None if there is no associated revison.

    :return: (old, new)
    """
    # This is a little clumsy because revision parsing may return
    # a single entry, or a list
    if revision is None:
        old, new = None, None
    elif isinstance(revision, (list, tuple)):
        if len(revision) == 0:
            old, new = None, None
        elif len(revision) == 1:
            old = revision[0]
            new = None
        elif len(revision) == 2:
            old = revision[0]
            new = revision[1]
        else:
            raise bzrlib.errors.BzrCommandError('revision can be'
                    ' at most 2 entries.')
    else:
        old = revision
        new = None

    if new is not None:
        new = branch.lookup_revision(new)
    if old is None:
        old = branch.last_patch()
    else:
        old = branch.lookup_revision(old)

    return old, new

def _get_trees(branch, revisions):
    """Get the old and new trees based on revision.
    """
    if revisions[0] is None:
        old_tree = branch.basis_tree()
    else:
        old_tree = branch.revision_tree(revisions[0])

    if revisions[1] is None:
        new_tree = branch.working_tree()
    else:
        new_tree = branch.revision_tree(revisions[1])
    return old_tree, new_tree

def _fake_working_revision(branch):
    """Fake a Revision object for the working tree."""
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
        self._get_revision_list(revisions)
        self.full_remove=full_remove
        self.full_rename=full_rename
        self.external_diff_options = external_diff_options
        self.old_label = old_label
        self.new_label = new_label
        self.old_tree = old_tree
        self.new_tree = new_tree

    def _get_revision_list(self, revisions):
        """This generates the list of all revisions from->to.
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
            self.base_revision = None
            old_revno = 1
        else:
            self.base_revision = self.branch.get_revision(rh[old_revno])
        if new_revno is not None:
            for rev_id in rh[old_revno+1:new_revno+1]:
                self.revision_list.append(self.branch.get_revision(rev_id))
        else:
            for rev_id in rh[old_revno+1:]:
                self.revision_list.append(self.branch.get_revision(rev_id))
            self.revision_list.append(_fake_working_revision(self.branch))

    def write_meta_info(self, to_file):
        """Write out the meta-info portion to the supplied file.

        :param to_file: Write out the meta information to the supplied
                        file
        """
        from bzrlib.osutils import username
        def write(txt, key=None):
            if key:
                to_file.write('# ' + key + ': ' + txt + '\n')
            else:
                to_file.write('# ' + txt + '\n')

        write('Bazaar-NG (bzr) changeset v0.0.5')
        write('This changeset can be applied with bzr apply-changeset')
        write('')

        write(username(), key='committer')

        if self.base_revision:
            write(self.base_revision.revision_id, key='precursor')

        first = True
        for rev in self.revision_list:
            if rev.revision_id is not None:
                if first:
                    write(rev.revision_id, key='revisions')
                    first = False
                else:
                    write(' '*11 + rev.revision_id)

        seen_ids = set(['TREE_ROOT'])
        need_ids = set()

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
                    to_file.write('# %s ids: ' % self.kind)
                else:
                    to_file.write('#')
                    to_file.write(' ' * (len(self.kind) + 7))
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
                    writer(info[1:2])
            for info in self.delta.modified:
                if info[2] == kind:
                    writer(info)

        _write_all('file')
        _write_all('directory')

        first = True
        while len(need_ids) > 0:
            file_id = need_ids.pop()
            if file_id in seen_ids:
                continue
            seen_ids.add(file_id)
            if first:
                to_file.write('# parent ids: ')
                first = False
            else:
                to_file.write('#             ')
            _write_entry(file_id)

        self._write_diffs(to_file)

    def _write_diffs(self, to_file):
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
            print >>to_file, '*** removed %s %r' % (kind, path)
            if kind == 'file' and self.full_remove:
                diff_file(self.old_label + path,
                          self.old_tree.get_file(file_id).readlines(),
                          DEVNULL, 
                          [],
                          to_file)
    
        for path, file_id, kind in self.delta.added:
            print >>to_file, '*** added %s %r' % (kind, path)
            if kind == 'file':
                diff_file(DEVNULL,
                          [],
                          self.new_label + path,
                          self.new_tree.get_file(file_id).readlines(),
                          to_file)
    
        for old_path, new_path, file_id, kind, text_modified in self.delta.renamed:
            print >>to_file, '*** renamed %s %r => %r' % (kind, old_path, new_path)
            if self.full_rename and kind == 'file':
                diff_file(self.old_label + old_path,
                          self.old_tree.get_file(file_id).readlines(),
                          DEVNULL, 
                          [],
                          to_file)
                diff_file(DEVNULL,
                          [],
                          self.new_label + new_path,
                          self.new_tree.get_file(file_id).readlines(),
                          to_file)
            elif text_modified:
                    diff_file(self.old_label + old_path,
                              self.old_tree.get_file(file_id).readlines(),
                              self.new_label + new_path,
                              self.new_tree.get_file(file_id).readlines(),
                              to_file)
    
        for path, file_id, kind in self.delta.modified:
            print >>to_file, '*** modified %s %r' % (kind, path)
            if kind == 'file':
                diff_file(self.old_label + path,
                          self.old_tree.get_file(file_id).readlines(),
                          self.new_label + path,
                          self.new_tree.get_file(file_id).readlines(),
                          to_file)

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


