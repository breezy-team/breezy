# Copyright (C) 2004, 2005 by Martin Pool
# Copyright (C) 2005 by Canonical Ltd

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

# TODO: Check ancestries are correct for every revision: includes
# every committed so far, and in a reasonable order.

# TODO: Also check non-mainline revisions mentioned as parents.

# TODO: Check for extra files in the control directory.

# TODO: Check revision, inventory and entry objects have all 
# required fields.


import bzrlib.ui
from bzrlib.trace import note, warning
from bzrlib.osutils import rename, sha_string, fingerprint_file
from bzrlib.trace import mutter
from bzrlib.errors import BzrCheckError, NoSuchRevision
from bzrlib.inventory import ROOT_ID
from bzrlib.branch import gen_root_id


class Check(object):
    """Check a branch"""
    def __init__(self, branch):
        self.branch = branch
        self.run()


    def run(self):
        branch = self.branch

	self.checked_text_cnt = 0
	self.checked_rev_cnt = 0
        self.missing_inventory_sha_cnt = 0
        self.missing_revision_cnt = 0

        history = branch.revision_history()
        revno = 0
        revcount = len(history)

        last_rev_id = None
        self.progress = bzrlib.ui.ui_factory.progress_bar()
        for rev_id in history:
            self.progress.update('checking revision', revno, revcount)
            revno += 1
	    self.check_one_rev(rev_id, last_rev_id)
	    last_rev_id = rev_id
        self.progress.clear()
	self.report_results()


    def report_results(self):
	note('checked branch %s format %d',
	     self.branch.base, 
	     self.branch._branch_format)

        note('checked %d revisions, %d file texts',
	     self.checked_rev_cnt,
	     self.checked_text_cnt)

        if self.missing_inventory_sha_cnt:
            note('%d revisions are missing inventory_sha1',
		 self.missing_inventory_sha_cnt)

        if self.missing_revision_cnt:
            note('%d revisions are mentioned but not present',
		 self.missing_revision_cnt)


    def check_one_rev(self, rev_id, last_rev_id):
	"""Check one revision.

	rev_id - the one to check

	last_rev_id - the previous one on the mainline, if any.
	"""

	# mutter('    revision {%s}' % rev_id)
	branch = self.branch
	rev = branch.get_revision(rev_id)
	if rev.revision_id != rev_id:
	    raise BzrCheckError('wrong internal revision id in revision {%s}'
				% rev_id)

	# check the previous history entry is a parent of this entry
	if rev.parent_ids:
	    if last_rev_id is None:
		raise BzrCheckError("revision {%s} has %d parents, but is the "
				    "start of the branch"
				    % (rev_id, len(rev.parent_ids)))
	    for parent_id in rev.parent_ids:
		if parent_id == last_rev_id:
		    break
	    else:
		raise BzrCheckError("previous revision {%s} not listed among "
				    "parents of {%s}"
				    % (last_rev_id, rev_id))
	elif last_rev_id:
	    raise BzrCheckError("revision {%s} has no parents listed "
				"but preceded by {%s}"
				% (rev_id, last_rev_id))

	if rev.inventory_sha1:
	    inv_sha1 = branch.get_inventory_sha1(rev_id)
	    if inv_sha1 != rev.inventory_sha1:
		raise BzrCheckError('Inventory sha1 hash doesn\'t match'
		    ' value in revision {%s}' % rev_id)
	else:
	    missing_inventory_sha_cnt += 1
	    mutter("no inventory_sha1 on revision {%s}" % rev_id)
	self._check_revision_tree(rev_id)
        self.checked_rev_cnt += 1

    def _check_revision_tree(self, rev_id):
	tree = self.branch.revision_tree(rev_id)
	inv = tree.inventory
	seen_ids = {}
	for file_id in inv:
	    if file_id in seen_ids:
		raise BzrCheckError('duplicated file_id {%s} '
				    'in inventory for revision {%s}'
				    % (file_id, rev_id))
	    seen_ids[file_id] = True
	for file_id in inv:
	    self._check_one_entry(rev_id, inv, tree, file_id)
	seen_names = {}
	for path, ie in inv.iter_entries():
	    if path in seen_names:
		raise BzrCheckError('duplicated path %s '
				    'in inventory for revision {%s}'
				    % (path, rev_id))
	    seen_names[path] = True

	
    def _check_one_entry(self, rev_id, inv, tree, file_id):
	ie = inv[file_id]
	if ie.parent_id != None:
	    if not inv.has_id(ie.parent_id):
		raise BzrCheckError('missing parent {%s} in inventory for revision {%s}'
			% (ie.parent_id, rev_id))
	if ie.kind == 'file':
	    text = tree.get_file_text(file_id)
	    self.checked_text_cnt += 1 
	    if ie.text_size != len(text):
		raise BzrCheckError('text {%s} wrong size' % ie.text_id)
	    if ie.text_sha1 != sha_string(text):
		raise BzrCheckError('text {%s} wrong sha1' % ie.text_id)
	elif ie.kind == 'directory':
	    if ie.text_sha1 != None or ie.text_size != None or ie.text_id != None:
		raise BzrCheckError('directory {%s} has text in revision {%s}'
			% (file_id, rev_id))
	elif ie.kind == 'root_directory':
	    pass
	else:
	    raise BzrCheckError('unknown entry kind %r in revision {%s}' % 
				(ie.kind, rev_id))


def check(branch):
    """Run consistency checks on a branch."""
    Check(branch)
