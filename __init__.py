
from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import (
    bzrdir,
    static_tuple,
    )
""")
from bzrlib.commands import (
    Command,
    register_command,
    )

class cmd_chk_used_by(Command):
    __doc__ = \
    """Find the inventories/revisions that reference a CHK."""

    takes_args = ['key*']
    takes_options = ['directory']

    def run(self, key_list, directory=u'.'):
        key_list = [static_tuple.StaticTuple(k) for k in key_list]
        if len(key_list) > 1:
            key_list = frozenset(key_list)
        bd, relpath = bzrdir.BzrDir.open_containing(directory)
        repo = bd.find_repository()
        self.add_cleanup(repo.lock_read().unlock)
        inv_vf = repo.inventories
        all_invs = [k[-1] for k in inv_vf.keys()]
        # print len(all_invs)
        for inv in repo.iter_inventories(all_invs):
            if inv.id_to_entry.key() in key_list:
                self.outf.write('id_to_entry of %s -> %s\n' % (inv.revision_id, inv.id_to_entry.key(),))
            if inv.parent_id_basename_to_file_id.key() in key_list:
                self.outf.write('parent_id_basename_to_file_id of %s -> %s\n' %
                        (inv.revision_id, inv.parent_id_basename_to_file_id.key(),))

register_command(cmd_chk_used_by)
