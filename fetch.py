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

from bzrlib import osutils, ui, urlutils
from bzrlib.errors import InvalidRevisionId, NoSuchRevision
from bzrlib.inventory import Inventory
from bzrlib.repository import InterRepository
from bzrlib.trace import info
from bzrlib.tsort import topo_sort

from bzrlib.plugins.git.repository import (
        LocalGitRepository, 
        GitRepository, 
        GitFormat,
        )
from bzrlib.plugins.git.converter import GitObjectConverter
from bzrlib.plugins.git.remote import RemoteGitRepository

import dulwich as git
from dulwich.client import SimpleFetchGraphWalker
from dulwich.objects import Commit

from cStringIO import StringIO


class BzrFetchGraphWalker(object):
    """GraphWalker implementation that uses a Bazaar repository."""

    def __init__(self, repository, mapping):
        self.repository = repository
        self.mapping = mapping
        self.done = set()
        self.heads = set(repository.all_revision_ids())
        self.parents = {}

    def __iter__(self):
        return iter(self.next, None)

    def ack(self, sha):
        revid = self.mapping.revision_id_foreign_to_bzr(sha)
        self.remove(revid)

    def remove(self, revid):
        self.done.add(revid)
        if revid in self.heads:
            self.heads.remove(revid)
        if revid in self.parents:
            for p in self.parents[revid]:
                self.remove(p)

    def next(self):
        while self.heads:
            ret = self.heads.pop()
            ps = self.repository.get_parent_map([ret])[ret]
            self.parents[ret] = ps
            self.heads.update([p for p in ps if not p in self.done])
            try:
                self.done.add(ret)
                return self.mapping.revision_id_bzr_to_foreign(ret)[0]
            except InvalidRevisionId:
                pass
        return None


def import_git_blob(repo, mapping, path, blob, inv, parent_invs, gitmap, executable):
    """Import a git blob object into a bzr repository.

    :param repo: bzr repository
    :param path: Path in the tree
    :param blob: A git blob
    """
    file_id = mapping.generate_file_id(path)
    text_revision = inv.revision_id
    repo.texts.add_lines((file_id, text_revision),
        [(file_id, p[file_id].revision) for p in parent_invs if file_id in p],
        osutils.split_lines(blob.data))
    ie = inv.add_path(path, "file", file_id)
    ie.revision = text_revision
    ie.text_size = len(blob.data)
    ie.text_sha1 = osutils.sha_string(blob.data)
    ie.executable = executable
    gitmap._idmap.add_entry(blob.sha().hexdigest(), "blob", (ie.file_id, ie.revision))


def import_git_tree(repo, mapping, path, tree, inv, parent_invs, 
                    gitmap, lookup_object):
    """Import a git tree object into a bzr repository.

    :param repo: A Bzr repository object
    :param path: Path in the tree
    :param tree: A git tree object
    :param inv: Inventory object
    """
    file_id = mapping.generate_file_id(path)
    text_revision = inv.revision_id
    repo.texts.add_lines((file_id, text_revision),
        [(file_id, p[file_id].revision) for p in parent_invs if file_id in p],
        [])
    ie = inv.add_path(path, "directory", file_id)
    ie.revision = text_revision
    gitmap._idmap.add_entry(tree.sha().hexdigest(), "tree", (file_id, text_revision))
    for mode, name, hexsha in tree.entries():
        entry_kind = (mode & 0700000) / 0100000
        basename = name.decode("utf-8")
        if path == "":
            child_path = name
        else:
            child_path = urlutils.join(path, name)
        if entry_kind == 0:
            tree = lookup_object(hexsha)
            import_git_tree(repo, mapping, child_path, tree, inv, parent_invs, gitmap, lookup_object)
        elif entry_kind == 1:
            blob = lookup_object(hexsha)
            fs_mode = mode & 0777
            import_git_blob(repo, mapping, child_path, blob, inv, parent_invs, gitmap, bool(fs_mode & 0111))
        else:
            raise AssertionError("Unknown blob kind, perms=%r." % (mode,))


def import_git_objects(repo, mapping, object_iter, target_git_object_retriever, 
        pb=None):
    """Import a set of git objects into a bzr repository.

    :param repo: Bazaar repository
    :param mapping: Mapping to use
    :param object_iter: Iterator over Git objects.
    """
    # TODO: a more (memory-)efficient implementation of this
    graph = []
    root_trees = {}
    revisions = {}
    # Find and convert commit objects
    for o in object_iter.iterobjects():
        if isinstance(o, Commit):
            rev = mapping.import_commit(o)
            root_trees[rev.revision_id] = object_iter[o.tree]
            revisions[rev.revision_id] = rev
            graph.append((rev.revision_id, rev.parent_ids))
            target_git_object_retriever._idmap.add_entry(o.sha().hexdigest(), "commit", (rev.revision_id, o._tree))
    # Order the revisions
    # Create the inventory objects
    for i, revid in enumerate(topo_sort(graph)):
        if pb is not None:
            pb.update("fetching revisions", i, len(graph))
        root_tree = root_trees[revid]
        rev = revisions[revid]
        # We have to do this here, since we have to walk the tree and 
        # we need to make sure to import the blobs / trees with the riht 
        # path; this may involve adding them more than once.
        inv = Inventory()
        inv.revision_id = rev.revision_id
        def lookup_object(sha):
            if sha in object_iter:
                return object_iter[sha]
            return target_git_object_retriever[sha]
        parent_invs = [repo.get_inventory(r) for r in rev.parent_ids]
        import_git_tree(repo, mapping, "", root_tree, inv, parent_invs, 
            target_git_object_retriever, lookup_object)
        repo.add_revision(rev.revision_id, rev, inv)


class InterGitNonGitRepository(InterRepository):

    _matching_repo_format = GitFormat()

    @staticmethod
    def _get_repo_format_to_test():
        return None

    def copy_content(self, revision_id=None, pb=None):
        """See InterRepository.copy_content."""
        self.fetch(revision_id, pb, find_ghosts=False)

    def fetch_objects(self, determine_wants, mapping, pb=None):
        def progress(text):
            pb.update("git: %s" % text.rstrip("\r\n"), 0, 0)
        graph_walker = BzrFetchGraphWalker(self.target, mapping)
        create_pb = None
        if pb is None:
            create_pb = pb = ui.ui_factory.nested_progress_bar()
        target_git_object_retriever = GitObjectConverter(self.target, mapping)
        
        try:
            self.target.lock_write()
            try:
                self.target.start_write_group()
                try:
                    objects_iter = self.source.fetch_objects(determine_wants, 
                                graph_walker, 
                                target_git_object_retriever.__getitem__, 
                                progress)
                    import_git_objects(self.target, mapping, objects_iter, 
                            target_git_object_retriever, pb)
                finally:
                    self.target.commit_write_group()
            finally:
                self.target.unlock()
        finally:
            if create_pb:
                create_pb.finished()

    def fetch(self, revision_id=None, pb=None, find_ghosts=False, 
              mapping=None, fetch_spec=None):
        self.fetch_refs(revision_id=revision_id, pb=pb, find_ghosts=find_ghosts,
                mapping=mapping, fetch_spec=fetch_spec)

    def fetch_refs(self, revision_id=None, pb=None, find_ghosts=False, 
              mapping=None, fetch_spec=None):
        if mapping is None:
            mapping = self.source.get_mapping()
        if revision_id is not None:
            interesting_heads = [revision_id]
        elif fetch_spec is not None:
            interesting_heads = fetch_spec.heads
        else:
            interesting_heads = None
        self._refs = {}
        def determine_wants(refs):
            self._refs = refs
            if interesting_heads is None:
                ret = [sha for (ref, sha) in refs.iteritems() if not ref.endswith("^{}")]
            else:
                ret = [mapping.revision_id_bzr_to_foreign(revid)[0] for revid in interesting_heads]
            return [rev for rev in ret if not self.target.has_revision(mapping.revision_id_foreign_to_bzr(rev))]
        self.fetch_objects(determine_wants, mapping, pb)
        return self._refs

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with GitRepository."""
        # FIXME: Also check target uses VersionedFile
        return (isinstance(source, GitRepository) and 
                target.supports_rich_root() and
                not isinstance(target, GitRepository))


class InterGitRepository(InterRepository):

    _matching_repo_format = GitFormat()

    @staticmethod
    def _get_repo_format_to_test():
        return None

    def copy_content(self, revision_id=None, pb=None):
        """See InterRepository.copy_content."""
        self.fetch(revision_id, pb, find_ghosts=False)

    def fetch(self, revision_id=None, pb=None, find_ghosts=False, 
              mapping=None, fetch_spec=None):
        if mapping is None:
            mapping = self.source.get_mapping()
        def progress(text):
            info("git: %s", text)
        r = self.target._git
        if revision_id is not None:
            args = [mapping.revision_id_bzr_to_foreign(revision_id)[0]]
        elif fetch_spec is not None:
            args = [mapping.revision_id_bzr_to_foreign(revid)[0] for revid in fetch_spec.heads]
        if fetch_spec is None and revision_id is None:
            determine_wants = r.object_store.determine_wants_all
        else:
            determine_wants = lambda x: [y for y in args if not y in r.object_store]

        graphwalker = SimpleFetchGraphWalker(r.heads().values(), r.get_parents)
        f, commit = r.object_store.add_pack()
        try:
            self.source._git.fetch_pack(path, determine_wants, graphwalker, f.write, progress)
            f.close()
            commit()
        except:
            f.close()
            raise

    @staticmethod
    def is_compatible(source, target):
        """Be compatible with GitRepository."""
        return (isinstance(source, GitRepository) and 
                isinstance(target, GitRepository))
