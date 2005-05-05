# (C) 2005 Canonical Ltd

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



def find_modified(branch):
    """Return a list of files that have been modified in the working copy.

    This does not consider renames and does not include files added or
    deleted.

    Each modified file is returned as (PATH, ENTRY).
    """
    import cache

    inv = branch.read_working_inventory()
    cc = cache.update_cache(branch, inv)
    basis_inv = branch.basis_tree().inventory
    
    for path, entry in inv.iter_entries():
        if entry.kind != 'file':
            continue
        
        file_id = entry.file_id
        ce = cc.get(file_id)
        if not ce:
            continue                    # not in working dir

        if file_id not in basis_inv:
            continue                    # newly added

        old_entry = basis_inv[file_id]
 
        if (old_entry.text_size == ce[3]
            and old_entry.text_sha1 == ce[1]):
            continue

        yield path, entry
        
