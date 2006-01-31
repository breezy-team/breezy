# Copyright (C) 2005 Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""\
Routines for extracting all version information from a bzr branch.
"""

import time
import pprint

from StringIO import StringIO

from bzrlib.errors import NoWorkingTree
from bzrlib.rio import RioReader, RioWriter, Stanza
from bzrlib.osutils import local_time_offset, format_date


def get_file_revisions(branch, check=False):
    """Get the last changed revision for all files.

    :param branch: The branch we are checking.
    :param check: See if there are uncommitted changes.
    :return: ({file_path => last changed revision}, Tree_is_clean)
    """
    clean = True
    file_revisions = {}
    basis_tree = branch.basis_tree()
    for path, ie in basis_tree.inventory.iter_entries():
        file_revisions[path] = ie.revision

    if not check:
        # Without checking, the tree looks clean
        return file_revisions, clean
    try:
        new_tree = branch.working_tree()
    except NoWorkingTree:
        # Without a working tree, everything is clean
        return file_revisions, clean

    from bzrlib.diff import compare_trees
    delta = compare_trees(basis_tree, new_tree, want_unchanged=False)

    # Using a 2-pass algorithm for renames. This is because you might have
    # renamed something out of the way, and then created a new file
    # in which case we would rather see the new marker
    # Or you might have removed the target, and then renamed
    # in which case we would rather see the renamed marker
    for old_path, new_path, file_id, kind, text_mod, meta_mod in delta.renamed:
        clean = False
        file_revisions[old_path] = u'renamed to %s' % (new_path,)
    for path, file_id, kind in delta.removed:
        clean = False
        file_revisions[path] = 'removed'
    for path, file_id, kind in delta.added:
        clean = False
        file_revisions[path] = 'new'
    for old_path, new_path, file_id, kind, text_mod, meta_mod in delta.renamed:
        clean = False
        file_revisions[new_path] = u'renamed from %s' % (old_path,)
    for path, file_id, kind, text_mod, meta_mod in delta.modified:
        clean = False
        file_revisions[path] = 'modified'

    for info in new_tree.list_files():
        path, status = info[0:2]
        if status == '?':
            file_revisions[path] = 'unversioned'
            clean = False

    return file_revisions, clean


# This contains a map of format id => formatter
# None is considered the default formatter
version_formats = {}

def create_date_str(timestamp=None, offset=None):
    """Just a wrapper around format_date to provide the right format.
    
    We don't want to use '%a' in the time string, because it is locale
    dependant. We also want to force timezone original, and show_offset

    Without parameters this function yields the current date in the local
    time zone.
    """
    if timestamp is None and offset is None:
        timestamp = time.time()
        offset = local_time_offset()
    return format_date(timestamp, offset, date_fmt='%Y-%m-%d %H:%M:%S',
                       timezone='original', show_offset=True)


def generate_rio_version(branch, to_file,
        check_for_clean=False,
        include_revision_history=False,
        include_file_revisions=False):
    """Create the version file for this project.

    :param branch: The branch to write information about
    :param to_file: The file to write the information
    :param check_for_clean: If true, check if the branch is clean.
        This can be expensive for large trees. This is also only
        valid for branches with working trees.
    :param include_revision_history: Write out the list of revisions, and
        the commit message associated with each
    :param include_file_revisions: Write out the set of last changed revision
        for each file.
    """
    info = Stanza()
    info.add('build-date', create_date_str())
    info.add('revno', str(branch.revno()))

    # XXX: Compatibility pre/post storage
    repo = getattr(branch, 'repository', branch)

    last_rev_id = branch.last_revision()
    if last_rev_id is not None:
        info.add('revision-id', last_rev_id)
        rev = repo.get_revision(last_rev_id)
        info.add('date', create_date_str(rev.timestamp, rev.timezone))

    if branch.nick is not None:
        info.add('branch-nick', branch.nick)

    file_revisions = {}
    clean = True
    if check_for_clean or include_file_revisions:
        file_revisions, clean = get_file_revisions(branch, check=check_for_clean)

    if check_for_clean:
        if clean:
            info.add('clean', 'True')
        else:
            info.add('clean', 'False')

    if include_revision_history:
        revs = branch.revision_history()
        log = Stanza()
        for rev_id in revs:
            rev = repo.get_revision(rev_id)
            log.add('id', rev_id)
            log.add('message', rev.message)
            log.add('date', create_date_str(rev.timestamp, rev.timezone))
        sio = StringIO()
        log_writer = RioWriter(to_file=sio)
        log_writer.write_stanza(log)
        info.add('revisions', sio.getvalue())

    if include_file_revisions:
        files = Stanza()
        for path in sorted(file_revisions.keys()):
            files.add('path', path)
            files.add('revision', file_revisions[path])
        sio = StringIO()
        file_writer = RioWriter(to_file=sio)
        file_writer.write_stanza(files)
        info.add('file-revisions', sio.getvalue())

    writer = RioWriter(to_file=to_file)
    writer.write_stanza(info)


version_formats['rio'] = generate_rio_version
# Default format is rio
version_formats[None] = generate_rio_version


# Header and footer for the python format
_py_version_header = '''#!/usr/bin/env python
"""\\
This file is automatically generated by generate_version_info
It uses the current working tree to determine the revision.
So don't edit it. :)
"""

'''


_py_version_footer = '''

if __name__ == '__main__':
    print 'revision: %(revno)d' % version_info
    print 'nick: %(branch_nick)s' % version_info
    print 'revision id: %(revision_id)s' % version_info
'''


def generate_python_version(branch, to_file,
        check_for_clean=False,
        include_revision_history=False,
        include_file_revisions=False):
    """Create a python version file for this project.

    :param branch: The branch to write information about
    :param to_file: The file to write the information
    :param check_for_clean: If true, check if the branch is clean.
        This can be expensive for large trees. This is also only
        valid for branches with working trees.
    :param include_revision_history: Write out the list of revisions, and
        the commit message associated with each
    :param include_file_revisions: Write out the set of last changed revision
        for each file.
    """
    # TODO: jam 20051228 The python output doesn't actually need to be
    #       encoded, because it should only generate ascii safe output.
    info = {'build_date':create_date_str()
              , 'revno':branch.revno()
              , 'revision_id':None
              , 'branch_nick':branch.nick
              , 'clean':None
              , 'date':None
    }
    revisions = []

    # XXX: Compatibility pre/post storage
    repo = getattr(branch, 'repository', branch)

    last_rev_id = branch.last_revision()
    if last_rev_id:
        rev = repo.get_revision(last_rev_id)
        info['revision_id'] = last_rev_id
        info['date'] = create_date_str(rev.timestamp, rev.timezone)

    file_revisions = {}
    clean = True
    if check_for_clean or include_file_revisions:
        file_revisions, clean = get_file_revisions(branch, check=check_for_clean)

    if check_for_clean:
        if clean:
            info['clean'] = True
        else:
            info['clean'] = False

    info_str = pprint.pformat(info)
    to_file.write(_py_version_header)
    to_file.write('version_info = ')
    to_file.write(info_str)
    to_file.write('\n\n')

    if include_revision_history:
        revs = branch.revision_history()
        for rev_id in revs:
            rev = repo.get_revision(rev_id)
            revisions.append((rev_id, rev.message, rev.timestamp, rev.timezone))
        revision_str = pprint.pformat(revisions)
        to_file.write('revisions = ')
        to_file.write(revision_str)
        to_file.write('\n\n')
    else:
        to_file.write('revisions = {}\n\n')

    if include_file_revisions:
        file_rev_str = pprint.pformat(file_revisions)
        to_file.write('file_revisions = ')
        to_file.write(file_rev_str)
        to_file.write('\n\n')
    else:
        to_file.write('file_revisions = {}\n\n')

    to_file.write(_py_version_footer)


version_formats['python'] = generate_python_version

