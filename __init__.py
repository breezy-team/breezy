from bzrlib.lazy_import import lazy_import

lazy_import(globals(), """
import (
        errno,
        os,
        sys,
        time,
        )

from bzrlib import (
    commands,
    urlutils
    )
from bzrlib.workingtree import WorkingTree
from bzrlib.tests import TestUtil

from bzrlib.plugins.multiparent.multiparent import (
    MultiVersionedFile,
    MultiMemoryVersionedFile,
    )
""")

class cmd_mp_regen(commands.Command):
    """Generate a multiparent versionedfile"""

    takes_args = ['file?']
    takes_options = [commands.Option('sync-snapshots',
                                     help='Snapshots follow source'),
                     commands.Option('snapshot-interval', type=int,
                                     help='take snapshots every x revisions'),
                     commands.Option('lsprof-timed', help='Use lsprof'),
                     commands.Option('outfile', type=unicode,
                                     help='Write pseudo-knit to this file'),
                     commands.Option('memory', help='Use memory, not disk'),
                     commands.Option('extract', help='test extract time'),
                     commands.Option('single', help='use a single parent'),
                     commands.Option('verify', help='verify added texts'),
                    ]
    hidden = True

    def run(self, file=None, sync_snapshots=False, snapshot_interval=26,
            lsprof_timed=False, dump=False, extract=False, single=False,
            verify=False, outfile=None, memory=False):
        if file is None:
            wt, path = WorkingTree.open_containing('.')
            file_weave = wt.branch.repository.get_inventory_weave()
        else:
            wt, path = WorkingTree.open_containing(file)
            file_id = wt.path2id(path)
            bt = wt.branch.repository.revision_tree(wt.last_revision())
            file_weave = bt.get_weave(file_id)
        url = file_weave.transport.abspath(file_weave.filename)
        print >> sys.stderr, 'Importing: %s' % \
            urlutils.local_path_from_url(url)
        if sync_snapshots:
            print >> sys.stderr, 'Snapshots follow input'
        else:
            print >> sys.stderr, 'Snapshot interval: %d' % snapshot_interval
        if not memory:
            if outfile is None:
                filename = 'pknit'
            else:
                filename = outfile
            vf = MultiVersionedFile(filename, snapshot_interval)
        else:
            vf = MultiMemoryVersionedFile(snapshot_interval)
        vf.destroy()
        snapshots = set(r for r in file_weave.versions() if
                        file_weave._index.get_method(r) == 'fulltext')
        if sync_snapshots:
            to_sync = snapshots
        else:
            to_sync = vf.select_snapshots(file_weave)
        print >> sys.stderr, "%d fulltexts" % len(snapshots)
        print >> sys.stderr, "%d planned snapshots" % len(to_sync)

        try:
            vf.import_versionedfile(file_weave, to_sync, single_parent=single,
                                    verify=verify)
        except:
            vf.destroy()
            raise
        try:
            print >> sys.stderr, "%d actual snapshots" % len(to_sync)
            vf.clear_cache()
            if False:
                for revision_id in file_weave.get_ancestry(
                    [bt.inventory[file_id].revision]):
                    if vf.get_line_list([revision_id])[0] != \
                        file_weave.get_lines(revision_id):
                        open(revision_id + '.old', 'wb').writelines(
                            file_weave.get_lines(revision_id))
                        open(revision_id + '.new', 'wb').writelines(
                            vf.get_line_list(revision_id)[0])
            if extract:
                revisions = file_weave.versions()[-1:]
                if lsprof_timed:
                    from bzrlib.lsprof import profile
                    ret, stats = profile(vf.get_line_list, revisions)
                    stats.sort()
                    stats.pprint()
                start = time.clock()
                print >> sys.stderr, revisions[0]
                for x in range(1000):
                    vf.clear_cache()
                    vf.get_line_list(revisions)
                print >> sys.stderr, time.clock() - start
                start = time.clock()
                for x in range(1000):
                    file_weave.get_line_list(revisions)
                print >> sys.stderr, time.clock() - start
            if memory and outfile is not None:
                outvf = MultiVersionedFile(outfile)
                for version_id in vf.versions():
                    outvf.add_diff(vf.get_diff(version_id), version_id,
                                   vf._parents[version_id])
        finally:
            if outfile is None:
                vf.destroy()

commands.register_command(cmd_mp_regen)

def test_suite():
    from bzrlib.plugins.multiparent import test_multiparent
    return TestUtil.TestLoader().loadTestsFromModule(test_multiparent)
