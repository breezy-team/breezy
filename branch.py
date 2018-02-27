# Copyright (C) 2007,2012 Canonical Ltd
# Copyright (C) 2009-2012 Jelmer Vernooij <jelmer@samba.org>
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

from __future__ import absolute_import

from cStringIO import StringIO
from collections import defaultdict

from dulwich.objects import (
    NotCommitError,
    ZERO_SHA,
    )
from dulwich.repo import check_ref_format

from ... import (
    branch,
    config,
    controldir,
    errors,
    lock,
    repository as _mod_repository,
    revision,
    tag,
    transport,
    urlutils,
    )
from ...revision import (
    NULL_REVISION,
    )
from ...trace import (
    is_quiet,
    mutter,
    warning,
    )

from .config import (
    GitBranchConfig,
    GitBranchStack,
    )
from .errors import (
    NoPushSupport,
    NoSuchRef,
    )
from .refs import (
    is_tag,
    ref_to_branch_name,
    ref_to_tag_name,
    tag_name_to_ref,
    )
from .unpeel_map import (
    UnpeelMap,
    )

from ...foreign import ForeignBranch


class GitPullResult(branch.PullResult):
    """Result of a pull from a Git branch."""

    def _lookup_revno(self, revid):
        assert isinstance(revid, str), "was %r" % revid
        # Try in source branch first, it'll be faster
        with self.target_branch.lock_read():
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

    def get_refs_container(self):
        raise NotImplementedError(self.get_refs_container)

    def _iter_tag_refs(self, refs):
        """Iterate over the tag refs.

        :param refs: Refs dictionary (name -> git sha1)
        :return: iterator over (name, peeled_sha1, unpeeled_sha1, bzr_revid)
        """
        for k, unpeeled in refs.as_dict().iteritems():
            try:
                tag_name = ref_to_tag_name(k)
            except (ValueError, UnicodeDecodeError):
                continue
            peeled = refs.get_peeled(k)
            if peeled is None:
                try:
                    peeled = self.repository.controldir._git.object_store.peel_sha(unpeeled).id
                except KeyError:
                    # Let's just hope it's a commit
                    peeled = unpeeled
            assert type(tag_name) is unicode
            try:
                foreign_peeled = self.branch.lookup_foreign_revision_id(peeled)
            except NotCommitError:
                continue
            yield (tag_name, peeled, unpeeled, foreign_peeled)

    def _merge_to_remote_git(self, target_repo, new_refs, overwrite=False):
        updates = {}
        conflicts = []
        def get_changed_refs(old_refs):
            ret = dict(old_refs)
            for k, v in new_refs.iteritems():
                if not is_tag(k):
                    continue
                name = ref_to_tag_name(k)
                if old_refs.get(k) == v:
                    pass
                elif overwrite or not k in old_refs:
                    ret[k] = v
                    updates[name] = target_repo.lookup_foreign_revision_id(v)
                else:
                    conflicts.append((name, v, old_refs[k]))
            return ret
        target_repo.controldir.send_pack(get_changed_refs, lambda have, want: [])
        return updates, conflicts

    def _merge_to_local_git(self, target_repo, refs, overwrite=False):
        conflicts = []
        updates = {}
        for k, unpeeled in refs.as_dict().iteritems():
            if not is_tag(k):
                continue
            name = ref_to_tag_name(k)
            peeled = self.repository.controldir.get_peeled(k)
            if target_repo._git.refs.get(k) == unpeeled:
                pass
            elif overwrite or not k in target_repo._git.refs:
                target_repo._git.refs[k] = unpeeled or peeled
                updates[name] = self.repository.lookup_foreign_revision_id(peeled)
            else:
                conflicts.append((name, self.repository.lookup_foreign_revision_id(peeled), target_repo.lookup_foreign_revision_id(target_repo._git.refs[k])))
        return updates, conflicts

    def _merge_to_git(self, to_tags, refs, overwrite=False):
        target_repo = to_tags.repository
        if self.repository.has_same_location(target_repo):
            return {}, []
        if getattr(target_repo, "_git", None):
            return self._merge_to_local_git(target_repo, refs, overwrite)
        else:
            return self._merge_to_remote_git(target_repo, refs, overwrite)

    def _merge_to_non_git(self, to_tags, refs, overwrite=False):
        unpeeled_map = defaultdict(set)
        conflicts = []
        updates = {}
        result = dict(to_tags.get_tag_dict())
        for n, peeled, unpeeled, bzr_revid in self._iter_tag_refs(refs):
            if unpeeled is not None:
                unpeeled_map[peeled].add(unpeeled)
            if result.get(n) == bzr_revid:
                pass
            elif n not in result or overwrite:
                result[n] = bzr_revid
                updates[n] = bzr_revid
            else:
                conflicts.append((n, bzr_revid, result[n]))
        to_tags._set_tag_dict(result)
        if len(unpeeled_map) > 0:
            map_file = UnpeelMap.from_repository(to_tags.branch.repository)
            map_file.update(unpeeled_map)
            map_file.save_in_repository(to_tags.branch.repository)
        return updates, conflicts

    def merge_to(self, to_tags, overwrite=False, ignore_master=False,
                 source_refs=None):
        """See Tags.merge_to."""
        if source_refs is None:
            source_refs = self.get_refs_container()
        if self == to_tags:
            return {}, []
        if isinstance(to_tags, GitTags):
            return self._merge_to_git(to_tags, source_refs,
                                      overwrite=overwrite)
        else:
            if ignore_master:
                master = None
            else:
                master = to_tags.branch.get_master_branch()
            updates, conflicts = self._merge_to_non_git(to_tags, source_refs,
                                              overwrite=overwrite)
            if master is not None:
                extra_updates, extra_conflicts = self.merge_to(
                    master.tags, overwrite=overwrite,
                                           source_refs=source_refs,
                                           ignore_master=ignore_master)
                updates.update(extra_updates)
                conflicts += extra_conflicts
            return updates, conflicts

    def get_tag_dict(self):
        ret = {}
        refs = self.get_refs_container()
        for (name, peeled, unpeeled, bzr_revid) in self._iter_tag_refs(refs):
            ret[name] = bzr_revid
        return ret


class LocalGitTagDict(GitTags):
    """Dictionary with tags in a local repository."""

    def __init__(self, branch):
        super(LocalGitTagDict, self).__init__(branch)
        self.refs = self.repository.controldir._git.refs

    def get_refs_container(self):
        return self.refs

    def _set_tag_dict(self, to_dict):
        extra = set(self.refs.allkeys())
        for k, revid in to_dict.iteritems():
            name = tag_name_to_ref(k)
            if name in extra:
                extra.remove(name)
            self.set_tag(k, revid)
        for name in extra:
            if is_tag(name):
                del self.repository._git[name]

    def set_tag(self, name, revid):
        try:
            git_sha, mapping = self.branch.lookup_bzr_revision_id(revid)
        except errors.NoSuchRevision:
            raise errors.GhostTagsNotSupported(self)
        self.refs[tag_name_to_ref(name)] = git_sha


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

    def supports_leaving_lock(self):
        return False

    def supports_tags_referencing_ghosts(self):
        return False

    def tags_are_versioned(self):
        return False

    @property
    def _matchingcontroldir(self):
        from .dir import LocalGitControlDirFormat
        return LocalGitControlDirFormat()

    def get_foreign_tests_branch_factory(self):
        from .tests.test_branch import ForeignTestsBranchFactory
        return ForeignTestsBranchFactory()

    def make_tags(self, branch):
        try:
            return branch.tags
        except AttributeError:
            pass
        if getattr(branch.repository, "_git", None) is None:
            from .remote import RemoteGitTagDict
            return RemoteGitTagDict(branch)
        else:
            return LocalGitTagDict(branch)

    def initialize(self, a_controldir, name=None, repository=None,
                   append_revisions_only=None):
        from .dir import LocalGitDir
        if not isinstance(a_controldir, LocalGitDir):
            raise errors.IncompatibleFormat(self, a_controldir._format)
        return a_controldir.create_branch(repository=repository, name=name,
            append_revisions_only=append_revisions_only)

    def get_reference(self, controldir, name=None):
        return controldir.get_branch_reference(name)

    def set_reference(self, controldir, name, target):
        return controldir.set_branch_reference(target, name)


class GitBranch(ForeignBranch):
    """An adapter to git repositories for bzr Branch objects."""

    @property
    def control_transport(self):
        return self.controldir.control_transport

    def __init__(self, controldir, repository, ref):
        self.repository = repository
        self._format = GitBranchFormat()
        self.controldir = controldir
        self._lock_mode = None
        self._lock_count = 0
        super(GitBranch, self).__init__(repository.get_mapping())
        self.ref = ref
        self._head = None
        try:
            self.name = ref_to_branch_name(ref)
        except ValueError:
            self.name = None
            if self.ref is not None:
                self.user_transport.set_segment_parameter(
                    "ref", urlutils.escape(self.ref))
        else:
            if self.name != "":
                self.user_transport.set_segment_parameter(
                    "branch", urlutils.escape(self.name))
        self.base = self.user_transport.base

    def _get_checkout_format(self, lightweight=False):
        """Return the most suitable metadir for a checkout of this branch.
        Weaves are used if this branch's repository uses weaves.
        """
        return controldir.format_registry.make_controldir("default")

    def get_child_submit_format(self):
        """Return the preferred format of submissions to this branch."""
        ret = self.get_config_stack().get("child_submit_format")
        if ret is not None:
            return ret
        return "git"

    def get_config(self):
        return GitBranchConfig(self)

    def get_config_stack(self):
        return GitBranchStack(self)

    def _get_nick(self, local=False, possible_master_transports=None):
        """Find the nick name for this branch.

        :return: Branch nick
        """
        cs = self.repository._git.get_config_stack()
        try:
            return cs.get((b"branch", self.name.encode('utf-8')), b"nick").decode("utf-8")
        except KeyError:
            pass
        return self.name or u"HEAD"

    def _set_nick(self, nick):
        cf = self.repository._git.get_config()
        cf.set((b"branch", self.name.encode('utf-8')), b"nick", nick.encode("utf-8"))
        f = StringIO()
        cf.write_to_file(f)
        self.repository._git._put_named_file('config', f.getvalue())

    nick = property(_get_nick, _set_nick)

    def __repr__(self):
        return "<%s(%r, %r)>" % (self.__class__.__name__, self.repository.base,
            self.name)

    def generate_revision_history(self, revid, old_revid=None):
        if revid == NULL_REVISION:
            newhead = ZERO_SHA
        else:
            # FIXME: Check that old_revid is in the ancestry of revid
            newhead, self.mapping = self.repository.lookup_bzr_revision_id(revid)
            if self.mapping is None:
                raise AssertionError
        self._set_head(newhead)

    def lock_write(self, token=None):
        if token is not None:
            raise errors.TokenLockingNotSupported(self)
        if self._lock_mode:
            if self._lock_mode == 'r':
                raise errors.ReadOnlyError(self)
            self._lock_count += 1
        else:
            self._lock_mode = 'w'
            self._lock_count = 1
        self.repository.lock_write()
        return lock.LogicalLockResult(self.unlock)

    def leave_lock_in_place(self):
        raise NotImplementedError(self.leave_lock_in_place)

    def dont_leave_lock_in_place(self):
        raise NotImplementedError(self.dont_leave_lock_in_place)

    def get_stacked_on_url(self):
        # Git doesn't do stacking (yet...)
        raise branch.UnstackableBranchFormat(self._format, self.base)

    def _get_parent_location(self):
        """See Branch.get_parent()."""
        # FIXME: Set "origin" url from .git/config ?
        cs = self.repository._git.get_config_stack()
        try:
            return cs.get((b"remote", b'origin'), b"url").decode("utf-8")
        except KeyError:
            return None

    def set_parent(self, location):
        # FIXME: Set "origin" url in .git/config ?
        cs = self.repository._git.get_config()
        location = urlutils.relative_url(self.base, location)
        cs.set((b"remote", b"origin"), b"url", location)
        f = StringIO()
        cs.write_to_file(f)
        self.repository._git._put_named_file('config', f.getvalue())

    def break_lock(self):
        raise NotImplementedError(self.break_lock)

    def lock_read(self):
        if self._lock_mode:
            assert self._lock_mode in ('r', 'w')
            self._lock_count += 1
        else:
            self._lock_mode = 'r'
            self._lock_count = 1
        self.repository.lock_read()
        return lock.LogicalLockResult(self.unlock)

    def peek_lock_mode(self):
        return self._lock_mode

    def is_locked(self):
        return (self._lock_mode is not None)

    def unlock(self):
        """See Branch.unlock()."""
        self._lock_count -= 1
        if self._lock_count == 0:
            self._lock_mode = None
            self._clear_cached_state()
        self.repository.unlock()

    def get_physical_lock_status(self):
        return False

    def last_revision(self):
        with self.lock_read():
            # perhaps should escape this ?
            if self.head is None:
                return revision.NULL_REVISION
            return self.lookup_foreign_revision_id(self.head)

    def _basic_push(self, target, overwrite=False, stop_revision=None):
        return branch.InterBranch.get(self, target)._basic_push(
            overwrite, stop_revision)

    def lookup_foreign_revision_id(self, foreign_revid):
        try:
            return self.repository.lookup_foreign_revision_id(foreign_revid,
                self.mapping)
        except KeyError:
            # Let's try..
            return self.mapping.revision_id_foreign_to_bzr(foreign_revid)

    def lookup_bzr_revision_id(self, revid):
        return self.repository.lookup_bzr_revision_id(
            revid, mapping=self.mapping)

    def get_unshelver(self, tree):
        raise errors.StoringUncommittedNotSupported(self)


class LocalGitBranch(GitBranch):
    """A local Git branch."""

    def __init__(self, controldir, repository, ref):
        super(LocalGitBranch, self).__init__(controldir, repository, ref)
        refs = controldir.get_refs_container()
        if not (ref in refs or "HEAD" in refs):
            raise errors.NotBranchError(self.base)

    def create_checkout(self, to_location, revision_id=None, lightweight=False,
        accelerator_tree=None, hardlink=False):
        t = transport.get_transport(to_location)
        t.ensure_base()
        format = self._get_checkout_format(lightweight=lightweight)
        checkout = format.initialize_on_transport(t)
        if lightweight:
            from_branch = checkout.set_branch_reference(target_branch=self)
        else:
            policy = checkout.determine_repository_policy()
            repo = policy.acquire_repository()[0]

            checkout_branch = checkout.create_branch()
            checkout_branch.bind(self)
            checkout_branch.pull(self, stop_revision=revision_id)
            from_branch = None
        return checkout.create_workingtree(revision_id,
                from_branch=from_branch, hardlink=hardlink)

    def fetch(self, from_branch, last_revision=None, limit=None):
        return branch.InterBranch.get(from_branch, self).fetch(
            stop_revision=last_revision, limit=limit)

    def _gen_revision_history(self):
        if self.head is None:
            return []
        graph = self.repository.get_graph()
        ret = list(graph.iter_lefthand_ancestry(self.last_revision(),
            (revision.NULL_REVISION, )))
        ret.reverse()
        return ret

    def _get_head(self):
        try:
            return self.repository._git.refs[self.ref or "HEAD"]
        except KeyError:
            return None

    def _read_last_revision_info(self):
        last_revid = self.last_revision()
        graph = self.repository.get_graph()
        revno = graph.find_distance_to_null(last_revid,
            [(revision.NULL_REVISION, 0)])
        return revno, last_revid

    def set_last_revision_info(self, revno, revision_id):
        self.set_last_revision(revision_id)
        self._last_revision_info_cache = revno, revision_id

    def set_last_revision(self, revid):
        if not revid or not isinstance(revid, basestring):
            raise errors.InvalidRevisionId(revision_id=revid, branch=self)
        if revid == NULL_REVISION:
            newhead = ZERO_SHA
        else:
            (newhead, self.mapping) = self.repository.lookup_bzr_revision_id(revid)
            if self.mapping is None:
                raise AssertionError
        self._set_head(newhead)

    def _set_head(self, value):
        self._head = value
        self.repository._git.refs[self.ref or "HEAD"] = self._head
        self._clear_cached_state()

    head = property(_get_head, _set_head)

    def get_push_location(self):
        """See Branch.get_push_location."""
        push_loc = self.get_config_stack().get('push_location')
        return push_loc

    def set_push_location(self, location):
        """See Branch.set_push_location."""
        self.get_config().set_user_option('push_location', location,
                                          store=config.STORE_LOCATION)

    def supports_tags(self):
        return True

    def store_uncommitted(self, creator):
        raise errors.StoringUncommittedNotSupported(self)


def _quick_lookup_revno(local_branch, remote_branch, revid):
    assert isinstance(revid, str), "was %r" % revid
    # Try in source branch first, it'll be faster
    with local_branch.lock_read():
        try:
            return local_branch.revision_id_to_revno(revid)
        except errors.NoSuchRevision:
            graph = local_branch.repository.get_graph()
            try:
                return graph.find_distance_to_null(revid,
                    [(revision.NULL_REVISION, 0)])
            except errors.GhostRevisionsHaveNoRevno:
                # FIXME: Check using graph.find_distance_to_null() ?
                with remote_branch.lock_read():
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
        return _quick_lookup_revno(self.target_branch, self.source_branch,
            revid)

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
        return _quick_lookup_revno(self.source_branch, self.target_branch,
            revid)

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
        try:
            default_format = branch.format_registry.get_default()
        except AttributeError:
            default_format = branch.BranchFormat._default_format
        return [
            (GitBranchFormat(), GitBranchFormat()),
            (GitBranchFormat(), default_format)]

    @classmethod
    def _get_interrepo(self, source, target):
        return _mod_repository.InterRepository.get(source.repository, target.repository)

    @classmethod
    def is_compatible(cls, source, target):
        if not isinstance(source, GitBranch):
            return False
        if isinstance(target, GitBranch):
            # InterLocalGitRemoteGitBranch or InterToGitBranch should be used
            return False
        if getattr(cls._get_interrepo(source, target), "fetch_objects", None) is None:
            # fetch_objects is necessary for this to work
            return False
        return True

    def fetch(self, stop_revision=None, fetch_tags=None, limit=None):
        self.fetch_objects(stop_revision, fetch_tags=fetch_tags, limit=limit)

    def fetch_objects(self, stop_revision, fetch_tags, limit=None):
        interrepo = self._get_interrepo(self.source, self.target)
        if fetch_tags is None:
            c = self.source.get_config_stack()
            fetch_tags = c.get('branch.fetch_tags')
        def determine_wants(heads):
            if self.source.ref is not None and not self.source.ref in heads:
                raise NoSuchRef(self.source.ref, self.source.user_url, heads.keys())

            if stop_revision is None:
                if self.source.ref is not None:
                    head = heads[self.source.ref]
                else:
                    head = heads["HEAD"]
                self._last_revid = self.source.lookup_foreign_revision_id(head)
            else:
                self._last_revid = stop_revision
            real = interrepo.get_determine_wants_revids(
                [self._last_revid], include_tags=fetch_tags)
            return real(heads)
        pack_hint, head, refs = interrepo.fetch_objects(
            determine_wants, self.source.mapping, limit=limit)
        if (pack_hint is not None and
            self.target.repository._format.pack_compresses):
            self.target.repository.pack(hint=pack_hint)
        return head, refs

    def _update_revisions(self, stop_revision=None, overwrite=False):
        head, refs = self.fetch_objects(stop_revision, fetch_tags=None)
        if overwrite:
            prev_last_revid = None
        else:
            prev_last_revid = self.target.last_revision()
        self.target.generate_revision_history(self._last_revid,
            prev_last_revid, self.source)
        return head, refs

    def _basic_pull(self, stop_revision, overwrite, run_hooks,
              _override_hook_target, _hook_master):
        result = GitBranchPullResult()
        result.source_branch = self.source
        if _override_hook_target is None:
            result.target_branch = self.target
        else:
            result.target_branch = _override_hook_target
        with self.target.lock_write(), self.source.lock_read():
            # We assume that during 'pull' the target repository is closer than
            # the source one.
            (result.old_revno, result.old_revid) = \
                self.target.last_revision_info()
            result.new_git_head, remote_refs = self._update_revisions(
                stop_revision, overwrite=overwrite)
            tags_ret  = self.source.tags.merge_to(
                    self.target.tags, overwrite, ignore_master=True)
            if isinstance(tags_ret, tuple):
                result.tag_updates, result.tag_conflicts = tags_ret
            else:
                result.tag_conflicts = tags_ret
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
            return result

    def pull(self, overwrite=False, stop_revision=None,
             possible_transports=None, _hook_master=None, run_hooks=True,
             _override_hook_target=None, local=False):
        """See Branch.pull.

        :param _hook_master: Private parameter - set the branch to
            be supplied as the master to pull hooks.
        :param run_hooks: Private parameter - if false, this branch
            is being called because it's the master of the primary branch,
            so it should not run its hooks.
        :param _override_hook_target: Private parameter - set the branch to be
            supplied as the target_branch to pull hooks.
        """
        # This type of branch can't be bound.
        bound_location = self.target.get_bound_location()
        if local and not bound_location:
            raise errors.LocalRequiresBoundBranch()
        master_branch = None
        source_is_master = False
        self.source.lock_read()
        if bound_location:
            # bound_location comes from a config file, some care has to be
            # taken to relate it to source.user_url
            normalized = urlutils.normalize_url(bound_location)
            try:
                relpath = self.source.user_transport.relpath(normalized)
                source_is_master = (relpath == '')
            except (errors.PathNotChild, urlutils.InvalidURL):
                source_is_master = False
        if not local and bound_location and not source_is_master:
            # not pulling from master, so we need to update master.
            master_branch = self.target.get_master_branch(possible_transports)
            master_branch.lock_write()
        try:
            try:
                if master_branch:
                    # pull from source into master.
                    master_branch.pull(self.source, overwrite, stop_revision,
                        run_hooks=False)
                result = self._basic_pull(stop_revision, overwrite, run_hooks,
                    _override_hook_target, _hook_master=master_branch)
            finally:
                self.source.unlock()
        finally:
            if master_branch:
                master_branch.unlock()
        return result

    def _basic_push(self, overwrite=False, stop_revision=None):
        result = branch.BranchPushResult()
        result.source_branch = self.source
        result.target_branch = self.target
        result.old_revno, result.old_revid = self.target.last_revision_info()
        result.new_git_head, remote_refs = self._update_revisions(
            stop_revision, overwrite=overwrite)
        tags_ret = self.source.tags.merge_to(self.target.tags,
            overwrite)
        if isinstance(tags_ret, tuple):
            (result.tag_updates, result.tag_conflicts) = tags_ret
        else:
            result.tag_conflicts = tags_ret
        result.new_revno, result.new_revid = self.target.last_revision_info()
        return result


class InterGitBranch(branch.GenericInterBranch):
    """InterBranch implementation that pulls between Git branches."""

    def fetch(self, stop_revision=None, fetch_tags=None, limit=None):
        raise NotImplementedError(self.fetch)


class InterLocalGitRemoteGitBranch(InterGitBranch):
    """InterBranch that copies from a local to a remote git branch."""

    @staticmethod
    def _get_branch_formats_to_test():
        # FIXME
        return []

    @classmethod
    def is_compatible(self, source, target):
        from .remote import RemoteGitBranch
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
            old_ref = old_refs.get(self.target.ref, ZERO_SHA)
            result.old_revid = self.target.lookup_foreign_revision_id(old_ref)
            refs = { self.target.ref: self.source.repository.lookup_bzr_revision_id(stop_revision)[0] }
            result.new_revid = stop_revision
            for name, sha in self.source.repository._git.refs.as_dict("refs/tags").iteritems():
                refs[tag_name_to_ref(name)] = sha
            return refs
        self.target.repository.send_pack(get_changed_refs,
            self.source.repository._git.object_store.generate_pack_contents)
        return result


class InterGitLocalGitBranch(InterGitBranch):
    """InterBranch that copies from a remote to a local git branch."""

    @staticmethod
    def _get_branch_formats_to_test():
        # FIXME
        return []

    @classmethod
    def is_compatible(self, source, target):
        return (isinstance(source, GitBranch) and
                isinstance(target, LocalGitBranch))

    def fetch(self, stop_revision=None, fetch_tags=None, limit=None):
        interrepo = _mod_repository.InterRepository.get(self.source.repository,
            self.target.repository)
        if stop_revision is None:
            stop_revision = self.source.last_revision()
        determine_wants = interrepo.get_determine_wants_revids(
            [stop_revision], include_tags=fetch_tags)
        interrepo.fetch_objects(determine_wants, limit=limit)

    def _basic_push(self, overwrite=False, stop_revision=None):
        result = GitBranchPushResult()
        result.source_branch = self.source
        result.target_branch = self.target
        result.old_revid = self.target.last_revision()
        refs, stop_revision = self.update_refs(stop_revision)
        self.target.generate_revision_history(stop_revision, result.old_revid)
        tags_ret = self.source.tags.merge_to(self.target.tags,
            source_refs=refs, overwrite=overwrite)
        if isinstance(tags_ret, tuple):
            (result.tag_updates, result.tag_conflicts) = tags_ret
        else:
            result.tag_conflicts = tags_ret
        result.new_revid = self.target.last_revision()
        return result

    def update_refs(self, stop_revision=None):
        interrepo = _mod_repository.InterRepository.get(self.source.repository,
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
        with self.target.lock_write(), self.source.lock_read():
            result.old_revid = self.target.last_revision()
            refs, stop_revision = self.update_refs(stop_revision)
            self.target.generate_revision_history(stop_revision, result.old_revid)
            tags_ret = self.source.tags.merge_to(self.target.tags,
                overwrite=overwrite, source_refs=refs)
            if isinstance(tags_ret, tuple):
                (result.tag_updates, result.tag_conflicts) = tags_ret
            else:
                result.tag_conflicts = tags_ret
            result.new_revid = self.target.last_revision()
            result.local_branch = None
            result.master_branch = result.target_branch
            if run_hooks:
                for hook in branch.Branch.hooks['post_pull']:
                    hook(result)
        return result


class InterToGitBranch(branch.GenericInterBranch):
    """InterBranch implementation that pulls into a Git branch."""

    def __init__(self, source, target):
        super(InterToGitBranch, self).__init__(source, target)
        self.interrepo = _mod_repository.InterRepository.get(source.repository,
                                           target.repository)

    @staticmethod
    def _get_branch_formats_to_test():
        try:
            default_format = branch.format_registry.get_default()
        except AttributeError:
            default_format = branch.BranchFormat._default_format
        return [(default_format, GitBranchFormat())]

    @classmethod
    def is_compatible(self, source, target):
        return (not isinstance(source, GitBranch) and
                isinstance(target, GitBranch))

    def _get_new_refs(self, stop_revision=None, fetch_tags=None):
        assert self.source.is_locked()
        if stop_revision is None:
            (stop_revno, stop_revision) = self.source.last_revision_info()
        else:
            stop_revno = self.source.revision_id_to_revno(stop_revision)
        assert type(stop_revision) is str
        main_ref = self.target.ref or "refs/heads/master"
        refs = { main_ref: (None, stop_revision) }
        if fetch_tags is None:
            c = self.source.get_config_stack()
            fetch_tags = c.get('branch.fetch_tags')
        for name, revid in self.source.tags.get_tag_dict().iteritems():
            if self.source.repository.has_revision(revid):
                ref = tag_name_to_ref(name)
                if not check_ref_format(ref):
                    warning("skipping tag with invalid characters %s (%s)",
                        name, ref)
                    continue
                if fetch_tags:
                    # FIXME: Skip tags that are not in the ancestry
                    refs[ref] = (None, revid)
        return refs, main_ref, (stop_revno, stop_revision)

    def _update_refs(self, result, old_refs, new_refs, overwrite):
        mutter("updating refs. old refs: %r, new refs: %r",
               old_refs, new_refs)
        result.tag_updates = {}
        result.tag_conflicts = []
        ret = dict(old_refs)
        def ref_equals(refs, ref, git_sha, revid):
            try:
                value = refs[ref]
            except KeyError:
                return False
            if (value[0] is not None and
                git_sha is not None and
                value[0] == git_sha):
                return True
            if (value[1] is not None and
                revid is not None and
                value[1] == revid):
                return True
            # FIXME: If one side only has the git sha available and the other only
            # has the bzr revid, then this will cause us to show a tag as updated
            # that hasn't actually been updated.
            return False
        # FIXME: Check for diverged branches
        for ref, (git_sha, revid) in new_refs.iteritems():
            if ref_equals(ret, ref, git_sha, revid):
                # Already up to date
                if git_sha is None:
                    git_sha = old_refs[ref][0]
                if revid is None:
                    revid = old_refs[ref][1]
                ret[ref] = new_refs[ref] = (git_sha, revid)
            elif ref not in ret or overwrite:
                try:
                    tag_name = ref_to_tag_name(ref)
                except ValueError:
                    pass
                else:
                    result.tag_updates[tag_name] = revid
                ret[ref] = (git_sha, revid)
            else:
                # FIXME: Check diverged
                diverged = False
                if diverged:
                    try:
                        name = ref_to_tag_name(ref)
                    except ValueError:
                        pass
                    else:
                        result.tag_conflicts.append((name, revid, ret[name][1]))
                else:
                    ret[ref] = (git_sha, revid)
        return ret

    def fetch(self, stop_revision=None, fetch_tags=None, lossy=False, limit=None):
        if stop_revision is None:
            stop_revision = self.source.last_revision()
        ret = []
        if fetch_tags:
            for k, v in self.source.tags.get_tag_dict().iteritems():
                ret.append((None, v))
        ret.append((None, stop_revision))
        self.interrepo.fetch_objects(ret, lossy=lossy, limit=limit)

    def pull(self, overwrite=False, stop_revision=None, local=False,
             possible_transports=None, run_hooks=True):
        result = GitBranchPullResult()
        result.source_branch = self.source
        result.target_branch = self.target
        with self.source.lock_read(), self.target.lock_write():
            new_refs, main_ref, stop_revinfo = self._get_new_refs(
                stop_revision)
            def update_refs(old_refs):
                return self._update_refs(result, old_refs, new_refs, overwrite)
            try:
                result.revidmap, old_refs, new_refs = self.interrepo.fetch_refs(
                    update_refs, lossy=False)
            except NoPushSupport:
                raise errors.NoRoundtrippingSupport(self.source, self.target)
            (old_sha1, result.old_revid) = old_refs.get(main_ref, (ZERO_SHA, NULL_REVISION))
            if result.old_revid is None:
                result.old_revid = self.target.lookup_foreign_revision_id(old_sha1)
            result.new_revid = new_refs[main_ref][1]
            result.local_branch = None
            result.master_branch = self.target
            if run_hooks:
                for hook in branch.Branch.hooks['post_pull']:
                    hook(result)
        return result

    def push(self, overwrite=False, stop_revision=None, lossy=False,
             _override_hook_source_branch=None):
        result = GitBranchPushResult()
        result.source_branch = self.source
        result.target_branch = self.target
        result.local_branch = None
        result.master_branch = result.target_branch
        with self.source.lock_read():
            new_refs, main_ref, stop_revinfo = self._get_new_refs(stop_revision)
            def update_refs(old_refs):
                return self._update_refs(result, old_refs, new_refs, overwrite)
            try:
                result.revidmap, old_refs, new_refs = self.interrepo.fetch_refs(
                    update_refs, lossy=lossy)
            except NoPushSupport:
                raise errors.NoRoundtrippingSupport(self.source, self.target)
            (old_sha1, result.old_revid) = old_refs.get(main_ref, (ZERO_SHA, NULL_REVISION))
            if result.old_revid is None:
                result.old_revid = self.target.lookup_foreign_revision_id(old_sha1)
            result.new_revid = new_refs[main_ref][1]
            (result.new_original_revno, result.new_original_revid) = stop_revinfo
            for hook in branch.Branch.hooks['post_push']:
                hook(result)
        return result


branch.InterBranch.register_optimiser(InterGitLocalGitBranch)
branch.InterBranch.register_optimiser(InterFromGitBranch)
branch.InterBranch.register_optimiser(InterToGitBranch)
branch.InterBranch.register_optimiser(InterLocalGitRemoteGitBranch)
