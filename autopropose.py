# Copyright (C) 2018 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Autopropose implementation."""

from ... import (
    branch as _mod_branch,
    errors,
    osutils,
    )
from ...i18n import gettext
from ...commit import PointlessCommit
from ...trace import note
from ...transport import get_transport
from . import (
    propose as _mod_propose,
    )
import os
import subprocess
import shutil
import tempfile


def autopropose(branch, script, name=None, overwrite=False):
    main_branch = _mod_branch.Branch.open(branch)
    hoster = _mod_propose.get_hoster(main_branch)
    td = tempfile.mkdtemp()
    try:
        # preserve whatever source format we have.
        to_dir = main_branch.controldir.sprout(
                get_transport(td).base, None, create_tree_if_local=True,
                source_branch=main_branch)
        local_tree = to_dir.open_workingtree()
        local_branch = to_dir.open_branch()
        p = subprocess.Popen(script, cwd=td, stdout=subprocess.PIPE)
        (description, err) = p.communicate("")
        if p.returncode != 0:
            raise errors.BzrCommandError(
                gettext("Script %s failed with error code %d") % (
                    script, p.returncode))
        try:
            local_tree.commit(description, allow_pointless=False)
        except PointlessCommit:
            raise errors.BzrCommandError(gettext(
                "Script didn't make any changes"))
        if name is None:
            name = os.path.splitext(osutils.basename(script.split(' ')[0]))[0]
        remote_branch, public_branch_url = hoster.publish(
                local_branch, main_branch, name=name, overwrite=overwrite)
    finally:
        shutil.rmtree(td)
    note(gettext('Published branch to %s') % public_branch_url)
    proposal_builder = hoster.get_proposer(remote_branch, main_branch)
    proposal = proposal_builder.create_proposal(description=description)
    note(gettext('Merge proposal created: %s') % proposal.url)
