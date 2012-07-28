# Copyright (C) 2008-2012 Canonical Ltd
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

"""Foreign branch utilities."""

from __future__ import absolute_import


from bzrlib.branch import (
    Branch,
    )
from bzrlib.commands import Command, Option
from bzrlib.repository import Repository
from bzrlib.revision import Revision
from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import (
    errors,
    registry,
    transform,
    )
from bzrlib.i18n import gettext
""")

class VcsMapping(object):
    """Describes the mapping between the semantics of Bazaar and a foreign VCS.

    """
    # Whether this is an experimental mapping that is still open to changes.
    experimental = False

    # Whether this mapping supports exporting and importing all bzr semantics.
    roundtripping = False

    # Prefix used when importing revisions native to the foreign VCS (as
    # opposed to roundtripping bzr-native revisions) using this mapping.
    revid_prefix = None

    def __init__(self, vcs):
        """Create a new VcsMapping.

        :param vcs: VCS that this mapping maps to Bazaar
        """
        self.vcs = vcs

    def revision_id_bzr_to_foreign(self, bzr_revid):
        """Parse a bzr revision id and convert it to a foreign revid.

        :param bzr_revid: The bzr revision id (a string).
        :return: A foreign revision id, can be any sort of object.
        """
        raise NotImplementedError(self.revision_id_bzr_to_foreign)

    def revision_id_foreign_to_bzr(self, foreign_revid):
        """Parse a foreign revision id and convert it to a bzr revid.

        :param foreign_revid: Foreign revision id, can be any sort of object.
        :return: A bzr revision id.
        """
        raise NotImplementedError(self.revision_id_foreign_to_bzr)


class VcsMappingRegistry(registry.Registry):
    """Registry for Bazaar<->foreign VCS mappings.

    There should be one instance of this registry for every foreign VCS.
    """

    def register(self, key, factory, help):
        """Register a mapping between Bazaar and foreign VCS semantics.

        The factory must be a callable that takes one parameter: the key.
        It must produce an instance of VcsMapping when called.
        """
        if ":" in key:
            raise ValueError("mapping name can not contain colon (:)")
        registry.Registry.register(self, key, factory, help)

    def set_default(self, key):
        """Set the 'default' key to be a clone of the supplied key.

        This method must be called once and only once.
        """
        self._set_default_key(key)

    def get_default(self):
        """Convenience function for obtaining the default mapping to use."""
        return self.get(self._get_default_key())

    def revision_id_bzr_to_foreign(self, revid):
        """Convert a bzr revision id to a foreign revid."""
        raise NotImplementedError(self.revision_id_bzr_to_foreign)


class ForeignRevision(Revision):
    """A Revision from a Foreign repository. Remembers
    information about foreign revision id and mapping.

    """

    def __init__(self, foreign_revid, mapping, *args, **kwargs):
        if not "inventory_sha1" in kwargs:
            kwargs["inventory_sha1"] = ""
        super(ForeignRevision, self).__init__(*args, **kwargs)
        self.foreign_revid = foreign_revid
        self.mapping = mapping


class ForeignVcs(object):
    """A foreign version control system."""

    branch_format = None

    repository_format = None

    def __init__(self, mapping_registry, abbreviation=None):
        """Create a new foreign vcs instance.

        :param mapping_registry: Registry with mappings for this VCS.
        :param abbreviation: Optional abbreviation ('bzr', 'svn', 'git', etc)
        """
        self.abbreviation = abbreviation
        self.mapping_registry = mapping_registry

    def show_foreign_revid(self, foreign_revid):
        """Prepare a foreign revision id for formatting using bzr log.

        :param foreign_revid: Foreign revision id.
        :return: Dictionary mapping string keys to string values.
        """
        return { }

    def serialize_foreign_revid(self, foreign_revid):
        """Serialize a foreign revision id for this VCS.

        :param foreign_revid: Foreign revision id
        :return: Bytestring with serialized revid, will not contain any 
            newlines.
        """
        raise NotImplementedError(self.serialize_foreign_revid)


class ForeignVcsRegistry(registry.Registry):
    """Registry for Foreign VCSes.

    There should be one entry per foreign VCS. Example entries would be
    "git", "svn", "hg", "darcs", etc.

    """

    def register(self, key, foreign_vcs, help):
        """Register a foreign VCS.

        :param key: Prefix of the foreign VCS in revision ids
        :param foreign_vcs: ForeignVCS instance
        :param help: Description of the foreign VCS
        """
        if ":" in key or "-" in key:
            raise ValueError("vcs name can not contain : or -")
        registry.Registry.register(self, key, foreign_vcs, help)

    def parse_revision_id(self, revid):
        """Parse a bzr revision and return the matching mapping and foreign
        revid.

        :param revid: The bzr revision id
        :return: tuple with foreign revid and vcs mapping
        """
        if not ":" in revid or not "-" in revid:
            raise errors.InvalidRevisionId(revid, None)
        try:
            foreign_vcs = self.get(revid.split("-")[0])
        except KeyError:
            raise errors.InvalidRevisionId(revid, None)
        return foreign_vcs.mapping_registry.revision_id_bzr_to_foreign(revid)


foreign_vcs_registry = ForeignVcsRegistry()


class ForeignRepository(Repository):
    """A Repository that exists in a foreign version control system.

    The data in this repository can not be represented natively using
    Bazaars internal datastructures, but have to converted using a VcsMapping.
    """

    # This repository's native version control system
    vcs = None

    def has_foreign_revision(self, foreign_revid):
        """Check whether the specified foreign revision is present.

        :param foreign_revid: A foreign revision id, in the format used
                              by this Repository's VCS.
        """
        raise NotImplementedError(self.has_foreign_revision)

    def lookup_bzr_revision_id(self, revid):
        """Lookup a mapped or roundtripped revision by revision id.

        :param revid: Bazaar revision id
        :return: Tuple with foreign revision id and mapping.
        """
        raise NotImplementedError(self.lookup_revision_id)

    def all_revision_ids(self, mapping=None):
        """See Repository.all_revision_ids()."""
        raise NotImplementedError(self.all_revision_ids)

    def get_default_mapping(self):
        """Get the default mapping for this repository."""
        raise NotImplementedError(self.get_default_mapping)


class ForeignBranch(Branch):
    """Branch that exists in a foreign version control system."""

    def __init__(self, mapping):
        self.mapping = mapping
        super(ForeignBranch, self).__init__()


def update_workingtree_fileids(wt, target_tree):
    """Update the file ids in a working tree based on another tree.

    :param wt: Working tree in which to update file ids
    :param target_tree: Tree to retrieve new file ids from, based on path
    """
    tt = transform.TreeTransform(wt)
    try:
        for f, p, c, v, d, n, k, e in target_tree.iter_changes(wt):
            if v == (True, False):
                trans_id = tt.trans_id_tree_path(p[0])
                tt.unversion_file(trans_id)
            elif v == (False, True):
                trans_id = tt.trans_id_tree_path(p[1])
                tt.version_file(f, trans_id)
        tt.apply()
    finally:
        tt.finalize()
    if len(wt.get_parent_ids()) == 1:
        wt.set_parent_trees([(target_tree.get_revision_id(), target_tree)])
    else:
        wt.set_last_revision(target_tree.get_revision_id())


class cmd_dpush(Command):
    __doc__ = """Push into a different VCS without any custom bzr metadata.

    This will afterwards rebase the local branch on the remote
    branch unless the --no-rebase option is used, in which case 
    the two branches will be out of sync after the push. 
    """
    takes_args = ['location?']
    takes_options = [
        'remember',
        Option('directory',
               help='Branch to push from, '
               'rather than the one containing the working directory.',
               short_name='d',
               type=unicode,
               ),
        Option('no-rebase', help="Do not rebase after push."),
        Option('strict',
               help='Refuse to push if there are uncommitted changes in'
               ' the working tree, --no-strict disables the check.'),
        ]

    def run(self, location=None, remember=False, directory=None,
            no_rebase=False, strict=None):
        from bzrlib import urlutils
        from bzrlib.controldir import ControlDir
        from bzrlib.errors import BzrCommandError, NoWorkingTree
        from bzrlib.workingtree import WorkingTree

        if directory is None:
            directory = "."
        try:
            source_wt = WorkingTree.open_containing(directory)[0]
            source_branch = source_wt.branch
        except NoWorkingTree:
            source_branch = Branch.open(directory)
            source_wt = None
        if source_wt is not None:
            source_wt.check_changed_or_out_of_date(
                strict, 'dpush_strict',
                more_error='Use --no-strict to force the push.',
                more_warning='Uncommitted changes will not be pushed.')
        stored_loc = source_branch.get_push_location()
        if location is None:
            if stored_loc is None:
                raise BzrCommandError(gettext("No push location known or specified."))
            else:
                display_url = urlutils.unescape_for_display(stored_loc,
                        self.outf.encoding)
                self.outf.write(
                       gettext("Using saved location: %s\n") % display_url)
                location = stored_loc

        controldir = ControlDir.open(location)
        target_branch = controldir.open_branch()
        target_branch.lock_write()
        try:
            try:
                push_result = source_branch.push(target_branch, lossy=True)
            except errors.LossyPushToSameVCS:
                raise BzrCommandError(gettext("{0!r} and {1!r} are in the same VCS, lossy "
                    "push not necessary. Please use regular push.").format(
                    source_branch, target_branch))
            # We successfully created the target, remember it
            if source_branch.get_push_location() is None or remember:
                # FIXME: Should be done only if we succeed ? -- vila 2012-01-18
                source_branch.set_push_location(target_branch.base)
            if not no_rebase:
                old_last_revid = source_branch.last_revision()
                source_branch.pull(target_branch, overwrite=True)
                new_last_revid = source_branch.last_revision()
                if source_wt is not None and old_last_revid != new_last_revid:
                    source_wt.lock_write()
                    try:
                        target = source_wt.branch.repository.revision_tree(
                            new_last_revid)
                        update_workingtree_fileids(source_wt, target)
                    finally:
                        source_wt.unlock()
            push_result.report(self.outf)
        finally:
            target_branch.unlock()
