# Copyright (C) 2005, 2006, 2007, 2009, 2010, 2011 Canonical Ltd
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

"""\
This contains functionality for installing bundles into repositories.
"""

from ... import ui
from ...i18n import gettext
from ...merge import Merger
from ...progress import ProgressPhase
from ...trace import note
from ..vf_repository import install_revision


def install_bundle(repository, bundle_reader):
    custom_install = getattr(bundle_reader, "install", None)
    if custom_install is not None:
        return custom_install(repository)
    with repository.lock_write(), ui.ui_factory.nested_progress_bar() as pb:
        real_revisions = bundle_reader.real_revisions
        for i, revision in enumerate(reversed(real_revisions)):
            pb.update(gettext("Install revisions"), i, len(real_revisions))
            if repository.has_revision(revision.revision_id):
                continue
            cset_tree = bundle_reader.revision_tree(repository, revision.revision_id)
            install_revision(repository, revision, cset_tree)


def merge_bundle(
    reader, tree, check_clean, merge_type, reprocess, show_base, change_reporter=None
):
    """Merge a revision bundle into the current tree."""
    with ui.ui_factory.nested_progress_bar() as pb:
        pp = ProgressPhase("Merge phase", 6, pb)
        pp.next_phase()
        install_bundle(tree.branch.repository, reader)
        merger = Merger(tree.branch, this_tree=tree, change_reporter=change_reporter)
        merger.pp = pp
        merger.pp.next_phase()
        if check_clean and tree.has_changes():
            raise errors.UncommittedChanges(self)
        merger.other_rev_id = reader.target
        merger.other_tree = merger.revision_tree(reader.target)
        merger.other_basis = reader.target
        merger.pp.next_phase()
        merger.find_base()
        if merger.base_rev_id == merger.other_rev_id:
            note(gettext("Nothing to do."))
            return 0
        merger.merge_type = merge_type
        merger.show_base = show_base
        merger.reprocess = reprocess
        conflicts = merger.do_merge()
        merger.set_pending()
    return conflicts
