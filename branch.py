# Copyright (C) 2007 Canonical Ltd
# Copyright (C) 2009-2010 Jelmer Vernooij <jelmer@samba.org>
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

from collections import defaultdict

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
from bzrlib.revision import (
    NULL_REVISION,
    )
from bzrlib.trace import (
    is_quiet,
    mutter,
    )

from bzrlib.plugins.git.config import (
    GitBranchConfig,
    )
from bzrlib.plugins.git.errors import (
    NoPushSupport,
    NoSuchRef,
    )
from bzrlib.plugins.git.refs import (
    extract_tags,
    is_tag,
    ref_to_branch_name,
    ref_to_tag_name,
    tag_name_to_ref,
    UnpeelMap,
    )

from bzrlib.foreign import ForeignBranch


class GitPullResult(branch.PullResult):
    """Result of a pull from a Git branch."""

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


class GitTags(tag.BasicTags):
    """Ref-based tag dictionary."""

    def __init__(self, branch):
        self.branch = branch
        self.repository = branch.repository

    def get_refs(self):
        raise NotImplementedError(self.get_refs)

    def _iter_tag_refs(self, refs):
        raise NotImplementedError(self._iter_tag_refs)

    def _merge_to_git(self, to_tags, refs, overwrite=False):
        target_repo = to_tags.repository
        conflicts = []
        for k, v in refs.iteritems():
            if not is_tag(k):
                continue
            if overwrite or not k in self.target.repository.refs:
                target_repo.refs[k] = v
            elif target_repo.repository.refs[k] == v:
                pass
            else:
                conflicts.append((ref_to_tag_name(k), v, target_repo.refs[k]))
        return conflicts

    def _merge_to_non_git(self, to_tags, refs, overwrite=False):
        unpeeled_map = defaultdict(set)
        conflicts = []
        result = dict(to_tags.get_tag_dict())
        for n, peeled, unpeeled, bzr_revid in self._iter_tag_refs(refs):
            if unpeeled is not None:
                unpeeled_map[peeled].add(unpeeled)
            if n not in result or overwrite:
                result[n] = bzr_revid
            elif result[n] == bzr_revid:
                pass
            else:
                conflicts.append((n, result[n], bzr_revid))
        to_tags._set_tag_dict(result)
        if len(unpeeled_map) > 0:
            map_file = UnpeelMap.from_repository(to_tags.branch.repository)
            map_file.update(unpeeled_map)
            map_file.save_in_repository(to_tags.branch.repository)
        return conflicts

    def merge_to(self, to_tags, overwrite=False, ignore_master=False,
                 source_refs=None):
        if source_refs is None:
            source_refs = self.get_refs()
        if self == to_tags:
            return
        if isinstance(to_tags, GitTags):
            return self._merge_to_git(to_tags, source_refs,
                                      overwrite=overwrite)
        else:
            if ignore_master:
                master = None
            else:
                master = to_tags.branch.get_master_branch()
            conflicts = self._merge_to_non_git(to_tags, source_refs,
                                              overwrite=overwrite)
            if master is not None:
                conflicts += self.merge_to(to_tags, overwrite=overwrite,
                                           source_refs=source_refs,
                                           ignore_master=ignore_master)
            return conflicts

    def get_tag_dict(self):
        ret = {}
        refs = self.get_refs()
        for (name, peeled, unpeeled, bzr_revid) in self._iter_tag_refs(refs):
            ret[name] = bzr_revid
        return ret


class LocalGitTagDict(GitTags):
    """Dictionary with tags in a local repository."""

    def __init__(self, branch):
        super(LocalGitTagDict, self).__init__(branch)
        self.refs = self.repository._git.refs

    def get_refs(self):
        return self.repository._git.get_refs()

    def _iter_tag_refs(self, refs):
        """Iterate over the tag refs.

        :param refs: Refs dictionary (name -> git sha1)
        :return: iterator over (name, peeled_sha1, unpeeled_sha1, bzr_revid)
        """
        for k, (peeled, unpeeled) in extract_tags(refs).iteritems():
            try:
                obj = self.repository._git[peeled]
            except KeyError:
                mutter("Tag %s points at unknown object %s, ignoring", peeled,
                       obj)
                continue
            # FIXME: this shouldn't really be necessary, the repository
            # already should have these unpeeled.
            while isinstance(obj, Tag):
                peeled = obj.object[1]
                obj = self.repository._git[peeled]
            if not isinstance(obj, Commit):
                mutter("Tag %s points at object %r that is not a commit, "
                       "ignoring", k, obj)
                continue
            yield (k, peeled, unpeeled,
                   self.branch.lookup_foreign_revision_id(peeled))

    def _set_tag_dict(self, to_dict):
        extra = set(self.get_refs().keys())
        for k, revid in to_dict.iteritems():
            name = tag_name_to_ref(k)
            if name in extra:
                extra.remove(name)
            self.set_tag(k, revid)
        for name in extra:
            if is_tag(name):
                del self.repository._git[name]

    def set_tag(self, name, revid):
        self.refs[tag_name_to_ref(name)], _ = \
            self.branch.lookup_bzr_revision_id(revid)


class DictTagDict(tag.BasicTags):

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


class GitReadLock(object):

    def __init__(self, unlock):
        self.unlock = unlock


class GitWriteLock(object):

    def __init__(self, unlock):
        self.unlock = unlock


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
        return bzrdir.format_registry.make_bzrdir("default")

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
        return self.name or "HEAD"

    def _set_nick(self, nick):
        raise NotImplementedError

    nick = property(_get_nick, _set_nick)

    def __repr__(self):
        return "<%s(%r, %r)>" % (self.__class__.__name__, self.repository.base,
            self.ref or "HEAD")

    def generate_revision_history(self, revid, old_revid=None):
        # FIXME: Check that old_revid is in the ancestry of revid
        newhead, self.mapping = self.mapping.revision_id_bzr_to_foreign(revid)
        self._set_head(newhead)

    def lock_write(self):
        self.control_files.lock_write()
        return GitWriteLock(self.unlock)

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
        return GitReadLock(self.unlock)

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
        return self.lookup_foreign_revision_id(self.head)

    def _basic_push(self, target, overwrite=False, stop_revision=None):
        return branch.InterBranch.get(self, target)._basic_push(
            overwrite, stop_revision)

    def lookup_foreign_revision_id(self, foreign_revid):
        return self.repository.lookup_foreign_revision_id(foreign_revid,
            self.mapping)

    def lookup_bzr_revision_id(self, revid):
        return self.repository.lookup_bzr_revision_id(
            revid, mapping=self.mapping)


class LocalGitBranch(GitBranch):
    """A local Git branch."""

    def __init__(self, bzrdir, repository, name, lockfiles, tagsdict=None):
        super(LocalGitBranch, self).__init__(bzrdir, repository, name,
              lockfiles, tagsdict)
        refs = repository._git.get_refs()
        if not (name in refs.keys() or "HEAD" in refs.keys()):
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
            to_location, force_new_tree=False)
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
            return self.repository._git.ref(self.ref or "HEAD")
        except KeyError:
            return None

    def set_last_revision_info(self, revno, revid):
        self.set_last_revision(revid)

    def set_last_revision(self, revid):
        (newhead, self.mapping) = self.repository.lookup_bzr_revision_id(revid)
        self.head = newhead

    def _set_head(self, value):
        self._head = value
        self.repository._git.refs[self.ref or "HEAD"] = self._head
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


def _quick_lookup_revno(local_branch, remote_branch, revid):
    assert isinstance(revid, str), "was %r" % revid
    # Try in source branch first, it'll be faster
    try:
        return local_branch.revision_id_to_revno(revid)
    except errors.NoSuchRevision:
        graph = local_branch.repository.get_graph()
        try:
            return graph.find_distance_to_null(revid)
        except errors.GhostRevisionsHaveNoRevno:
            # FIXME: Check using graph.find_distance_to_null() ?
            return remote_branch.revision_id_to_revno(revid)


class GitBranchPullResult(branch.PullResult):

    def __init__(self):
        super(GitBranchPullResult, self).__init__()
        self.new_git_head = None
        self._old_revno = None
        self._new_revno = None

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

    def _lookup_revno(self, revid):
        return _quick_lookup_revno(self.target_branch, self.source_branch, revid)

    def _get_old_revno(self):
        if self._old_revno is not None:
            return self._old_revno
        return self._lookup_revno(self.old_revid)

    def _set_old_revno(self, revno):
        self._old_revno = revno

    old_revno = property(_get_old_revno, _set_old_revno)

    def _get_new_revno(self):
        if self._new_revno is not None:
            return self._new_revno
        return self._lookup_revno(self.new_revid)

    def _set_new_revno(self, revno):
        self._new_revno = revno

    new_revno = property(_get_new_revno, _set_new_revno)


class GitBranchPushResult(branch.BranchPushResult):

    def _lookup_revno(self, revid):
        return _quick_lookup_revno(self.source_branch, self.target_branch, revid)

    @property
    def old_revno(self):
        return self._lookup_revno(self.old_revid)

    @property
    def new_revno(self):
        new_original_revno = getattr(self, "new_original_revno", None)
        if new_original_revno:
            return new_original_revno
        if getattr(self, "new_original_revid", None) is not None:
            return self._lookup_revno(self.new_original_revid)
        return self._lookup_revno(self.new_revid)


class InterFromGitBranch(branch.GenericInterBranch):
    """InterBranch implementation that pulls from Git into bzr."""

    @staticmethod
    def _get_branch_formats_to_test():
        return []

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
        and returns the new git head and remote refs.
        """
        interrepo = self._get_interrepo(self.source, self.target)
        def determine_wants(heads):
            if self.source.ref is not None and not self.source.ref in heads:
                raise NoSuchRef(self.source.ref, heads.keys())
            if stop_revision is not None:
                self._last_revid = stop_revision
                head, mapping = self.source.repository.lookup_bzr_revision_id(
                    stop_revision)
            else:
                if self.source.ref is not None:
                    head = heads[self.source.ref]
                else:
                    head = heads["HEAD"]
                self._last_revid = self.source.lookup_foreign_revision_id(head)
            if self.target.repository.has_revision(self._last_revid):
                return []
            return [head]
        pack_hint, head, refs = interrepo.fetch_objects(
            determine_wants, self.source.mapping, limit=limit)
        if (pack_hint is not None and
            self.target.repository._format.pack_compresses):
            self.target.repository.pack(hint=pack_hint)
        if head is not None:
            self._last_revid = self.source.lookup_foreign_revision_id(head)
        if overwrite:
            prev_last_revid = None
        else:
            prev_last_revid = self.target.last_revision()
        self.target.generate_revision_history(self._last_revid,
            prev_last_revid)
        return head, refs

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
            result.new_git_head, remote_refs = self._update_revisions(
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
        result.new_git_head, remote_refs = self._update_revisions(
            stop_revision, overwrite=overwrite, graph=graph)
        result.tag_conflicts = self.source.tags.merge_to(self.target.tags,
            overwrite)
        result.new_revno, result.new_revid = self.target.last_revision_info()
        return result


class InterGitBranch(branch.GenericInterBranch):
    """InterBranch implementation that pulls between Git branches."""


class InterGitLocalRemoteBranch(InterGitBranch):
    """InterBranch that copies from a local to a remote git branch."""

    @staticmethod
    def _get_branch_formats_to_test():
        return []

    @classmethod
    def is_compatible(self, source, target):
        from bzrlib.plugins.git.remote import RemoteGitBranch
        return (isinstance(source, LocalGitBranch) and
                isinstance(target, RemoteGitBranch))

    def _basic_push(self, overwrite=False, stop_revision=None):
        from dulwich.protocol import ZERO_SHA
        result = GitBranchPushResult()
        result.source_branch = self.source
        result.target_branch = self.target
        if stop_revision is None:
            stop_revision = self.source.last_revision()
        # FIXME: Check for diverged branches
        def get_changed_refs(old_refs):
            result.old_revid = self.target.lookup_foreign_revision_id(old_refs.get(self.target.ref, ZERO_SHA))
            refs = { self.target.ref: self.source.repository.lookup_bzr_revision_id(stop_revision)[0] }
            result.new_revid = stop_revision
            for name, sha in self.source.repository._git.refs.as_dict("refs/tags").iteritems():
                refs[tag_name_to_ref(name)] = sha
            return refs
        self.target.repository.send_pack(get_changed_refs,
            self.source.repository._git.object_store.generate_pack_contents)
        return result


class InterGitRemoteLocalBranch(InterGitBranch):
    """InterBranch that copies from a remote to a local git branch."""

    @staticmethod
    def _get_branch_formats_to_test():
        return []

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
        result.tag_conflicts = self.source.tags.merge_to(self.target.tags,
            source_refs=refs, overwrite=overwrite)
        result.new_revid = self.target.last_revision()
        return result

    def update_refs(self, stop_revision=None):
        interrepo = repository.InterRepository.get(self.source.repository,
            self.target.repository)
        if stop_revision is None:
            refs = interrepo.fetch(branches=["HEAD"])
            stop_revision = self.target.lookup_foreign_revision_id(refs["HEAD"])
        else:
            refs = interrepo.fetch(revision_id=stop_revision)
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
        result.tag_conflicts = self.source.tags.merge_to(self.target.tags,
            overwrite=overwrite, source_refs=refs)
        result.new_revid = self.target.last_revision()
        return result


class InterToGitBranch(branch.GenericInterBranch):
    """InterBranch implementation that pulls from Git into bzr."""

    def __init__(self, source, target):
        super(InterToGitBranch, self).__init__(source, target)
        self.interrepo = repository.InterRepository.get(source.repository,
                                           target.repository)

    @staticmethod
    def _get_branch_formats_to_test():
        return []

    @classmethod
    def is_compatible(self, source, target):
        return (not isinstance(source, GitBranch) and
                isinstance(target, GitBranch))

    def update_revisions(self, *args, **kwargs):
        raise NoPushSupport()

    def _get_new_refs(self, stop_revision=None):
        if stop_revision is None:
            (stop_revno, stop_revision) = self.source.last_revision_info()
        assert type(stop_revision) is str
        main_ref = self.target.ref or "refs/heads/master"
        refs = { main_ref: (None, stop_revision) }
        for name, revid in self.source.tags.get_tag_dict().iteritems():
            if self.source.repository.has_revision(revid):
                refs[tag_name_to_ref(name)] = (None, revid)
        return refs, main_ref, (stop_revno, stop_revision)

    def pull(self, overwrite=False, stop_revision=None, local=False,
             possible_transports=None):
        from dulwich.protocol import ZERO_SHA
        result = GitBranchPullResult()
        result.source_branch = self.source
        result.target_branch = self.target
        new_refs, main_ref, stop_revinfo = self._get_new_refs(stop_revision)
        def update_refs(old_refs):
            refs = dict(old_refs)
            # FIXME: Check for diverged branches
            refs.update(new_refs)
            return refs
        old_refs, new_refs = self.interrepo.fetch_refs(update_refs)
        (result.old_revid, old_sha1) = old_refs.get(main_ref, (ZERO_SHA, NULL_REVISION))
        if result.old_revid is None:
            result.old_revid = self.target.lookup_foreign_revision_id(old_sha1)
        result.new_revid = new_refs[main_ref][1]
        return result

    def push(self, overwrite=False, stop_revision=None,
             _override_hook_source_branch=None):
        from dulwich.protocol import ZERO_SHA
        result = GitBranchPushResult()
        result.source_branch = self.source
        result.target_branch = self.target
        new_refs, main_ref, stop_revinfo = self._get_new_refs(stop_revision)
        def update_refs(old_refs):
            refs = dict(old_refs)
            # FIXME: Check for diverged branches
            refs.update(new_refs)
            return refs
        old_refs, new_refs = self.interrepo.fetch_refs(update_refs)
        (result.old_revid, old_sha1) = old_refs.get(main_ref, (ZERO_SHA, NULL_REVISION))
        if result.old_revid is None:
            result.old_revid = self.target.lookup_foreign_revision_id(old_sha1)
        result.new_revid = new_refs[main_ref][1]
        return result

    def lossy_push(self, stop_revision=None):
        result = GitBranchPushResult()
        result.source_branch = self.source
        result.target_branch = self.target
        new_refs, main_ref, stop_revinfo = self._get_new_refs(stop_revision)
        def update_refs(old_refs):
            refs = dict(old_refs)
            # FIXME: Check for diverged branches
            refs.update(new_refs)
            return refs
        result.revidmap, old_refs, new_refs = self.interrepo.dfetch_refs(
            update_refs)
        result.old_revid = old_refs.get(self.target.ref, (None, NULL_REVISION))[1]
        result.new_revid = new_refs[main_ref][1]
        (result.new_original_revno, result.new_original_revid) = stop_revinfo
        return result


branch.InterBranch.register_optimiser(InterGitRemoteLocalBranch)
branch.InterBranch.register_optimiser(InterFromGitBranch)
branch.InterBranch.register_optimiser(InterToGitBranch)
branch.InterBranch.register_optimiser(InterGitLocalRemoteBranch)
