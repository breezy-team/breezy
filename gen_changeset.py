#!/usr/bin/env python
"""\
Just some work for generating a changeset.
"""

import bzrlib, bzrlib.errors

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

    def __init__(self, branch, revisions, delta):
        self.branch = branch
        self.delta = delta
        self._get_revision_list(revisions)

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
        """Write out the meta-info portion to the supplied file."""
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

        if self.revision_list[-1].revision_id is None:
            final_tree = self.branch.working_tree()
        else:
            final_tree = self.branch.revision_tree(
                    self.revision_list[-1])

        class _write_file(object):
            first = True
            def __call__(self, info):
                if self.first:
                    self.first = False
                    to_file.write('# file ids: ')
                else:
                    to_file.write('#           ')
                to_file.write(info[0].encode('utf-8'))
                to_file.write('\t')
                to_file.write(info[1].encode('utf-8'))
                inv = final_tree.inventory[info[1]]
                if inv.parent_id:
                    to_file.write('\t')
                    to_file.write(inv.parent_id)
                to_file.write('\n')
        write_file = _write_file()

        for info in self.delta.removed:
            if info[2] == 'file':
                write_file(info)
        for info in self.delta.added:
            if info[2] == 'file':
                write_file(info)
        for info in self.delta.renamed:
            if info[3] == 'file':
                write_file(info[1:2])
        for info in self.delta.modified:
            if info[2] == 'file':
                write_file(info)


def show_changeset(branch, revision=None, specific_files=None,
        external_diff_options=None, to_file=None):
    from bzrlib.diff import compare_trees

    if to_file is None:
        import sys
        to_file = sys.stdout
    revisions = _canonicalize_revision(branch, revision)

    old_tree, new_tree = _get_trees(branch, revisions)

    delta = compare_trees(old_tree, new_tree, want_unchanged=False,
                          specific_files=specific_files)

    meta = MetaInfoHeader(branch, revisions, delta)
    meta.write_meta_info(to_file)


