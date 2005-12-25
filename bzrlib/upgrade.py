# Copyright (C) 2005 Canonical Ltd
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

"""Experiment in converting existing bzr branches to weaves."""

# To make this properly useful
#
# 1. assign text version ids, and put those text versions into
#    the inventory as they're converted.
#
# 2. keep track of the previous version of each file, rather than
#    just using the last one imported
#
# 3. assign entry versions when files are added, renamed or moved.
#
# 4. when merged-in versions are observed, walk down through them
#    to discover everything, then commit bottom-up
#
# 5. track ancestry as things are merged in, and commit that in each
#    revision
#
# Perhaps it's best to first walk the whole graph and make a plan for
# what should be imported in what order?  Need a kind of topological
# sort of all revisions.  (Or do we, can we just before doing a revision
# see that all its parents have either been converted or abandoned?)


# Cannot import a revision until all its parents have been
# imported.  in other words, we can only import revisions whose
# parents have all been imported.  the first step must be to
# import a revision with no parents, of which there must be at
# least one.  (So perhaps it's useful to store forward pointers
# from a list of parents to their children?)
#
# Another (equivalent?) approach is to build up the ordered
# ancestry list for the last revision, and walk through that.  We
# are going to need that.
#
# We don't want to have to recurse all the way back down the list.
#
# Suppose we keep a queue of the revisions able to be processed at
# any point.  This starts out with all the revisions having no
# parents.
#
# This seems like a generally useful algorithm...
#
# The current algorithm is dumb (O(n**2)?) but will do the job, and
# takes less than a second on the bzr.dev branch.

# This currently does a kind of lazy conversion of file texts, where a
# new text is written in every version.  That's unnecessary but for
# the moment saves us having to worry about when files need new
# versions.


import os
import tempfile
import sys
import shutil

from bzrlib.branch import Branch, find_branch
from bzrlib.branch import BZR_BRANCH_FORMAT_5, BZR_BRANCH_FORMAT_6
import bzrlib.hashcache as hashcache
from bzrlib.weave import Weave
from bzrlib.weavefile import read_weave, write_weave
from bzrlib.ui import ui_factory
from bzrlib.atomicfile import AtomicFile
from bzrlib.xml4 import serializer_v4
from bzrlib.xml5 import serializer_v5
from bzrlib.trace import mutter, note, warning
from bzrlib.osutils import sha_strings, sha_string


class Convert(object):
    def __init__(self, base_dir):
        self.base = base_dir
        self.converted_revs = set()
        self.absent_revisions = set()
        self.text_count = 0
        self.revisions = {}
        self.convert()


    def convert(self):
        if not self._open_branch():
            return
        note('starting upgrade of %s', os.path.abspath(self.base))
        self._backup_control_dir()
        self.pb = ui_factory.progress_bar()
        if self.old_format == 4:
            note('starting upgrade from format 4 to 5')
            self._convert_to_weaves()
            self._open_branch()
        if self.old_format == 5:
            note('starting upgrade from format 5 to 6')
            self._convert_to_prefixed()
            self._open_branch()
        cache = hashcache.HashCache(os.path.abspath(self.base))
        cache.clear()
        cache.write()
        note("finished")


    def _convert_to_prefixed(self):
        from bzrlib.store import hash_prefix
        for store_name in ["weaves", "revision-store"]:
            note("adding prefixes to %s" % store_name) 
            store_dir = os.path.join(self.base, ".bzr", store_name)
            for filename in os.listdir(store_dir):
                if filename.endswith(".weave") or filename.endswith(".gz"):
                    file_id = os.path.splitext(filename)[0]
                else:
                    file_id = filename
                prefix_dir = os.path.join(store_dir, hash_prefix(file_id))
                if not os.path.isdir(prefix_dir):
                    os.mkdir(prefix_dir)
                os.rename(os.path.join(store_dir, filename),
                          os.path.join(prefix_dir, filename))
        self._set_new_format(BZR_BRANCH_FORMAT_6)


    def _convert_to_weaves(self):
        note('note: upgrade may be faster if all store files are ungzipped first')
        if not os.path.isdir(self.base + '/.bzr/weaves'):
            os.mkdir(self.base + '/.bzr/weaves')
        self.inv_weave = Weave('inventory')
        # holds in-memory weaves for all files
        self.text_weaves = {}
        os.remove(self.branch.control_files.controlfilename('branch-format'))
        self._convert_working_inv()
        rev_history = self.branch.revision_history()
        # to_read is a stack holding the revisions we still need to process;
        # appending to it adds new highest-priority revisions
        self.known_revisions = set(rev_history)
        self.to_read = rev_history[-1:]
        while self.to_read:
            rev_id = self.to_read.pop()
            if (rev_id not in self.revisions
                and rev_id not in self.absent_revisions):
                self._load_one_rev(rev_id)
        self.pb.clear()
        to_import = self._make_order()
        for i, rev_id in enumerate(to_import):
            self.pb.update('converting revision', i, len(to_import))
            self._convert_one_rev(rev_id)
        self.pb.clear()
        note('upgraded to weaves:')
        note('  %6d revisions and inventories' % len(self.revisions))
        note('  %6d revisions not present' % len(self.absent_revisions))
        note('  %6d texts' % self.text_count)
        self._write_all_weaves()
        self._write_all_revs()
        self._cleanup_spare_files()
        self._set_new_format(BZR_BRANCH_FORMAT_5)


    def _open_branch(self):
        self.branch = Branch.open_downlevel(self.base)
        self.old_format = self.branch._branch_format
        if self.old_format == 6:
            note('this branch is in the most current format')
            return False
        if self.old_format not in (4, 5):
            raise BzrError("cannot upgrade from branch format %r" %
                           self.branch._branch_format)
        return True

    def _set_new_format(self, format):
        self.branch.control_files.put_utf8('branch-format', format)

    def _cleanup_spare_files(self):
        for n in 'merged-patches', 'pending-merged-patches':
            p = self.branch.control_files.controlfilename(n)
            if not os.path.exists(p):
                continue
            ## assert os.path.getsize(p) == 0
            os.remove(p)
        shutil.rmtree(self.base + '/.bzr/inventory-store')
        shutil.rmtree(self.base + '/.bzr/text-store')

    def _backup_control_dir(self):
        orig = self.base + '/.bzr'
        backup = orig + '.backup'
        note('making backup of tree history')
        shutil.copytree(orig, backup)
        note('%s has been backed up to %s', orig, backup)
        note('if conversion fails, you can move this directory back to .bzr')
        note('if it succeeds, you can remove this directory if you wish')

    def _convert_working_inv(self):
        branch = self.branch
        inv = serializer_v4.read_inventory(branch.control_files.controlfile('inventory', 'rb'))
        new_inv_xml = serializer_v5.write_inventory_to_string(inv)
        branch.control_files.put_utf8('inventory', new_inv_xml)

    def _write_all_weaves(self):
        write_a_weave(self.inv_weave, self.base + '/.bzr/inventory.weave')
        i = 0
        try:
            for file_id, file_weave in self.text_weaves.items():
                self.pb.update('writing weave', i, len(self.text_weaves))
                write_a_weave(file_weave, self.base + '/.bzr/weaves/%s.weave' % file_id)
                i += 1
        finally:
            self.pb.clear()


    def _write_all_revs(self):
        """Write all revisions out in new form."""
        shutil.rmtree(self.base + '/.bzr/revision-store')
        os.mkdir(self.base + '/.bzr/revision-store')
        try:
            for i, rev_id in enumerate(self.converted_revs):
                self.pb.update('write revision', i, len(self.converted_revs))
                f = file(self.base + '/.bzr/revision-store/%s' % rev_id, 'wb')
                try:
                    serializer_v5.write_revision(self.revisions[rev_id], f)
                finally:
                    f.close()
        finally:
            self.pb.clear()

            
    def _load_one_rev(self, rev_id):
        """Load a revision object into memory.

        Any parents not either loaded or abandoned get queued to be
        loaded."""
        self.pb.update('loading revision',
                       len(self.revisions),
                       len(self.known_revisions))
        if not self.branch.repository.revision_store.has_id(rev_id):
            self.pb.clear()
            note('revision {%s} not present in branch; '
                 'will be converted as a ghost',
                 rev_id)
            self.absent_revisions.add(rev_id)
        else:
            rev_xml = self.branch.repository.revision_store.get(rev_id).read()
            rev = serializer_v4.read_revision_from_string(rev_xml)
            for parent_id in rev.parent_ids:
                self.known_revisions.add(parent_id)
                self.to_read.append(parent_id)
            self.revisions[rev_id] = rev


    def _load_old_inventory(self, rev_id):
        assert rev_id not in self.converted_revs
        old_inv_xml = self.branch.repository.inventory_store.get(rev_id).read()
        inv = serializer_v4.read_inventory_from_string(old_inv_xml)
        rev = self.revisions[rev_id]
        if rev.inventory_sha1:
            assert rev.inventory_sha1 == sha_string(old_inv_xml), \
                'inventory sha mismatch for {%s}' % rev_id
        return inv
        

    def _load_updated_inventory(self, rev_id):
        assert rev_id in self.converted_revs
        inv_xml = self.inv_weave.get_text(rev_id)
        inv = serializer_v5.read_inventory_from_string(inv_xml)
        return inv


    def _convert_one_rev(self, rev_id):
        """Convert revision and all referenced objects to new format."""
        rev = self.revisions[rev_id]
        inv = self._load_old_inventory(rev_id)
        present_parents = [p for p in rev.parent_ids
                           if p not in self.absent_revisions]
        self._convert_revision_contents(rev, inv, present_parents)
        self._store_new_weave(rev, inv, present_parents)
        self.converted_revs.add(rev_id)


    def _store_new_weave(self, rev, inv, present_parents):
        # the XML is now updated with text versions
        if __debug__:
            for file_id in inv:
                ie = inv[file_id]
                if ie.kind == 'root_directory':
                    continue
                assert hasattr(ie, 'revision'), \
                    'no revision on {%s} in {%s}' % \
                    (file_id, rev.revision_id)
        new_inv_xml = serializer_v5.write_inventory_to_string(inv)
        new_inv_sha1 = sha_string(new_inv_xml)
        self.inv_weave.add(rev.revision_id, 
                           present_parents,
                           new_inv_xml.splitlines(True),
                           new_inv_sha1)
        rev.inventory_sha1 = new_inv_sha1

    def _convert_revision_contents(self, rev, inv, present_parents):
        """Convert all the files within a revision.

        Also upgrade the inventory to refer to the text revision ids."""
        rev_id = rev.revision_id
        mutter('converting texts of revision {%s}',
               rev_id)
        parent_invs = map(self._load_updated_inventory, present_parents)
        for file_id in inv:
            ie = inv[file_id]
            self._convert_file_version(rev, ie, parent_invs)

    def _convert_file_version(self, rev, ie, parent_invs):
        """Convert one version of one file.

        The file needs to be added into the weave if it is a merge
        of >=2 parents or if it's changed from its parent.
        """
        if ie.kind == 'root_directory':
            return
        file_id = ie.file_id
        rev_id = rev.revision_id
        w = self.text_weaves.get(file_id)
        if w is None:
            w = Weave(file_id)
            self.text_weaves[file_id] = w
        text_changed = False
        previous_entries = ie.find_previous_heads(parent_invs, w)
        for old_revision in previous_entries:
                # if this fails, its a ghost ?
                assert old_revision in self.converted_revs 
        self.snapshot_ie(previous_entries, ie, w, rev_id)
        del ie.text_id
        assert getattr(ie, 'revision', None) is not None

    def snapshot_ie(self, previous_revisions, ie, w, rev_id):
        # TODO: convert this logic, which is ~= snapshot to
        # a call to:. This needs the path figured out. rather than a work_tree
        # a v4 revision_tree can be given, or something that looks enough like
        # one to give the file content to the entry if it needs it.
        # and we need something that looks like a weave store for snapshot to 
        # save against.
        #ie.snapshot(rev, PATH, previous_revisions, REVISION_TREE, InMemoryWeaveStore(self.text_weaves))
        if len(previous_revisions) == 1:
            previous_ie = previous_revisions.values()[0]
            if ie._unchanged(previous_ie):
                ie.revision = previous_ie.revision
                return
        parent_indexes = map(w.lookup, previous_revisions)
        if ie.has_text():
            text = self.branch.repository.text_store.get(ie.text_id)
            file_lines = text.readlines()
            assert sha_strings(file_lines) == ie.text_sha1
            assert sum(map(len, file_lines)) == ie.text_size
            w.add(rev_id, parent_indexes, file_lines, ie.text_sha1)
            self.text_count += 1
        else:
            w.add(rev_id, parent_indexes, [], None)
        ie.revision = rev_id
        ##mutter('import text {%s} of {%s}',
        ##       ie.text_id, file_id)

    def _make_order(self):
        """Return a suitable order for importing revisions.

        The order must be such that an revision is imported after all
        its (present) parents.
        """
        todo = set(self.revisions.keys())
        done = self.absent_revisions.copy()
        o = []
        while todo:
            # scan through looking for a revision whose parents
            # are all done
            for rev_id in sorted(list(todo)):
                rev = self.revisions[rev_id]
                parent_ids = set(rev.parent_ids)
                if parent_ids.issubset(done):
                    # can take this one now
                    o.append(rev_id)
                    todo.remove(rev_id)
                    done.add(rev_id)
        return o


def write_a_weave(weave, filename):
    inv_wf = file(filename, 'wb')
    try:
        write_weave(weave, inv_wf)
    finally:
        inv_wf.close()


def upgrade(base_dir):
    Convert(base_dir)
