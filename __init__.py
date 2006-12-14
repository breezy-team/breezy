# Copyright (C) 2006 Canonical Ltd
# Authors: Robert Collins <robert.collins@canonical.com>
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


"""A GIT branch and repository format implementation for bzr."""


from StringIO import StringIO

import stgit
import stgit.git as git

from bzrlib import config, iterablefile, graph, osutils, urlutils
from bzrlib.decorators import *
import bzrlib.branch
import bzrlib.bzrdir
import bzrlib.errors as errors
import bzrlib.repository
from bzrlib.revision import Revision


class GitBranchConfig(config.BranchConfig):
    """BranchConfig that uses locations.conf in place of branch.conf""" 

    def __init__(self, branch):
        config.BranchConfig.__init__(self, branch)
        # do not provide a BranchDataConfig
        self.option_sources = self.option_sources[0], self.option_sources[2]

    def set_user_option(self, name, value, local=False):
        """Force local to True"""
        config.BranchConfig.set_user_option(self, name, value, local=True)


def gitrevid_from_bzr(revision_id):
    if revision_id is None:
        return None
    return revision_id[4:]


def bzrrevid_from_git(revision_id):
    return "git:" + revision_id


class GitLock(object):
    """A lock that thunks through to Git."""

    def lock_write(self):
        pass

    def lock_read(self):
        pass

    def unlock(self):
        pass


class GitLockableFiles(bzrlib.lockable_files.LockableFiles):
    """Git specific lockable files abstraction."""

    def __init__(self, lock):
        self._lock = lock
        self._transaction = None
        self._lock_mode = None
        self._lock_count = 0


class GitDir(bzrlib.bzrdir.BzrDir):
    """An adapter to the '.git' dir used by git."""

    def __init__(self, transport, lockfiles, format):
        self._format = format
        self.root_transport = transport
        self.transport = transport.clone('.git')
        self._lockfiles = lockfiles

    def get_branch_transport(self, branch_format):
        if branch_format is None:
            return self.transport
        if isinstance(branch_format, GitBzrDirFormat):
            return self.transport
        raise errors.IncompatibleFormat(branch_format, self._format)

    get_repository_transport = get_branch_transport
    get_workingtree_transport = get_branch_transport

    def is_supported(self):
        return True

    def open_branch(self, ignored=None):
        """'crate' a branch for this dir."""
        return GitBranch(self, self._lockfiles)

    def open_repository(self, shared=False):
        """'open' a repository for this dir."""
        return GitRepository(self._gitrepo, self, self._lockfiles)

    def open_workingtree(self):
        loc = urlutils.unescape_for_display(self.root_transport.base, 'ascii')
        raise errors.NoWorkingTree(loc)


class GitBzrDirFormat(bzrlib.bzrdir.BzrDirFormat):
    """The .git directory control format."""

    @classmethod
    def _known_formats(self):
        return set([GitBzrDirFormat()])

    def open(self, transport, _create=False, _found=None):
        """Open this directory.
        
        :param _create: create the git dir on the fly. private to GitDirFormat.
        """
        # we dont grok readonly - git isn't integrated with transport.
        url = transport.base
        if url.startswith('readonly+'):
            url = url[len('readonly+'):]
        if url.startswith('file://'):
            url = url[len('file://'):]
        url = url.encode('utf8')
        if not transport.has('.git'):
            raise errors.NotBranchError(path=transport.base)
        lockfiles = GitLockableFiles(GitLock())
        return GitDir(transport, lockfiles, self)

    @classmethod
    def probe_transport(klass, transport):
        """Our format is present if the transport ends in '.not/'."""
        # little ugly, but works
        format = klass() 
        # try a manual probe first, its a little faster perhaps ?
        if transport.has('.git'):
            return format
        # delegate to the main opening code. This pays a double rtt cost at the
        # moment, so perhaps we want probe_transport to return the opened thing
        # rather than an openener ? or we could return a curried thing with the
        # dir to open already instantiated ? Needs more thought.
        try:
            format.open(transport)
            return format
        except Exception, e:
            raise errors.NotBranchError(path=transport.base)
        raise errors.NotBranchError(path=transport.base)


bzrlib.bzrdir.BzrDirFormat.register_control_format(GitBzrDirFormat)


class GitBranch(bzrlib.branch.Branch):
    """An adapter to git repositories for bzr Branch objects."""

    def __init__(self, gitdir, lockfiles):
        self.bzrdir = gitdir
        self.control_files = lockfiles
        self.repository = GitRepository(gitdir, lockfiles)
        self.base = gitdir.root_transport.base
        if '.git' not in gitdir.root_transport.list_dir('.'):
            raise errors.NotBranchError(self.base)

    def lock_write(self):
        self.control_files.lock_write()

    @needs_read_lock
    def last_revision(self):
        # perhaps should escape this ?
        return bzrrevid_from_git(self.repository.git.get_head())

    @needs_read_lock
    def revision_history(self):
        node = self.last_revision()
        ancestors = self.repository.get_revision_graph(node)
        history = []
        while node is not None:
            history.append(node)
            if len(ancestors[node]) > 0:
                node = ancestors[node][0]
            else:
                node = None
        return list(reversed(history))

    def get_config(self):
        return GitBranchConfig(self)

    def lock_read(self):
        self.control_files.lock_read()

    def unlock(self):
        self.control_files.unlock()

    def get_push_location(self):
        """See Branch.get_push_location."""
        push_loc = self.get_config().get_user_option('push_location')
        return push_loc

    def set_push_location(self, location):
        """See Branch.set_push_location."""
        self.get_config().set_user_option('push_location', location, 
                                          local=True)


class GitRepository(bzrlib.repository.Repository):
    """An adapter to git repositories for bzr."""

    def __init__(self, gitdir, lockfiles):
        self.bzrdir = gitdir
        self.control_files = lockfiles
        gitdirectory = urlutils.local_path_from_url(gitdir.transport.base)
        self.git = GitModel(gitdirectory)
        self._revision_cache = {}

    def _ancestor_revisions(self, revision_ids):
        if revision_ids is not None:
            git_revisions = [gitrevid_from_bzr(r) for r in revision_ids]
        else:
            git_revisions = None
        for lines in self.git.ancestor_lines(git_revisions):
            yield self.parse_rev(lines)

    def is_shared(self):
        return True

    def get_revision_graph(self, revision_id=None):
        if revision_id is None:
            revisions = None
        else:
            revisions = [revision_id]
        return self.get_revision_graph_with_ghosts(revisions).get_ancestors()

    def get_revision_graph_with_ghosts(self, revision_ids=None):
        result = graph.Graph()
        for revision in self._ancestor_revisions(revision_ids):
            result.add_node(revision.revision_id, revision.parent_ids)
            self._revision_cache[revision.revision_id] = revision
        return result

    def get_revision(self, revision_id):
        if revision_id in self._revision_cache:
            return self._revision_cache[revision_id]
        raw = self.git.rev_list([gitrevid_from_bzr(revision_id)], max_count=1,
                                header=True)
        return self.parse_rev(raw)

    def has_revision(self, revision_id):
        try:
            self.get_revision(revision_id)
        except NoSuchRevision:
            return False
        else:
            return True

    def get_revisions(self, revisions):
        return [self.get_revision(r) for r in revisions]

    def parse_rev(self, raw):
        # first field is the rev itself.
        # then its 'field value'
        # until the EOF??
        parents = []
        log = []
        in_log = False
        committer = None
        revision_id = bzrrevid_from_git(raw[0][:-1])
        for field in raw[1:]:
            #if field.startswith('author '):
            #    committer = field[7:]
            if field.startswith('parent '):
                parents.append(bzrrevid_from_git(field.split()[1]))
            elif field.startswith('committer '):
                commit_fields = field.split()
                if committer is None:
                    committer = ' '.join(commit_fields[1:-3])
                timestamp = commit_fields[-2]
                timezone = commit_fields[-1]
            elif field.startswith('tree '):
                tree_id = field.split()[1]
            elif in_log:
                log.append(field[4:])
            elif field == '\n':
                in_log = True

        log = ''.join(log)
        result = Revision(revision_id)
        result.parent_ids = parents
        result.message = log
        result.inventory_sha1 = ""
        result.timezone = timezone and int(timezone)
        result.timestamp = float(timestamp)
        result.committer = committer 
        result.properties['git-tree-id'] = tree_id
        return result

    def revision_tree(self, revision_id):
        return GitRevisionTree(self, revision_id)

    def get_inventory(self, revision_id):
        revision = self.get_revision(revision_id)
        inventory = GitInventory(revision_id)
        tree_id = revision.properties['git-tree-id']
        type_map = {'blob': 'file', 'tree': 'directory' }
        def get_inventory(tree_id, prefix):
            for perms, type, obj_id, name in self.git.get_inventory(tree_id):
                full_path = prefix + name
                if type == 'blob':
                    text_sha1 = obj_id
                else:
                    text_sha1 = None
                executable = (perms[-3] in ('1', '3', '5', '7'))
                entry = GitEntry(full_path, type_map[type], revision_id,
                                 text_sha1, executable)
                inventory.entries[full_path] = entry
                if type == 'tree':
                    get_inventory(obj_id, full_path+'/')
        get_inventory(tree_id, '')
        return inventory


class GitRevisionTree(object):

    def __init__(self, repository, revision_id):
        self.repository = repository
        self.revision_id = revision_id
        self.inventory = repository.get_inventory(revision_id)

    def get_file(self, file_id):
        obj_id = self.inventory[file_id].text_sha1
        lines = self.repository.git.cat_file('blob', obj_id)
        return iterablefile.IterableFile(lines)

    def is_executable(self, file_id):
        return self.inventory[file_id].executable


class GitInventory(object):

    def __init__(self, revision_id):
        self.entries = {}
        self.root = GitEntry('', 'directory', revision_id)
        self.entries[''] = self.root

    def __getitem__(self, key):
        return self.entries[key]

    def iter_entries(self):
        return iter(sorted(self.entries.items()))

    def iter_entries_by_dir(self):
        return self.iter_entries()

    def __len__(self):
        return len(self.entries)


class GitEntry(object):

    def __init__(self, path, kind, revision, text_sha1=None, executable=False,
                 text_size=None):
        self.path = path
        self.file_id = path
        self.kind = kind
        self.executable = executable
        self.name = osutils.basename(path)
        if path == '':
            self.parent_id = None
        else:
            self.parent_id = osutils.dirname(path)
        self.revision = revision
        self.symlink_target = None
        self.text_sha1 = text_sha1
        self.text_size = None

    def __repr__(self):
        return "GitEntry(%r, %r, %r, %r)" % (self.path, self.kind, 
                                             self.revision, self.parent_id)


class GitModel(object):
    """API that follows GIT model closely"""

    def __init__(self, git_dir):
        self.git_dir = git_dir

    def git_command(self, command, args):
        args = ' '.join("'%s'" % arg for arg in args)
        return 'git --git-dir=%s %s %s' % (self.git_dir, command, args) 

    def git_lines(self, command, args):
        return stgit.git._output_lines(self.git_command(command, args))

    def git_line(self, command, args):
        return stgit.git._output_one_line(self.git_command(command, args))

    def cat_file(self, type, object_id, pretty=False):
        args = []
        if pretty:
            args.append('-p')
        else:
            args.append(type)
        args.append(object_id)
        return self.git_lines('cat-file', args)

    def rev_list(self, heads, max_count=None, header=False):
        args = []
        if max_count is not None:
            args.append('--max-count=%d' % max_count)
        if header is not False:
            args.append('--header')
        if heads is None:
            args.append('--all')
        else:
            args.extend(heads)
        return self.git_lines('rev-list', args)

    def rev_parse(self, git_id):
        args = ['--verify', git_id]
        return self.git_line('rev-parse', args)

    def get_head(self):
        return self.rev_parse('HEAD')

    def ancestor_lines(self, revisions):
        revision_lines = []
        for line in self.rev_list(revisions, header=True):
            if line.startswith('\x00'):
                yield revision_lines
                revision_lines = [line[1:].decode('latin-1')]
            else:
                revision_lines.append(line.decode('latin-1'))
        assert revision_lines == ['']

    def get_inventory(self, tree_id):
        for line in self.cat_file('tree', tree_id, True):
            sections = line.split(' ', 2)
            obj_id, name = sections[2].split('\t', 1)
            name = name.rstrip('\n')
            if name.startswith('"'):
                name = name[1:-1].decode('string_escape').decode('utf-8')
            yield (sections[0], sections[1], obj_id, name)
