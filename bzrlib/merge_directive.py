from StringIO import StringIO

from bzrlib import (
    branch as _mod_branch,
    diff,
    errors,
    revision as _mod_revision,
    rio,
    testament,
    )
from bzrlib.bundle import serializer as bundle_serializer


class MergeDirective(object):

    def __init__(self, revision_id, testament_sha1, time, timezone,
                 submit_location, patch=None, patch_type=None,
                 public_location=None):
        assert isinstance(time, float)
        assert patch_type in (None, 'diff', 'bundle')
        if patch_type != 'bundle' and public_location is None:
            raise errors.NoMergeSource()
        if patch_type is not None and patch is None:
            raise errors.PatchMissing(patch_type)
        self.revision_id = revision_id
        self.testament_sha1 = testament_sha1
        self.time = time
        self.timezone = timezone
        self.submit_location = submit_location
        self.patch = patch
        self.patch_type = patch_type
        self.public_location = public_location

    @staticmethod
    def from_lines(lines):
        line_iter = iter(lines)
        stanza = rio.read_patch_stanza(line_iter)
        patch_lines = list(line_iter)
        if len(patch_lines) == 0:
            patch = None
        else:
            patch = ''.join(patch_lines)
        try:
            bundle_serializer.read_bundle(StringIO(patch))
        except errors.NotABundle:
            patch_type = 'diff'
        else:
            patch_type = 'bundle'
        time, timezone = bundle_serializer.unpack_highres_date(
            stanza.get('timestamp'))
        kwargs = {}
        for key in ('revision_id', 'testament_sha1', 'submit_location',
                    'public_location'):
            try:
                kwargs[key] = stanza.get(key)
            except KeyError:
                pass
        return MergeDirective(time=time, timezone=timezone,
                              patch_type=patch_type, patch=patch, **kwargs)

    def to_lines(self):
        timestamp = bundle_serializer.format_highres_date(self.time,
                                                          self.timezone)
        stanza = rio.Stanza(revision_id=self.revision_id, timestamp=timestamp,
                            submit_location=self.submit_location,
                            testament_sha1=self.testament_sha1)
        for key in ('public_location',):
            if self.__dict__[key] is not None:
                stanza.add(key, self.__dict__[key])
        lines = rio.to_patch_lines(stanza)
        lines.append('# \n')
        if self.patch is not None:
            lines.extend(self.patch.splitlines(True))
        return lines

    @classmethod
    def from_objects(klass, repository, revision_id, time, timezone,
                 submit_location, patch_type='bundle',
                 local_submit_location=None, public_branch=None):
        if public_branch is not None:
            public_location = public_branch.base
            if not public_branch.repository.has_revision(revision_id):
                raise errors.PublicBranchOutOfDate(public_location,
                                                   revision_id)
            else:
                public_location = None
        t = testament.StrictTestament3.from_revision(repository, revision_id)
        if patch_type is None:
            patch = None
        else:
            submit_branch = _mod_branch.Branch.open(submit_location)
            submit_revision_id = submit_branch.last_revision()
            repository.fetch(submit_branch.repository, submit_revision_id)
            ancestor_id = _mod_revision.common_ancestor(revision_id,
                                                        submit_revision_id,
                                                        repository)
            if patch_type == 'bundle':
                s = StringIO()
                bundle_serializer.write_bundle(repository, revision_id,
                                               ancestor_id, s)
                patch = s.getvalue()
            elif patch_type == 'diff':
                patch = klass._generate_diff(repository, revision_id,
                                             ancestor_id)
        return MergeDirective(revision_id, t.as_sha1(), time, timezone,
                              submit_location, patch, patch_type,
                              public_branch)

    @staticmethod
    def _generate_diff(repository, revision_id, ancestor_id):
        tree_1 = repository.revision_tree(ancestor_id)
        tree_2 = repository.revision_tree(revision_id)
        s = StringIO()
        diff.show_diff_trees(tree_1, tree_2, s)
        return s.getvalue()
