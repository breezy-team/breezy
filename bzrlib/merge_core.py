import os.path

import changeset
from changeset import Inventory, apply_changeset, invert_dict
from bzrlib.osutils import backup_file, rename
from bzrlib.merge3 import Merge3
import bzrlib
from bzrlib.atomicfile import AtomicFile
from changeset import get_contents

class ApplyMerge3:
    history_based = False
    """Contents-change wrapper around merge3.Merge3"""
    def __init__(self, file_id, base, other, show_base=False, reprocess=False):
        self.file_id = file_id
        self.base = base
        self.other = other
        self.show_base = show_base
        self.reprocess = reprocess

    def is_creation(self):
        return False

    def is_deletion(self):
        return False

    def __eq__(self, other):
        if not isinstance(other, ApplyMerge3):
            return False
        return (self.base == other.base and 
                self.other == other.other and self.file_id == other.file_id)

    def __ne__(self, other):
        return not (self == other)

    def apply(self, filename, conflict_handler):
        new_file = filename+".new" 
        base = self.base
        other = self.other
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
        if self.show_base is True:
            base_marker = '|' * 7
        else:
            base_marker = None
        for line in m3.merge_lines(name_a = "TREE", name_b = "MERGE-SOURCE", 
                       name_base = "BASE-REVISION",
                       start_marker=start_marker, base_marker=base_marker,
                       reprocess = self.reprocess):
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

class WeaveMerge:
    """Contents-change wrapper around weave merge"""
    history_based = True
    def __init__(self, weave, this_revision_id, other_revision_id):
        self.weave = weave
        self.this_revision_id = this_revision_id
        self.other_revision_id = other_revision_id

    def is_creation(self):
        return False

    def is_deletion(self):
        return False

    def __eq__(self, other):
        if not isinstance(other, WeaveMerge):
            return False
        return self.weave == other.weave and\
            self.this_revision_id == other.this_revision_id and\
            self.other_revision_id == other.other_revision_id

    def __ne__(self, other):
        return not (self == other)

    def apply(self, filename, conflict_handler):
        this_i = self.weave.lookup(self.this_revision_id)
        other_i = self.weave.lookup(self.other_revision_id)
        plan = self.weave.plan_merge(this_i, other_i)
        lines = self.weave.weave_merge(plan)
        conflicts = False
        out_file = AtomicFile(filename, mode='wb')
        for line in lines:
            if line == '<<<<<<<\n':
                conflicts = True
            out_file.write(line)
        if conflicts:
            conflict_handler.weave_merge_conflict(filename, self.weave,
                                                  other_i, out_file)
        else:
            out_file.commit()

class BackupBeforeChange:
    """Contents-change wrapper to back up file first"""
    def __init__(self, contents_change):
        self.contents_change = contents_change

    def is_creation(self):
        return self.contents_change.is_creation()

    def is_deletion(self):
        return self.contents_change.is_deletion()

    def __eq__(self, other):
        if not isinstance(other, BackupBeforeChange):
            return False
        return (self.contents_change == other.contents_change)

    def __ne__(self, other):
        return not (self == other)

    def apply(self, filename, conflict_handler):
        backup_file(filename)
        self.contents_change.apply(filename, conflict_handler)


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
    result = apply_changeset(new_cset, invert_invent(this.inventory),
                             this.basedir, conflict_handler)
    return result
    

def make_merge_changeset(cset, this, base, other, 
                         conflict_handler, merge_factory):
    new_cset = changeset.Changeset()

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
        entry = tree.inventory[file_id]
        my_dir = tree.id2path(entry.parent_id)
        if my_dir is None:
            my_dir = ""
        return entry.name, entry.parent_id, my_dir 
    this_name, this_parent, this_dir = entry_data(entry.id, this)
    base_name, base_parent, base_dir = entry_data(entry.id, base)
    other_name, other_parent, other_dir = entry_data(entry.id, other)
    mutter("Dirs: this, base, other %r %r %r", this_dir, base_dir, other_dir)
    mutter("Names: this, base, other %r %r %r", this_name, base_name, other_name)
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


def make_merged_contents(entry, this, base, other, conflict_handler,
                         merge_factory):
    contents = entry.contents_change
    if contents is None:
        return None
    if entry.id in this:
        this_path = this.id2abspath(entry.id)
    else:
        this_path = None
    def make_merge():
        if this_path is None:
            return conflict_handler.missing_for_merge(entry.id, 
                                                      other.id2path(entry.id))
        return merge_factory(entry.id, base, other)

    if isinstance(contents, changeset.ReplaceContents):
        base_contents = contents.old_contents
        other_contents = contents.new_contents
        if base_contents is None and other_contents is None:
            return None
        if other_contents is None:
            this_contents = get_contents(this, entry.id)
            if this_path is not None and bzrlib.osutils.lexists(this_path):
                if this_contents != base_contents:
                    return conflict_handler.rem_contents_conflict(this_path, 
                        this_contents, base_contents)
                return contents
            else:
                return None
        elif base_contents is None:
            if this_path is None or not bzrlib.osutils.lexists(this_path):
                return contents
            else:
                this_contents = get_contents(this, entry.id)
                if this_contents == other_contents:
                    return None
                else:
                    conflict_handler.new_contents_conflict(this_path, 
                        other_contents)
        elif isinstance(base_contents, changeset.TreeFileCreate) and \
            isinstance(other_contents, changeset.TreeFileCreate):
            return make_merge()
        else:
            this_contents = get_contents(this, entry.id)
            if this_contents == base_contents:
                return contents
            elif this_contents == other_contents:
                return None
            elif base_contents == other_contents:
                return None
            else:
                conflict_handler.threeway_contents_conflict(this_path,
                                                            this_contents,
                                                            base_contents,
                                                            other_contents)
                

def make_merged_metadata(entry, base, other):
    metadata = entry.metadata_change
    if metadata is None:
        return None
    assert isinstance(metadata, changeset.ChangeExecFlag)
    if metadata.new_exec_flag is None:
        return None
    elif metadata.old_exec_flag is None:
        return metadata
    else:
        return ExecFlagMerge(base, other, entry.id)
    

class ExecFlagMerge(object):
    def __init__(self, base_tree, other_tree, file_id):
        self.base_tree = base_tree
        self.other_tree = other_tree
        self.file_id = file_id

    def apply(self, filename, conflict_handler):
        base = self.base_tree
        other = self.other_tree
        base_exec_flag = base.is_executable(self.file_id)
        other_exec_flag = other.is_executable(self.file_id)
        this_mode = os.stat(filename).st_mode
        this_exec_flag = bool(this_mode & 0111)
        if (base_exec_flag != other_exec_flag and
            this_exec_flag != other_exec_flag):
            assert this_exec_flag == base_exec_flag
            current_mode = os.stat(filename).st_mode
            if other_exec_flag:
                umask = os.umask(0)
                os.umask(umask)
                to_mode = current_mode | (0100 & ~umask)
                # Enable x-bit for others only if they can read it.
                if current_mode & 0004:
                    to_mode |= 0001 & ~umask
                if current_mode & 0040:
                    to_mode |= 0010 & ~umask
            else:
                to_mode = current_mode & ~0111
            os.chmod(filename, to_mode)

