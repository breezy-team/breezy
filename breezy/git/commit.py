# Copyright (C) 2009-2018 Jelmer Vernooij <jelmer@jelmer.uk>
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA


"""Support for committing in native Git working trees."""

from dulwich.index import (
    commit_tree,
    read_submodule_head,
    )
import stat

from .. import (
    bugtracker,
    config as _mod_config,
    gpg,
    osutils,
    revision as _mod_revision,
    trace,
    )
from ..errors import (
    BzrError,
    RootMissing,
    UnsupportedOperation,
    )
from ..repository import (
    CommitBuilder,
    )

from dulwich.objects import (
    Blob,
    Commit,
    )


from .mapping import (
    encode_git_path,
    object_mode,
    fix_person_identifier,
    )
from .tree import entry_factory


class GitCommitBuilder(CommitBuilder):
    """Commit builder for Git repositories."""

    supports_record_entry_contents = False

    def __init__(self, *args, **kwargs):
        super(GitCommitBuilder, self).__init__(*args, **kwargs)
        self.random_revid = True
        self._validate_revprops(self._revprops)
        self.store = self.repository._git.object_store
        self._blobs = {}
        self._inv_delta = []
        self._deleted_paths = set()
        self._any_changes = False
        self._mapping = self.repository.get_mapping()

    def any_changes(self):
        return self._any_changes

    def record_iter_changes(self, workingtree, basis_revid, iter_changes):
        seen_root = False
        for change in iter_changes:
            if change.kind == (None, None):
                # Ephemeral
                continue
            if change.versioned[0] and not change.copied:
                file_id = self._mapping.generate_file_id(change.path[0])
            elif change.versioned[1]:
                file_id = self._mapping.generate_file_id(change.path[1])
            else:
                file_id = None
            if change.path[1]:
                parent_id_new = self._mapping.generate_file_id(osutils.dirname(change.path[1]))
            else:
                parent_id_new = None
            if change.kind[1] in ("directory",):
                self._inv_delta.append(
                    (change.path[0], change.path[1], file_id,
                     entry_factory[change.kind[1]](
                         file_id, change.name[1], parent_id_new)))
                if change.kind[0] in ("file", "symlink"):
                    self._blobs[encode_git_path(change.path[0])] = None
                    self._any_changes = True
                if change.path[1] == "":
                    seen_root = True
                continue
            self._any_changes = True
            if change.path[1] is None:
                self._inv_delta.append((change.path[0], change.path[1], file_id, None))
                self._deleted_paths.add(encode_git_path(change.path[0]))
                continue
            try:
                entry_kls = entry_factory[change.kind[1]]
            except KeyError:
                raise KeyError("unknown kind %s" % change.kind[1])
            entry = entry_kls(file_id, change.name[1], parent_id_new)
            if change.kind[1] == "file":
                entry.executable = change.executable[1]
                blob = Blob()
                f, st = workingtree.get_file_with_stat(change.path[1])
                try:
                    blob.data = f.read()
                finally:
                    f.close()
                sha = blob.id
                if st is not None:
                    entry.text_size = st.st_size
                else:
                    entry.text_size = len(blob.data)
                entry.git_sha1 = sha
                self.store.add_object(blob)
            elif change.kind[1] == "symlink":
                symlink_target = workingtree.get_symlink_target(change.path[1])
                blob = Blob()
                blob.data = encode_git_path(symlink_target)
                self.store.add_object(blob)
                sha = blob.id
                entry.symlink_target = symlink_target
                st = None
            elif change.kind[1] == "tree-reference":
                sha = read_submodule_head(workingtree.abspath(change.path[1]))
                reference_revision = workingtree.get_reference_revision(change.path[1])
                entry.reference_revision = reference_revision
                st = None
            else:
                raise AssertionError("Unknown kind %r" % change.kind[1])
            mode = object_mode(change.kind[1], change.executable[1])
            self._inv_delta.append((change.path[0], change.path[1], file_id, entry))
            if change.path[0] is not None:
                self._deleted_paths.add(encode_git_path(change.path[0]))
            self._blobs[encode_git_path(change.path[1])] = (mode, sha)
            if st is not None:
                yield change.path[1], (entry.git_sha1, st)
        if not seen_root and len(self.parents) == 0:
            raise RootMissing()
        if getattr(workingtree, "basis_tree", False):
            basis_tree = workingtree.basis_tree()
        else:
            if len(self.parents) == 0:
                basis_revid = _mod_revision.NULL_REVISION
            else:
                basis_revid = self.parents[0]
            basis_tree = self.repository.revision_tree(basis_revid)
        # Fill in entries that were not changed
        for entry in basis_tree._iter_tree_contents(include_trees=False):
            if entry.path in self._blobs:
                continue
            if entry.path in self._deleted_paths:
                continue
            self._blobs[entry.path] = (entry.mode, entry.sha)
        self.new_inventory = None

    def update_basis(self, tree):
        # Nothing to do here
        pass

    def finish_inventory(self):
        # eliminate blobs that were removed
        self._blobs = {k: v for (k, v) in self._blobs.items()}

    def _iterblobs(self):
        return ((path, sha, mode) for (path, (mode, sha))
                in self._blobs.items())

    def commit(self, message):
        self._validate_unicode_text(message, 'commit message')
        c = Commit()
        c.parents = [self.repository.lookup_bzr_revision_id(
            revid)[0] for revid in self.parents]
        c.tree = commit_tree(self.store, self._iterblobs())
        encoding = self._revprops.pop(u'git-explicit-encoding', 'utf-8')
        c.encoding = encoding.encode('ascii')
        c.committer = fix_person_identifier(self._committer.encode(encoding))
        pseudoheaders = []
        try:
            author = self._revprops.pop('author')
        except KeyError:
            try:
                authors = self._revprops.pop('authors').splitlines()
            except KeyError:
                author = self._committer
            else:
                if len(authors) == 0:
                    author = self._committer
                else:
                    author = authors[0]
                    for coauthor in authors[1:]:
                        pseudoheaders.append(
                            b'Co-authored-by: %s'
                            % fix_person_identifier(coauthor.encode(encoding)))
        c.author = fix_person_identifier(author.encode(encoding))
        bugstext = self._revprops.pop('bugs', None)
        if bugstext is not None:
            for url, status in bugtracker.decode_bug_urls(bugstext):
                if status == bugtracker.FIXED:
                    pseudoheaders.append(("Fixes: %s" % url).encode(encoding))
                elif status == bugtracker.RELATED:
                    pseudoheaders.append(("Bug: %s" % url).encode(encoding))
                else:
                    raise bugtracker.InvalidBugStatus(status)
        if self._revprops:
            raise NotImplementedError(self._revprops)
        c.commit_time = int(self._timestamp)
        c.author_time = int(self._timestamp)
        c.commit_timezone = self._timezone
        c.author_timezone = self._timezone
        c.message = message.encode(encoding)
        if pseudoheaders:
            if not c.message.endswith(b"\n"):
                c.message += b"\n"
            c.message += b"\n" + b"".join([line + b"\n" for line in pseudoheaders])
        create_signatures = self._config_stack.get('create_signatures')
        if (create_signatures in (
                _mod_config.SIGN_ALWAYS, _mod_config.SIGN_WHEN_POSSIBLE)):
            strategy = gpg.GPGStrategy(self._config_stack)
            try:
                c.gpgsig = strategy.sign(c.as_raw_string(), gpg.MODE_DETACH)
            except gpg.GpgNotInstalled as e:
                if create_signatures == _mod_config.SIGN_WHEN_POSSIBLE:
                    trace.note('skipping commit signature: %s', e)
                else:
                    raise
            except gpg.SigningFailed as e:
                if create_signatures == _mod_config.SIGN_WHEN_POSSIBLE:
                    trace.note('commit signature failed: %s', e)
                else:
                    raise
        self.store.add_object(c)
        self.repository.commit_write_group()
        self._new_revision_id = self._mapping.revision_id_foreign_to_bzr(c.id)
        return self._new_revision_id

    def abort(self):
        if self.repository.is_in_write_group():
            self.repository.abort_write_group()

    def revision_tree(self):
        return self.repository.revision_tree(self._new_revision_id)

    def get_basis_delta(self):
        return self._inv_delta

    def update_basis_by_delta(self, revid, delta):
        pass
