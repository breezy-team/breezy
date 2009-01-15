# Copyright (C) 2008 Canonical Ltd
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

from bzrlib.bzrdir import BzrDir
from bzrlib.repository import Repository
from bzrlib.inventory import InventoryDirectory, InventoryFile
from bzrlib.osutils import splitpath

from bzrlib.plugins.git.fetch import import_git_objects
from bzrlib.plugins.git.mapping import default_mapping

from dulwich.server import Backend
from dulwich.pack import Pack, PackData, write_pack_index_v2
from dulwich.objects import ShaFile, Commit, Tree, Blob

import os, tempfile

import stat
S_IFGITLINK = 0160000

#S_IFREG | 0664 # *Might* see this; would fail fsck --strict


class BzrBackend(Backend):

    def __init__(self, directory):
        self.directory = directory
        self.mapping = default_mapping

    def get_refs(self):
        """ return a dict of all tags and branches in repository (and shas) """
        ret = {}
        repo_dir = BzrDir.open(self.directory)
        repo = repo_dir.open_repository()
        for branch in repo.find_branches(using=True):
            #FIXME: Need to get branch path relative to its repository and use this instead of nick
            ret["refs/heads/"+branch.nick] = self.mapping.revision_id_bzr_to_foreign(branch.last_revision())
        return ret

    def apply_pack(self, refs, read):
        """ apply pack from client to current repository """

        fd, path = tempfile.mkstemp(suffix=".pack")
        f = os.fdopen(fd, 'w')
        f.write(read())
        f.close()

        p = PackData(path)
        entries = p.sorted_entries()
        write_pack_index_v2(path[:-5]+".idx", entries, p.calculate_checksum())

        def get_objects():
            pack = Pack(path[:-5])
            for obj in pack.iterobjects():
                yield obj

        target = Repository.open(self.directory)

        target.lock_write()
        try:
            target.start_write_group()
            try:
                import_git_objects(target, self.mapping, iter(get_objects()))
            finally:
                target.commit_write_group()
        finally:
            target.unlock()

        for oldsha, sha, ref in refs:
            if ref[:11] == 'refs/heads/':
                branch_nick = ref[11:]

                try:
                    target_dir = BzrDir.open(self.directory + "/" + branch_nick)
                except:
                    target_dir = BzrDir.create(self.directory + "/" + branch_nick)

                try:
                    target_branch = target_dir.open_branch()
                except:
                    target_branch = target_dir.create_branch()

                rev_id = self.mapping.revision_id_foreign_to_bzr(sha)
                target_branch.generate_revision_history(rev_id)

    def fetch_objects(self, determine_wants, graph_walker, progress):
        """ yield git objects to send to client """
        wants = determine_wants(self.get_refs())
        commits_to_send = set([self.mapping.revision_id_foreign_to_bzr(w) for w in wants])
        rev_done = set()
        obj_sent = set()

        repo = Repository.open(self.directory)

        objects = set()

        repo.lock_read()
        try:
            have = graph_walker.next()
            while have:
                rev_done.add(have)
                if repo.has_revision(self.mapping.revision_id_foregin_to_bzr(sha)):
                    graph_walker.ack(have)
                have = graph_walker.next()

            while commits_to_send:
                commit = commits_to_send.pop()
                if commit in rev_done:
                    continue
                rev_done.add(commit)

                rev = repo.get_revision(commit)

                commits_to_send.update([p for p in rev.parent_ids if not p in rev_done])

                for sha, obj in inventory_to_tree_and_blobs(repo, self.mapping, commit):
                    if sha not in obj_sent:
                        obj_sent.add(sha)
                        objects.add(obj)

                objects.add(revision_to_commit(rev, self.mapping, sha))

        finally:
            repo.unlock()

        return (len(objects), iter(objects))


def revision_to_commit(rev, mapping, tree_sha):
    """
    Turn a Bazaar revision in to a Git commit
    :param tree_sha: HACK parameter (until we can retrieve this from the mapping)
    :return dulwich.objects.Commit represent the revision:
    """
    commit = Commit()
    commit._tree = tree_sha
    for p in rev.parent_ids:
        commit._parents.append(mapping.revision_id_bzr_to_foreign(p))
    commit._message = rev.message
    commit._committer = rev.committer
    if 'author' in rev.properties:
        commit._author = rev.properties['author']
    else:
        commit._author = rev.committer
    commit._commit_time = long(rev.timestamp)
    commit.serialize()
    return commit

def inventory_to_tree_and_blobs(repo, mapping, revision_id):
    stack = []
    cur = ""
    tree = Tree()

    inv = repo.get_inventory(revision_id)

    for path, entry in inv.iter_entries():
        while stack and not path.startswith(cur):
            tree.serialize()
            sha = tree.sha().hexdigest()
            yield sha, tree
            t = (stat.S_IFDIR, splitpath(cur)[-1:][0].encode('UTF-8'), sha)
            cur, tree = stack.pop()
            tree.add(*t)

        if type(entry) == InventoryDirectory:
            stack.append((cur, tree))
            cur = path
            tree = Tree()

        if type(entry) == InventoryFile:
            #FIXME: We can make potentially make this Lazy to avoid shaing lots of stuff
            # and having all these objects in memory at once
            blob = Blob()
            _, blob._text = repo.iter_files_bytes([(entry.file_id, revision_id, path)]).next()
            sha = blob.sha().hexdigest()
            yield sha, blob

            name = splitpath(path)[-1:][0].encode('UTF-8')
            mode = stat.S_IFREG | 0644
            if entry.executable:
                mode |= 0111
            tree.add(mode, name, sha)

    while len(stack) > 1:
        tree.serialize()
        sha = tree.sha().hexdigest()
        yield sha, tree
        t = (stat.S_IFDIR, splitpath(cur)[-1:][0].encode('UTF-8'), sha)
        cur, tree = stack.pop()
        tree.add(*t)

    tree.serialize()
    yield tree.sha().hexdigest(), tree

