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
                     commands.Option('outfile', type=unicode,
                                     help='Write pseudo-knit to this file'),
                     commands.Option('memory', help='Use memory, not disk'),
                     commands.Option('extract', help='test extract time'),
                     commands.Option('single', help='use a single parent'),
                     commands.Option('verify', help='verify added texts'),
                     commands.Option('cache', help='Aggresively cache'),
                     commands.Option('size', help='Aggressive size'),
                     commands.Option('build', help='Aggressive build'),
                    ]
    hidden = True

    def run(self, file=None, sync_snapshots=False, snapshot_interval=26,
            lsprof_timed=False, dump=False, extract=False, single=False,
            verify=False, outfile=None, memory=False, cache=False,
            size=False, build=False):
        file_weave = get_file_weave(file)
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
        old_snapshots = set(r for r in file_weave.versions() if
                        file_weave._index.get_method(r) == 'fulltext')
        if sync_snapshots:
            to_sync = old_snapshots
        elif size or build:
            assert memory
            to_sync = set()
        else:
            to_sync = vf.select_snapshots(file_weave)
        print >> sys.stderr, "%d fulltext(s)" % len(old_snapshots)
        print >> sys.stderr, "%d planned snapshots" % len(to_sync)

        try:
            vf.import_versionedfile(file_weave, to_sync, single_parent=single,
                                    verify=verify, no_cache=not cache)
            if size:
                snapshots = vf.select_by_size(len(snapshots))
                for version_id in snapshots:
                    vf.make_snapshot(version_id)
            if build:
                ranking = vf.get_build_ranking()
                snapshots = ranking[:len(snapshots) -\
                    len(vf._snapshots)]
                for version_id in snapshots:
                    old_len = len(vf._snapshots)
                    #vf.make_snapshot(version_id)
        except:
            vf.destroy()
            raise
        try:
            print >> sys.stderr, "%d actual snapshots" % len(vf._snapshots)
            if not cache:
                vf.clear_cache()
            if memory:
                if outfile is not None:
                    vf_file = MultiVersionedFile(outfile)
                for version_id in vf.versions():
                    vf_file.add_diff(vf.get_diff(version_id), version_id,
                                     vf._parents[version_id])
            else:
                vf_file = vf
        finally:
            if outfile is None:
                vf.destroy()
            else:
                vf_file.save()

class cmd_mp_extract(commands.Command):

    takes_options = [
        commands.Option('lsprof-timed', help='Use lsprof'),
        commands.Option('parallel', help='extract multiple versions at once'),
        commands.Option('count', help='Number of cycles to do', type=int),
        ]

    takes_args = ['filename', 'vfile?']

    def run(self, filename, vfile=None, lsprof_timed=False, count=1000,
            parallel=False):
        vf = MultiVersionedFile(filename)
        vf.load()
        revisions = list(vf.versions())
        revisions = revisions[-count:]
        print 'Testing extract time of %d revisions' % len(revisions)
        if parallel:
            revisions_list = [revisions]
        else:
            revisions_list = [[r] for r in revisions]
        start = time.clock()
        for revisions in revisions_list:
            vf = MultiVersionedFile(filename)
            vf.load()
            vf.get_line_list(revisions)
        print >> sys.stderr, time.clock() - start
        if lsprof_timed:
            from bzrlib.lsprof import profile
            vf.clear_cache()
            ret, stats = profile(vf.get_line_list, revisions_list[-1][-1])
            stats.sort()
            stats.pprint()
        start = time.clock()
        for revisions in revisions_list:
            file_weave = get_file_weave(vfile)
            file_weave.get_line_list(revisions)
        print >> sys.stderr, time.clock() - start


def get_file_weave(filename=None, wt=None):
    if filename is None:
        wt, path = WorkingTree.open_containing('.')
        return wt.branch.repository.get_inventory_weave()
    else:
        wt, path = WorkingTree.open_containing(filename)
        file_id = wt.path2id(path)
        bt = wt.branch.repository.revision_tree(wt.last_revision())
        return bt.get_weave(file_id)


commands.register_command(cmd_mp_regen)
commands.register_command(cmd_mp_extract)

def test_suite():
    from bzrlib.plugins.multiparent import test_multiparent
    return TestUtil.TestLoader().loadTestsFromModule(test_multiparent)
