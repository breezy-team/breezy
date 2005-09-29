import changeset
from changeset import Inventory, apply_changeset, invert_dict
import os.path
from osutils import backup_file, rename
from merge3 import Merge3

class ApplyMerge3:
    """Contents-change wrapper around merge3.Merge3"""
    def __init__(self, file_id, base, other):
        self.file_id = file_id
        self.base = base
        self.other = other
 
    def __eq__(self, other):
        if not isinstance(other, ApplyMerge3):
            return False
        return (self.base == other.base and 
                self.other == other.other and self.file_id == other.file_id)

    def __ne__(self, other):
        return not (self == other)


    def apply(self, filename, conflict_handler, reverse=False):
        new_file = filename+".new" 
        if not reverse:
            base = self.base
            other = self.other
        else:
            base = self.other
            other = self.base
        def get_lines(tree):
            if self.file_id not in tree:
                raise Exception("%s not in tree" % self.file_id)
                return ()
            return tree.get_file(self.file_id).readlines()
        base_lines = get_lines(base)
        other_lines = get_lines(other)
        m3 = Merge3(base_lines, file(filename, "rb").readlines(), other_lines)

        new_conflicts = False
        output_file = file(new_file, "wb")
        start_marker = "!START OF MERGE CONFLICT!" + "I HOPE THIS IS UNIQUE"
        for line in m3.merge_lines(name_a = "TREE", name_b = "MERGE-SOURCE", 
                       start_marker=start_marker):
            if line.startswith(start_marker):
                new_conflicts = True
                output_file.write(line.replace(start_marker, '<' * 7))
            else:
                output_file.write(line)
        output_file.close()
        if not new_conflicts:
            os.chmod(new_file, os.stat(filename).st_mode)
            rename(new_file, filename)
            return
        else:
            conflict_handler.merge_conflict(new_file, filename, base_lines,
                                            other_lines)


class BackupBeforeChange:
    """Contents-change wrapper to back up file first"""
    def __init__(self, contents_change):
        self.contents_change = contents_change
 
    def __eq__(self, other):
        if not isinstance(other, BackupBeforeChange):
            return False
        return (self.contents_change == other.contents_change)

    def __ne__(self, other):
        return not (self == other)

    def apply(self, filename, conflict_handler, reverse=False):
        backup_file(filename)
        self.contents_change.apply(filename, conflict_handler, reverse)


def invert_invent(inventory):
    invert_invent = {}
    for file_id in inventory:
        path = inventory.id2path(file_id)
        if path == '':
            path = './.'
        else:
            path = './' + path
        invert_invent[file_id] = path
    return invert_invent


def merge_flex(this, base, other, changeset_function, inventory_function,
               conflict_handler, merge_factory, interesting_ids):
    cset = changeset_function(base, other, interesting_ids)
    new_cset = make_merge_changeset(cset, this, base, other, 
                                    conflict_handler, merge_factory)
    result = apply_changeset(new_cset, invert_invent(this.tree.inventory),
                             this.root, conflict_handler, False)
    conflict_handler.finalize()
    return result

    

def make_merge_changeset(cset, this, base, other, 
                         conflict_handler, merge_factory):
    new_cset = changeset.Changeset()
    def get_this_contents(id):
        path = this.readonly_path(id)
        if os.path.isdir(path):
            return changeset.dir_create
        else:
            return changeset.FileCreate(file(path, "rb").read())

    for entry in cset.entries.itervalues():
        if entry.is_boring():
            new_cset.add_entry(entry)
        else:
            new_entry = make_merged_entry(entry, this, base, other, 
                                          conflict_handler)
            new_contents = make_merged_contents(entry, this, base, other, 
                                                conflict_handler,
                                                merge_factory)
            new_entry.contents_change = new_contents
            new_entry.metadata_change = make_merged_metadata(entry, base, other)
            new_cset.add_entry(new_entry)

    return new_cset

class ThreeWayConflict(Exception):
    def __init__(self, this, base, other):
        self.this = this
        self.base = base
        self.other = other
        msg = "Conflict merging %s %s and %s" % (this, base, other)
        Exception.__init__(self, msg)

def threeway_select(this, base, other):
    """Returns a value selected by the three-way algorithm.
    Raises ThreewayConflict if the algorithm yields a conflict"""
    if base == other:
        return this
    elif base == this:
        return other
    elif other == this:
        return this
    else:
        raise ThreeWayConflict(this, base, other)


def make_merged_entry(entry, this, base, other, conflict_handler):
    from bzrlib.trace import mutter
    def entry_data(file_id, tree):
        assert hasattr(tree, "__contains__"), "%s" % tree
        if not tree.has_or_had_id(file_id):
            return (None, None, "")
        entry = tree.tree.inventory[file_id]
        my_dir = tree.id2path(entry.parent_id)
        if my_dir is None:
            my_dir = ""
        return entry.name, entry.parent_id, my_dir 
    this_name, this_parent, this_dir = entry_data(entry.id, this)
    base_name, base_parent, base_dir = entry_data(entry.id, base)
    other_name, other_parent, other_dir = entry_data(entry.id, other)
    mutter("Dirs: this, base, other %r %r %r" % (this_dir, base_dir, other_dir))
    mutter("Names: this, base, other %r %r %r" % (this_name, base_name, other_name))
    old_name = this_name
    try:
        new_name = threeway_select(this_name, base_name, other_name)
    except ThreeWayConflict:
        new_name = conflict_handler.rename_conflict(entry.id, this_name, 
                                                    base_name, other_name)

    old_parent = this_parent
    try:
        new_parent = threeway_select(this_parent, base_parent, other_parent)
    except ThreeWayConflict:
        new_parent = conflict_handler.move_conflict(entry.id, this_dir,
                                                    base_dir, other_dir)
    def get_path(name, parent):
        if name is not None:
            if name == "":
                assert parent is None
                return './.'
            parent_dir = {this_parent: this_dir, other_parent: other_dir, 
                          base_parent: base_dir}
            directory = parent_dir[parent]
            return os.path.join(directory, name)
        else:
            assert parent is None
            return None

    old_path = get_path(old_name, old_parent)
        
    new_entry = changeset.ChangesetEntry(entry.id, old_parent, old_path)
    new_entry.new_path = get_path(new_name, new_parent)
    new_entry.new_parent = new_parent
    mutter(repr(new_entry))
    return new_entry


def get_contents(entry, tree):
    """Get a contents change element suitable for use with ReplaceContents
    """
    tree_entry = tree.tree.inventory[entry.id]
    if tree_entry.kind == "file":
        return changeset.FileCreate(tree.get_file(entry.id).read())
    else:
        assert tree_entry.kind in ("root_directory", "directory")
        return changeset.dir_create


def make_merged_contents(entry, this, base, other, conflict_handler,
                         merge_factory):
    contents = entry.contents_change
    if contents is None:
        return None
    this_path = this.readonly_path(entry.id)
    def make_merge():
        if this_path is None:
            return conflict_handler.missing_for_merge(entry.id, 
                                                      other.id2path(entry.id))
        return merge_factory(entry.id, base, other)

    if isinstance(contents, changeset.ReplaceContents):
        if contents.old_contents is None and contents.new_contents is None:
            return None
        if contents.new_contents is None:
            this_contents = get_contents(entry, this)
            if this_path is not None and os.path.exists(this_path):
                if this_contents != contents.old_contents:
                    return conflict_handler.rem_contents_conflict(this_path, 
                        this_contents, contents.old_contents)
                return contents
            else:
                return None
        elif contents.old_contents is None:
            if this_path is None or not os.path.exists(this_path):
                return contents
            else:
                this_contents = get_contents(entry, this)
                if this_contents == contents.new_contents:
                    return None
                else:
                    other_path = other.readonly_path(entry.id)    
                    conflict_handler.new_contents_conflict(this_path, 
                                                           other_path)
        elif isinstance(contents.old_contents, changeset.FileCreate) and \
            isinstance(contents.new_contents, changeset.FileCreate):
            return make_merge()
        else:
            raise Exception("Unhandled merge scenario")

def make_merged_metadata(entry, base, other):
    if entry.metadata_change is not None:
        base_path = base.readonly_path(entry.id)
        other_path = other.readonly_path(entry.id)    
        return PermissionsMerge(base_path, other_path)
    

class PermissionsMerge(object):
    def __init__(self, base_path, other_path):
        self.base_path = base_path
        self.other_path = other_path

    def apply(self, filename, conflict_handler, reverse=False):
        if not reverse:
            base = self.base_path
            other = self.other_path
        else:
            base = self.other_path
            other = self.base_path
        base_stat = os.stat(base).st_mode
        other_stat = os.stat(other).st_mode
        this_stat = os.stat(filename).st_mode
        if base_stat &0777 == other_stat &0777:
            return
        elif this_stat &0777 == other_stat &0777:
            return
        elif this_stat &0777 == base_stat &0777:
            os.chmod(filename, other_stat)
        else:
            conflict_handler.permission_conflict(filename, base, other)
