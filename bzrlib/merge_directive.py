# Copyright (C) 2007 Canonical Ltd
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


from email import Message
from StringIO import StringIO

from bzrlib import (
    branch as _mod_branch,
    diff,
    errors,
    gpg,
    registry,
    revision as _mod_revision,
    rio,
    testament,
    timestamp,
    )
from bzrlib.bundle import (
    serializer as bundle_serializer,
    )


class _BaseMergeDirective(object):

    def __init__(self, revision_id, testament_sha1, time, timezone,
                 target_branch, patch=None, source_branch=None, message=None,
                 bundle=None):
        """Constructor.

        :param revision_id: The revision to merge
        :param testament_sha1: The sha1 of the testament of the revision to
            merge.
        :param time: The current POSIX timestamp time
        :param timezone: The timezone offset
        :param target_branch: The branch to apply the merge to
        :param patch: The text of a diff or bundle
        :param source_branch: A public location to merge the revision from
        :param message: The message to use when committing this merge
        """
        self.revision_id = revision_id
        self.testament_sha1 = testament_sha1
        self.time = time
        self.timezone = timezone
        self.target_branch = target_branch
        self.patch = patch
        self.source_branch = source_branch
        self.message = message

    def _to_lines(self):
        """Serialize as a list of lines

        :return: a list of lines
        """
        time_str = timestamp.format_patch_date(self.time, self.timezone)
        stanza = rio.Stanza(revision_id=self.revision_id, timestamp=time_str,
                            target_branch=self.target_branch,
                            testament_sha1=self.testament_sha1)
        for key in ('source_branch', 'message'):
            if self.__dict__[key] is not None:
                stanza.add(key, self.__dict__[key])
        lines = ['# ' + self._format_string + '\n']
        lines.extend(rio.to_patch_lines(stanza))
        lines.append('# \n')
        return lines

    @classmethod
    def from_objects(klass, repository, revision_id, time, timezone,
                 target_branch, patch_type='bundle',
                 local_target_branch=None, public_branch=None, message=None):
        """Generate a merge directive from various objects

        :param repository: The repository containing the revision
        :param revision_id: The revision to merge
        :param time: The POSIX timestamp of the date the request was issued.
        :param timezone: The timezone of the request
        :param target_branch: The url of the branch to merge into
        :param patch_type: 'bundle', 'diff' or None, depending on the type of
            patch desired.
        :param local_target_branch: a local copy of the target branch
        :param public_branch: location of a public branch containing the target
            revision.
        :param message: Message to use when committing the merge
        :return: The merge directive

        The public branch is always used if supplied.  If the patch_type is
        not 'bundle', the public branch must be supplied, and will be verified.

        If the message is not supplied, the message from revision_id will be
        used for the commit.
        """
        t_revision_id = revision_id
        if revision_id == _mod_revision.NULL_REVISION:
            t_revision_id = None
        t = testament.StrictTestament3.from_revision(repository, t_revision_id)
        submit_branch = _mod_branch.Branch.open(target_branch)
        if submit_branch.get_public_branch() is not None:
            target_branch = submit_branch.get_public_branch()
        if patch_type is None:
            patch = None
        else:
            submit_revision_id = submit_branch.last_revision()
            submit_revision_id = _mod_revision.ensure_null(submit_revision_id)
            repository.fetch(submit_branch.repository, submit_revision_id)
            graph = repository.get_graph()
            ancestor_id = graph.find_unique_lca(revision_id,
                                                submit_revision_id)
            type_handler = {'bundle': klass._generate_bundle,
                            'diff': klass._generate_diff,
                            None: lambda x, y, z: None }
            patch = type_handler[patch_type](repository, revision_id,
                                             ancestor_id)

            if public_branch is not None and patch_type != 'bundle':
                public_branch_obj = _mod_branch.Branch.open(public_branch)
                if not public_branch_obj.repository.has_revision(revision_id):
                    raise errors.PublicBranchOutOfDate(public_branch,
                                                       revision_id)

        return klass(revision_id, t.as_sha1(), time, timezone, target_branch,
            patch, patch_type, public_branch, message)

    @staticmethod
    def _generate_diff(repository, revision_id, ancestor_id):
        tree_1 = repository.revision_tree(ancestor_id)
        tree_2 = repository.revision_tree(revision_id)
        s = StringIO()
        diff.show_diff_trees(tree_1, tree_2, s, old_label='', new_label='')
        return s.getvalue()

    @staticmethod
    def _generate_bundle(repository, revision_id, ancestor_id):
        s = StringIO()
        bundle_serializer.write_bundle(repository, revision_id,
                                       ancestor_id, s)
        return s.getvalue()

    def to_signed(self, branch):
        """Serialize as a signed string.

        :param branch: The source branch, to get the signing strategy
        :return: a string
        """
        my_gpg = gpg.GPGStrategy(branch.get_config())
        return my_gpg.sign(''.join(self.to_lines()))

    def to_email(self, mail_to, branch, sign=False):
        """Serialize as an email message.

        :param mail_to: The address to mail the message to
        :param branch: The source branch, to get the signing strategy and
            source email address
        :param sign: If True, gpg-sign the email
        :return: an email message
        """
        mail_from = branch.get_config().username()
        message = Message.Message()
        message['To'] = mail_to
        message['From'] = mail_from
        if self.message is not None:
            message['Subject'] = self.message
        else:
            revision = branch.repository.get_revision(self.revision_id)
            message['Subject'] = revision.message
        if sign:
            body = self.to_signed(branch)
        else:
            body = ''.join(self.to_lines())
        message.set_payload(body)
        return message

    def install_revisions(self, target_repo):
        """Install revisions and return the target revision"""
        if not target_repo.has_revision(self.revision_id):
            if self.patch_type == 'bundle':
                info = bundle_serializer.read_bundle(
                    StringIO(self.get_raw_bundle()))
                # We don't use the bundle's target revision, because
                # MergeDirective.revision_id is authoritative.
                info.install_revisions(target_repo)
            else:
                source_branch = _mod_branch.Branch.open(self.source_branch)
                target_repo.fetch(source_branch.repository, self.revision_id)
        return self.revision_id


class MergeDirective(_BaseMergeDirective):

    """A request to perform a merge into a branch.

    Designed to be serialized and mailed.  It provides all the information
    needed to perform a merge automatically, by providing at minimum a revision
    bundle or the location of a branch.

    The serialization format is robust against certain common forms of
    deterioration caused by mailing.

    The format is also designed to be patch-compatible.  If the directive
    includes a diff or revision bundle, it should be possible to apply it
    directly using the standard patch program.
    """

    _format_string = 'Bazaar merge directive format 1'

    def __init__(self, revision_id, testament_sha1, time, timezone,
                 target_branch, patch=None, patch_type=None,
                 source_branch=None, message=None, bundle=None):
        """Constructor.

        :param revision_id: The revision to merge
        :param testament_sha1: The sha1 of the testament of the revision to
            merge.
        :param time: The current POSIX timestamp time
        :param timezone: The timezone offset
        :param target_branch: The branch to apply the merge to
        :param patch: The text of a diff or bundle
        :param patch_type: None, "diff" or "bundle", depending on the contents
            of patch
        :param source_branch: A public location to merge the revision from
        :param message: The message to use when committing this merge
        """
        _BaseMergeDirective.__init__(self, revision_id, testament_sha1, time,
            timezone, target_branch, patch, source_branch, message)
        assert patch_type in (None, 'diff', 'bundle'), patch_type
        if patch_type != 'bundle' and source_branch is None:
            raise errors.NoMergeSource()
        if patch_type is not None and patch is None:
            raise errors.PatchMissing(patch_type)
        self.patch_type = patch_type

    def clear_payload(self):
        self.patch = None
        self.patch_type = None

    def get_raw_bundle(self):
        return self.bundle

    def _bundle(self):
        if self.patch_type == 'bundle':
            return self.patch
        else:
            return None

    bundle = property(_bundle)

    @classmethod
    def from_lines(klass, lines):
        """Deserialize a MergeRequest from an iterable of lines

        :param lines: An iterable of lines
        :return: a MergeRequest
        """
        line_iter = iter(lines)
        for line in line_iter:
            if line.startswith('# Bazaar merge directive format '):
                break
        else:
            if len(lines) > 0:
                raise errors.NotAMergeDirective(lines[0])
            else:
                raise errors.NotAMergeDirective('')
        return _format_registry.get(line[2:].rstrip())._from_lines(line_iter)

    @classmethod
    def _from_lines(klass, line_iter):
        stanza = rio.read_patch_stanza(line_iter)
        patch_lines = list(line_iter)
        if len(patch_lines) == 0:
            patch = None
            patch_type = None
        else:
            patch = ''.join(patch_lines)
            try:
                bundle_serializer.read_bundle(StringIO(patch))
            except (errors.NotABundle, errors.BundleNotSupported,
                    errors.BadBundle):
                patch_type = 'diff'
            else:
                patch_type = 'bundle'
        time, timezone = timestamp.parse_patch_date(stanza.get('timestamp'))
        kwargs = {}
        for key in ('revision_id', 'testament_sha1', 'target_branch',
                    'source_branch', 'message'):
            try:
                kwargs[key] = stanza.get(key)
            except KeyError:
                pass
        kwargs['revision_id'] = kwargs['revision_id'].encode('utf-8')
        return MergeDirective(time=time, timezone=timezone,
                              patch_type=patch_type, patch=patch, **kwargs)

    def to_lines(self):
        lines = self._to_lines()
        if self.patch is not None:
            lines.extend(self.patch.splitlines(True))
        return lines

    @staticmethod
    def _generate_bundle(repository, revision_id, ancestor_id):
        s = StringIO()
        bundle_serializer.write_bundle(repository, revision_id,
                                       ancestor_id, s, '0.9')
        return s.getvalue()


class MergeDirective2(_BaseMergeDirective):

    _format_string = 'Bazaar merge directive format 2 (Bazaar 0.18)'

    def __init__(self, revision_id, testament_sha1, time, timezone,
                 target_branch, patch=None, source_branch=None, message=None,
                 bundle=None):
        if source_branch is None and bundle is None:
            raise errors.NoMergeSource()
        _BaseMergeDirective.__init__(self, revision_id, testament_sha1, time,
            timezone, target_branch, patch, source_branch, message)
        self.bundle = bundle

    def _patch_type(self):
        if self.bundle is not None:
            return 'bundle'
        elif self.patch is not None:
            return 'diff'
        else:
            return None

    patch_type = property(_patch_type)

    def clear_payload(self):
        self.patch = None
        self.bundle = None

    def get_raw_bundle(self):
        if self.bundle is None:
            return None
        else:
            return self.bundle.decode('base-64')

    @classmethod
    def _from_lines(klass, line_iter):
        stanza = rio.read_patch_stanza(line_iter)
        patch = None
        bundle = None
        try:
            start = line_iter.next()
        except StopIteration:
            pass
        else:
            if start.startswith('# Begin patch'):
                patch_lines = []
                for line in line_iter:
                    if line.startswith('# Begin bundle'):
                        start = line
                        break
                    patch_lines.append(line)
                else:
                    start = None
                patch = ''.join(patch_lines)
            if start is not None:
                if start.startswith('# Begin bundle'):
                    bundle = ''.join(line_iter)
                else:
                    raise errors.IllegalMergeDirectivePayload(start)
        time, timezone = timestamp.parse_patch_date(stanza.get('timestamp'))
        kwargs = {}
        for key in ('revision_id', 'testament_sha1', 'target_branch',
                    'source_branch', 'message'):
            try:
                kwargs[key] = stanza.get(key)
            except KeyError:
                pass
        kwargs['revision_id'] = kwargs['revision_id'].encode('utf-8')
        return klass(time=time, timezone=timezone, patch=patch, bundle=bundle,
                     **kwargs)

    def to_lines(self):
        lines = self._to_lines()
        if self.patch is not None:
            lines.append('# Begin patch\n')
            lines.extend(self.patch.splitlines(True))
        if self.bundle is not None:
            lines.append('# Begin bundle\n')
            lines.extend(self.bundle.splitlines(True))
        return lines

    @classmethod
    def from_objects(klass, repository, revision_id, time, timezone,
                 target_branch, patch_type='bundle',
                 local_target_branch=None, public_branch=None, message=None):
        """Generate a merge directive from various objects

        :param repository: The repository containing the revision
        :param revision_id: The revision to merge
        :param time: The POSIX timestamp of the date the request was issued.
        :param timezone: The timezone of the request
        :param target_branch: The url of the branch to merge into
        :param patch_type: 'bundle', 'diff' or None, depending on the type of
            patch desired.
        :param local_target_branch: a local copy of the target branch
        :param public_branch: location of a public branch containing the target
            revision.
        :param message: Message to use when committing the merge
        :return: The merge directive

        The public branch is always used if supplied.  If the patch_type is
        not 'bundle', the public branch must be supplied, and will be verified.

        If the message is not supplied, the message from revision_id will be
        used for the commit.
        """
        locked = []
        try:
            repository.lock_write()
            locked.append(repository)
            t_revision_id = revision_id
            if revision_id == 'null:':
                t_revision_id = None
            t = testament.StrictTestament3.from_revision(repository,
                t_revision_id)
            submit_branch = _mod_branch.Branch.open(target_branch)
            submit_branch.lock_read()
            locked.append(submit_branch)
            if submit_branch.get_public_branch() is not None:
                target_branch = submit_branch.get_public_branch()
            if patch_type is None:
                patch = None
                bundle = None
            else:
                submit_revision_id = submit_branch.last_revision()
                submit_revision_id = _mod_revision.ensure_null(
                    submit_revision_id)
                repository.fetch(submit_branch.repository, submit_revision_id)
                graph = repository.get_graph()
                ancestor_id = graph.find_unique_lca(revision_id,
                                                    submit_revision_id)
                if patch_type in ('bundle', 'diff'):
                    patch = klass._generate_diff(repository, revision_id,
                                                 ancestor_id)
                if patch_type == 'bundle':
                    bundle = klass._generate_bundle(repository, revision_id,
                        ancestor_id).encode('base-64')
                else:
                    bundle = None

                if public_branch is not None and patch_type != 'bundle':
                    public_branch_obj = _mod_branch.Branch.open(public_branch)
                    public_branch_obj.lock_read
                    locked.append(public_branch_obj)
                    if not public_branch_obj.repository.has_revision(
                        revision_id):
                        raise errors.PublicBranchOutOfDate(public_branch,
                                                           revision_id)
        finally:
            for entry in reversed(locked):
                entry.unlock()
        return klass(revision_id, t.as_sha1(), time, timezone, target_branch,
            patch, public_branch, message, bundle)

class MergeDirectiveFormatRegistry(registry.Registry):

    def register(self, directive):
        registry.Registry.register(self, directive._format_string, directive)


_format_registry = MergeDirectiveFormatRegistry()
_format_registry.register(MergeDirective)
_format_registry.register(MergeDirective2)
