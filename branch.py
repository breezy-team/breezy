# Copyright (C) 2007 Canonical Ltd
# Copyright (C) 2009 Jelmer Vernooij <jelmer@samba.org>
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

"""An adapter between a Git Branch and a Bazaar Branch"""

from dulwich.objects import (
    Commit,
    Tag,
    )

from bzrlib import (
    branch,
    bzrdir,
    config,
    errors,
    repository,
    revision,
    tag,
    transport,
    )
from bzrlib.decorators import (
    needs_read_lock,
    )
from bzrlib.trace import (
    is_quiet,
    mutter,
    )

from bzrlib.plugins.git import (
    get_rich_root_format,
    )
from bzrlib.plugins.git.config import (
    GitBranchConfig,
    )
from bzrlib.plugins.git.errors import (
    NoPushSupport,
    NoSuchRef,
    )

from bzrlib.foreign import ForeignBranch


def extract_tags(refs):
    """Extract the tags from a refs dictionary.

    :param refs: Refs to extract the tags from.
    :return: Dictionary mapping tag names to SHA1s.
    """
    ret = {}
    for k,v in refs.iteritems():
        if k.startswith("refs/tags/") and not k.endswith("^{}"):
            v = refs.get(k+"^{}", v)
            ret[k[len("refs/tags/"):]] = v
    return ret


def branch_name_to_ref(name, default=None):
    """Map a branch name to a ref.

    :param name: Branch name
    :return: ref string
    """
    if name is None:
        return None
    if name == "HEAD":
        return "HEAD"
    if not name.startswith("refs/"):
        return "refs/heads/%s" % name
    else:
        return name


def ref_to_branch_name(ref):
    """Map a ref to a branch name

    :param ref: Ref
    :return: A branch name
    """
    if ref == "HEAD":
        return "HEAD"
    if ref.startswith("refs/heads/"):
        return ref[len("refs/heads/"):]
    raise ValueError("unable to map ref %s back to branch name")


class GitPullResult(branch.PullResult):

    def _lookup_revno(self, revid):
        assert isinstance(revid, str), "was %r" % revid
        # Try in source branch first, it'll be faster
        return self.target_branch.revision_id_to_revno(revid)

    @property
    def old_revno(self):
        return self._lookup_revno(self.old_revid)

    @property
    def new_revno(self):
        return self._lookup_revno(self.new_revid)


class LocalGitTagDict(tag.BasicTags):
    """Dictionary with tags in a local repository."""

    def __init__(self, branch):
        self.branch = branch
        self.repository = branch.repository

    def get_tag_dict(self):
        ret = {}
        for k,v in extract_tags(self.repository._git.get_refs()).iteritems():
            try:
                obj = self.repository._git[v]
            except KeyError:
                mutter("Tag %s points at unknown object %s, ignoring", v, obj)
                continue
            while isinstance(obj, Tag):
                v = obj.object[1]
                obj = self.repository._git[v]
            if not isinstance(obj, Commit):
                mutter("Tag %s points at object %r that is not a commit, "
                       "ignoring", k, obj)
                continue
            ret[k] = self.branch.mapping.revision_id_foreign_to_bzr(v)
        return ret

    def _set_tag_dict(self, to_dict):
        extra = set(self.repository._git.get_refs().keys())
        for k, revid in to_dict.iteritems():
            name = "refs/tags/%s" % k
            if name in extra:
                extra.remove(name)
            self.set_tag(k, revid)
        for name in extra:
            if name.startswith("refs/tags/"):
                del self.repository._git[name]
        
    def set_tag(self, name, revid):
        self.repository._git.refs["refs/tags/%s" % name], _ = \
            self.branch.mapping.revision_id_bzr_to_foreign(revid)


class DictTagDict(LocalGitTagDict):

    def __init__(self, branch, tags):
        super(DictTagDict, self).__init__(branch)
        self._tags = tags

    def get_tag_dict(self):
        return self._tags


class GitBranchFormat(branch.BranchFormat):

    def get_format_description(self):
        return 'Git Branch'

    def network_name(self):
        return "git"

    def supports_tags(self):
        return True

    def get_foreign_tests_branch_factory(self):
        from bzrlib.plugins.git.tests.test_branch import ForeignTestsBranchFactory
        return ForeignTestsBranchFactory()

    def make_tags(self, branch):
        if getattr(branch.repository, "get_refs", None) is not None:
            from bzrlib.plugins.git.remote import RemoteGitTagDict
            return RemoteGitTagDict(branch)
        else:
            return LocalGitTagDict(branch)


class GitBranch(ForeignBranch):
    """An adapter to git repositories for bzr Branch objects."""

    def __init__(self, bzrdir, repository, ref, lockfiles, tagsdict=None):
        self.repository = repository
        self._format = GitBranchFormat()
        self.control_files = lockfiles
        self.bzrdir = bzrdir
        super(GitBranch, self).__init__(repository.get_mapping())
        if tagsdict is not None:
            self.tags = DictTagDict(self, tagsdict)
        self.ref = ref
        self.name = ref_to_branch_name(ref)
        self._head = None
        self.base = bzrdir.root_transport.base

    def _get_checkout_format(self):
        """Return the most suitable metadir for a checkout of this branch.
        Weaves are used if this branch's repository uses weaves.
        """
        return get_rich_root_format()

    def get_child_submit_format(self):
        """Return the preferred format of submissions to this branch."""
        ret = self.get_config().get_user_option("child_submit_format")
        if ret is not None:
            return ret
        return "git"

    def _get_nick(self, local=False, possible_master_transports=None):
        """Find the nick name for this branch.

        :return: Branch nick
        """
        return self.name

    def _set_nick(self, nick):
        raise NotImplementedError

    nick = property(_get_nick, _set_nick)

    def __repr__(self):
        return "<%s(%r, %r)>" % (self.__class__.__name__, self.repository.base,
            self.ref)

    def generate_revision_history(self, revid, old_revid=None):
        # FIXME: Check that old_revid is in the ancestry of revid
        newhead, self.mapping = self.mapping.revision_id_bzr_to_foreign(revid)
        self._set_head(newhead)

    def lock_write(self):
        self.control_files.lock_write()

    def get_stacked_on_url(self):
        # Git doesn't do stacking (yet...)
        raise errors.UnstackableBranchFormat(self._format, self.base)

    def get_parent(self):
        """See Branch.get_parent()."""
        # FIXME: Set "origin" url from .git/config ?
        return None

    def set_parent(self, url):
        # FIXME: Set "origin" url in .git/config ?
        pass

    def lock_read(self):
        self.control_files.lock_read()

    def is_locked(self):
        return self.control_files.is_locked()

    def unlock(self):
        self.control_files.unlock()

    def get_physical_lock_status(self):
        return False

    @needs_read_lock
    def last_revision(self):
        # perhaps should escape this ?
        if self.head is None:
            return revision.NULL_REVISION
        return self.mapping.revision_id_foreign_to_bzr(self.head)

    def _basic_push(self, target, overwrite=False, stop_revision=None):
        return branch.InterBranch.get(self, target)._basic_push(
            overwrite, stop_revision)


class LocalGitBranch(GitBranch):
    """A local Git branch."""

    def __init__(self, bzrdir, repository, name, lockfiles, tagsdict=None):
        super(LocalGitBranch, self).__init__(bzrdir, repository, name, 
              lockfiles, tagsdict)
        if not name in repository._git.get_refs().keys():
            raise errors.NotBranchError(self.base)

    def create_checkout(self, to_location, revision_id=None, lightweight=False,
        accelerator_tree=None, hardlink=False):
        if lightweight:
            t = transport.get_transport(to_location)
            t.ensure_base()
            format = self._get_checkout_format()
            checkout = format.initialize_on_transport(t)
            from_branch = branch.BranchReferenceFormat().initialize(checkout,
                self)
            tree = checkout.create_workingtree(revision_id,
                from_branch=from_branch, hardlink=hardlink)
            return tree
        else:
            return self._create_heavyweight_checkout(to_location, revision_id,
            hardlink)

    def _create_heavyweight_checkout(self, to_location, revision_id=None,
                                     hardlink=False):
        """Create a new heavyweight checkout of this branch.

        :param to_location: URL of location to create the new checkout in.
        :param revision_id: Revision that should be the tip of the checkout.
        :param hardlink: Whether to hardlink
        :return: WorkingTree object of checkout.
        """
        checkout_branch = bzrdir.BzrDir.create_branch_convenience(
            to_location, force_new_tree=False, format=get_rich_root_format())
        checkout = checkout_branch.bzrdir
        checkout_branch.bind(self)
        # pull up to the specified revision_id to set the initial
        # branch tip correctly, and seed it with history.
        checkout_branch.pull(self, stop_revision=revision_id)
        return checkout.create_workingtree(revision_id, hardlink=hardlink)

    def _gen_revision_history(self):
        if self.head is None:
            return []
        ret = list(self.repository.iter_reverse_revision_history(
            self.last_revision()))
        ret.reverse()
        return ret

    def _get_head(self):
        try:
            return self.repository._git.ref(self.ref)
        except KeyError:
            return None

    def set_last_revision_info(self, revno, revid):
        self.set_last_revision(revid)

    def set_last_revision(self, revid):
        (newhead, self.mapping) = self.mapping.revision_id_bzr_to_foreign(
                revid)
        self.head = newhead

    def _set_head(self, value):
        self._head = value
        self.repository._git.refs[self.ref] = self._head
        self._clear_cached_state()

    head = property(_get_head, _set_head)

    def get_config(self):
        return GitBranchConfig(self)

    def get_push_location(self):
        """See Branch.get_push_location."""
        push_loc = self.get_config().get_user_option('push_location')
        return push_loc

    def set_push_location(self, location):
        """See Branch.set_push_location."""
        self.get_config().set_user_option('push_location', location,
                                          store=config.STORE_LOCATION)

    def supports_tags(self):
        return True


class GitBranchPullResult(branch.PullResult):

    def report(self, to_file):
        if not is_quiet():
            if self.old_revid == self.new_revid:
                to_file.write('No revisions to pull.\n')
            elif self.new_git_head is not None:
                to_file.write('Now on revision %d (git sha: %s).\n' %
                        (self.new_revno, self.new_git_head))
            else:
                to_file.write('Now on revision %d.\n' % (self.new_revno,))
        self._show_tag_conficts(to_file)


class GitBranchPushResult(branch.BranchPushResult):

    def _lookup_revno(self, revid):
        assert isinstance(revid, str), "was %r" % revid
        # Try in source branch first, it'll be faster
        try:
            return self.source_branch.revision_id_to_revno(revid)
        except errors.NoSuchRevision:
            # FIXME: Check using graph.find_distance_to_null() ?
            return self.target_branch.revision_id_to_revno(revid)

    @property
    def old_revno(self):
        return self._lookup_revno(self.old_revid)

    @property
    def new_revno(self):
        return self._lookup_revno(self.new_revid)


class InterFromGitBranch(branch.GenericInterBranch):
    """InterBranch implementation that pulls from Git into bzr."""

    @classmethod
    def _get_interrepo(self, source, target):
        return repository.InterRepository.get(source.repository,
            target.repository)

    @classmethod
    def is_compatible(cls, source, target):
        return (isinstance(source, GitBranch) and
                not isinstance(target, GitBranch) and
                (getattr(cls._get_interrepo(source, target), "fetch_objects", None) is not None))

    def _update_revisions(self, stop_revision=None, overwrite=False,
        graph=None, limit=None):
        """Like InterBranch.update_revisions(), but with additions.

        Compared to the `update_revisions()` below, this function takes a
        `limit` argument that limits how many git commits will be converted
        and returns the new git head.
        """
        interrepo = self._get_interrepo(self.source, self.target)
        def determine_wants(heads):
            if not self.source.ref in heads:
                raise NoSuchRef(self.source.ref, heads.keys())
            if stop_revision is not None:
                self._last_revid = stop_revision
                head, mapping = self.source.repository.lookup_bzr_revision_id(
                    stop_revision)
            else:
                head = heads[self.source.ref]
                self._last_revid = self.source.mapping.revision_id_foreign_to_bzr(
                    head)
            if self.target.repository.has_revision(self._last_revid):
                return []
            return [head]
        pack_hint, head = interrepo.fetch_objects(
            determine_wants, self.source.mapping, limit=limit)
        if pack_hint is not None and self.target.repository._format.pack_compresses:
            self.target.repository.pack(hint=pack_hint)
        if head is not None:
            self._last_revid = self.source.mapping.revision_id_foreign_to_bzr(head)
        if overwrite:
            prev_last_revid = None
        else:
            prev_last_revid = self.target.last_revision()
        self.target.generate_revision_history(self._last_revid,
            prev_last_revid)
        return head

    def update_revisions(self, stop_revision=None, overwrite=False,
                         graph=None):
        """See InterBranch.update_revisions()."""
        self._update_revisions(stop_revision, overwrite, graph)

    def pull(self, overwrite=False, stop_revision=None,
             possible_transports=None, _hook_master=None, run_hooks=True,
             _override_hook_target=None, local=False, limit=None):
        """See Branch.pull.

        :param _hook_master: Private parameter - set the branch to
            be supplied as the master to pull hooks.
        :param run_hooks: Private parameter - if false, this branch
            is being called because it's the master of the primary branch,
            so it should not run its hooks.
        :param _override_hook_target: Private parameter - set the branch to be
            supplied as the target_branch to pull hooks.
        :param limit: Only import this many revisons.  `None`, the default,
            means import all revisions.
        """
        # This type of branch can't be bound.
        if local:
            raise errors.LocalRequiresBoundBranch()
        result = GitBranchPullResult()
        result.source_branch = self.source
        if _override_hook_target is None:
            result.target_branch = self.target
        else:
            result.target_branch = _override_hook_target
        self.source.lock_read()
        try:
            # We assume that during 'pull' the target repository is closer than
            # the source one.
            graph = self.target.repository.get_graph(self.source.repository)
            (result.old_revno, result.old_revid) = \
                self.target.last_revision_info()
            result.new_git_head = self._update_revisions(
                stop_revision, overwrite=overwrite, graph=graph, limit=limit)
            result.tag_conflicts = self.source.tags.merge_to(self.target.tags,
                overwrite)
            (result.new_revno, result.new_revid) = \
                self.target.last_revision_info()
            if _hook_master:
                result.master_branch = _hook_master
                result.local_branch = result.target_branch
            else:
                result.master_branch = result.target_branch
                result.local_branch = None
            if run_hooks:
                for hook in branch.Branch.hooks['post_pull']:
                    hook(result)
        finally:
            self.source.unlock()
        return result

    def _basic_push(self, overwrite=False, stop_revision=None):
        result = branch.BranchPushResult()
        result.source_branch = self.source
        result.target_branch = self.target
        graph = self.target.repository.get_graph(self.source.repository)
        result.old_revno, result.old_revid = self.target.last_revision_info()
        result.new_git_head = self._update_revisions(
            stop_revision, overwrite=overwrite, graph=graph)
        result.tag_conflicts = self.source.tags.merge_to(self.target.tags,
            overwrite)
        result.new_revno, result.new_revid = self.target.last_revision_info()
        return result


class InterGitBranch(branch.GenericInterBranch):
    """InterBranch implementation that pulls between Git branches."""


class InterGitLocalRemoteBranch(InterGitBranch):
    """InterBranch that copies from a local to a remote git branch."""

    @classmethod
    def is_compatible(self, source, target):
        from bzrlib.plugins.git.remote import RemoteGitBranch
        return (isinstance(source, LocalGitBranch) and
                isinstance(target, RemoteGitBranch))

    def _basic_push(self, overwrite=False, stop_revision=None):
        result = GitBranchPushResult()
        result.source_branch = self.source
        result.target_branch = self.target
        if stop_revision is None:
            stop_revision = self.source.last_revision()
        # FIXME: Check for diverged branches
        def get_changed_refs(old_refs):
            result.old_revid = self.target.mapping.revision_id_foreign_to_bzr(old_refs.get(self.target.ref, "0" * 40))
            refs = { self.target.ref: self.source.repository.lookup_bzr_revision_id(stop_revision)[0] }
            result.new_revid = stop_revision
            for name, sha in self.source.repository._git.refs.as_dict("refs/tags").iteritems():
                refs["refs/tags/%s" % name] = sha
            return refs
        self.target.repository.send_pack(get_changed_refs,
            self.source.repository._git.object_store.generate_pack_contents)
        return result


class InterGitRemoteLocalBranch(InterGitBranch):
    """InterBranch that copies from a remote to a local git branch."""

    @classmethod
    def is_compatible(self, source, target):
        from bzrlib.plugins.git.remote import RemoteGitBranch
        return (isinstance(source, RemoteGitBranch) and
                isinstance(target, LocalGitBranch))

    def _basic_push(self, overwrite=False, stop_revision=None):
        result = branch.BranchPushResult()
        result.source_branch = self.source
        result.target_branch = self.target
        result.old_revid = self.target.last_revision()
        refs, stop_revision = self.update_refs(stop_revision)
        self.target.generate_revision_history(stop_revision, result.old_revid)
        self.update_tags(refs)
        result.new_revid = self.target.last_revision()
        return result

    def update_tags(self, refs):
        for name, v in extract_tags(refs).iteritems():
            revid = self.target.mapping.revision_id_foreign_to_bzr(v)
            self.target.tags.set_tag(name, revid)

    def update_refs(self, stop_revision=None):
        interrepo = repository.InterRepository.get(self.source.repository,
            self.target.repository)
        if stop_revision is None:
            refs = interrepo.fetch_refs(branches=["HEAD"])
            stop_revision = self.target.mapping.revision_id_foreign_to_bzr(refs["HEAD"])
        else:
            refs = interrepo.fetch_refs(revision_id=stop_revision)
        return refs, stop_revision

    def pull(self, stop_revision=None, overwrite=False,
        possible_transports=None, run_hooks=True,local=False):
        # This type of branch can't be bound.
        if local:
            raise errors.LocalRequiresBoundBranch()
        result = GitPullResult()
        result.source_branch = self.source
        result.target_branch = self.target
        result.old_revid = self.target.last_revision()
        refs, stop_revision = self.update_refs(stop_revision)
        self.target.generate_revision_history(stop_revision, result.old_revid)
        self.update_tags(refs)
        result.new_revid = self.target.last_revision()
        return result


class InterToGitBranch(branch.InterBranch):
    """InterBranch implementation that pulls from Git into bzr."""

    @staticmethod
    def _get_branch_formats_to_test():
        return None, None

    @classmethod
    def is_compatible(self, source, target):
        return (not isinstance(source, GitBranch) and
                isinstance(target, GitBranch))

    def update_revisions(self, *args, **kwargs):
        raise NoPushSupport()

    def push(self, overwrite=True, stop_revision=None,
             _override_hook_source_branch=None):
        raise NoPushSupport()

    def lossy_push(self, stop_revision=None):
        result = GitBranchPushResult()
        result.source_branch = self.source
        result.target_branch = self.target
        if stop_revision is None:
            stop_revision = self.source.last_revision()
        # FIXME: Check for diverged branches
        refs = { self.target.ref: stop_revision }
        for name, revid in self.source.tags.get_tag_dict().iteritems():
            if self.source.repository.has_revision(revid):
                refs["refs/tags/%s" % name] = revid
        revidmap, old_refs, new_refs = self.target.repository.dfetch_refs(
            self.source.repository, refs)
        result.old_revid = self.target.mapping.revision_id_foreign_to_bzr(
            old_refs.get(self.target.ref, "0" * 40))
        result.new_revid = self.target.mapping.revision_id_foreign_to_bzr(
            new_refs[self.target.ref])
        result.revidmap = revidmap
        return result


branch.InterBranch.register_optimiser(InterGitRemoteLocalBranch)
branch.InterBranch.register_optimiser(InterFromGitBranch)
branch.InterBranch.register_optimiser(InterToGitBranch)
branch.InterBranch.register_optimiser(InterGitLocalRemoteBranch)
