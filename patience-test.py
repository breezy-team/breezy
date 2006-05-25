#!/usr/bin/env python2.4
# Copyright (C) 2006 by Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import difflib
from StringIO import StringIO
from subprocess import Popen, PIPE
from tempfile import mkdtemp

from bzrlib.branch import Branch
from bzrlib.patiencediff import SequenceMatcher
from bzrlib.diff import internal_diff
from bzrlib.osutils import pathjoin


def patch(path, patch_lines):
    """Apply a patch to a branch, using patch(1).  URLs may be used."""
    cmd = ['patch', '--quiet', path]
    r = 0
    child_proc = Popen(cmd, stdin=PIPE)
    for line in patch_lines:
        child_proc.stdin.write(line)
    child_proc.stdin.close()
    r = child_proc.wait()
    return r


old_total = 0
new_total = 0
b = Branch.open_containing('.')[0]
repo = b.repository
repo.lock_write()
try:
    temp_dir = mkdtemp()
    transaction = repo.get_transaction()
    file_list = list(repo.text_store)
    for i, file_id in enumerate(file_list):
        print "%.2f%% %d of %d %s" % ((float(i)/len(file_list) * 100), i,
                                    len(file_list), file_id)
        versioned_file = repo.text_store.get_weave(file_id, transaction)
        last_id = None
        for revision_id in versioned_file.versions():
            if last_id != None:
                old_lines = versioned_file.get_lines(last_id)
                new_lines = versioned_file.get_lines(revision_id)
                if ''.join(old_lines) == ''.join(new_lines):
                    continue

                new_patch = StringIO()
                try:
                    internal_diff('old', old_lines, 'new', new_lines, new_patch,
                                  sequence_matcher=SequenceMatcher)
                except:
                    file(pathjoin(temp_dir, 'old'), 
                         'wb').write(''.join(old_lines))
                    file(pathjoin(temp_dir, 'new'), 
                         'wb').write(''.join(new_lines))
                    print "temp dir is %s" % temp_dir
                    raise
                old_patch = StringIO()
                internal_diff('old', old_lines, 'new', new_lines, old_patch,
                              sequence_matcher=difflib.SequenceMatcher)
                old_total += len(old_patch.getvalue())
                new_total += len(new_patch.getvalue())
                new_patch.seek(0)
                file_path = pathjoin(temp_dir, 'file')
                orig_file = file(file_path, 'wb')
                for line in old_lines:
                    orig_file.write(line)
                orig_file.close()
                patch(file_path, new_patch)
                new_file = file(file_path, 'rb')
                assert list(new_file) == new_lines
            last_id = revision_id
    print old_total, new_total
finally:
    repo.unlock()
