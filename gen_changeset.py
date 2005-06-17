#!/usr/bin/env python
"""\
Just some work for generating a changeset.
"""

import bzrlib, bzrlib.errors

def _canonicalize_revision(branch, revision=None):
    """Turn some sort of revision information into a single
    set of from-to revision ids.

    A revision id can be none if there is no associated revison.
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
            # Get the ancestor previous version
            rev = branch.get_revision(new)
            old = rev.precursor
        else:
            old = branch.lookup_revision(old)
    else:
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

        if old_revno is None:
            raise bzrlib.errors.BzrError('Could not find revision for %s' % revisions[0])

        self.revision_list = []
        if new_revno is not None:
            for rev_id in rh[old_revno:new_revno+1]:
                self.revision_list.append(self.branch.get_revision(rev_id))
        else:
            for rev_id in rh[old_revno:]:
                self.revision_list.append(self.branch.get_revision(rev_id))
            self.revision_list.append(_fake_working_revision(self.branch))

    def write_meta_info(self, to_file):
        """Write out the meta-info portion to the supplied file."""
        from bzrlib.osutils import username
        def write(key, value):
            to_file.write('# ' + key + ': ' + value + '\n')

        write('committer', username())


def show_changeset(branch, revision=None, specific_files=None,
        external_diff_options=None, to_file=None):
    from bzrlib.diff import compare_trees

    if to_file is None:
        import sys
        to_file = sys.stdout
    revisions = _canonicalize_revision(branch, revision)
    print "Canonicalized revisions: %s" % (revisions,)

    old_tree, new_tree = _get_trees(branch, revisions)

    delta = compare_trees(old_tree, new_tree, want_unchanged=False,
                          specific_files=specific_files)

    meta = MetaInfoHeader(branch, revisions, delta)
    meta.write_meta_info(to_file)


