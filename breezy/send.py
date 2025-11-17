# Copyright (C) 2009, 2010 Canonical Ltd
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

import os
import time
from collections.abc import Callable

from . import controldir, errors, osutils, registry, trace
from .branch import Branch
from .i18n import gettext
from .revision import NULL_REVISION

format_registry = registry.Registry[str, Callable]()


def send(
    target_branch,
    revision,
    public_branch,
    remember,
    format,
    no_bundle,
    no_patch,
    output,
    from_,
    mail_to,
    message,
    body,
    to_file,
    strict=None,
):
    possible_transports = []
    tree, branch = controldir.ControlDir.open_containing_tree_or_branch(
        from_, possible_transports=possible_transports
    )[:2]
    # we may need to write data into branch's repository to calculate
    # the data to send.
    with branch.lock_write():
        if output is None:
            config_stack = branch.get_config_stack()
            if mail_to is None:
                mail_to = config_stack.get("submit_to")
            mail_client = config_stack.get("mail_client")(config_stack)
            if not getattr(mail_client, "supports_body", False) and body is not None:
                raise errors.CommandError(
                    gettext('Mail client "%s" does not support specifying body')
                    % mail_client.__class__.__name__
                )
        if remember and target_branch is None:
            raise errors.CommandError(
                gettext("--remember requires a branch to be specified.")
            )
        stored_target_branch = branch.get_submit_branch()
        remembered_target_branch = None
        if target_branch is None:
            target_branch = stored_target_branch
            remembered_target_branch = "submit"
        else:
            # Remembers if asked explicitly or no previous location is set
            if remember or (remember is None and stored_target_branch is None):
                branch.set_submit_branch(target_branch)
        if target_branch is None:
            target_branch = branch.get_parent()
            remembered_target_branch = "parent"
        if target_branch is None:
            raise errors.CommandError(gettext("No submit branch known or specified"))
        if remembered_target_branch is not None:
            trace.note(
                gettext(
                    'Using saved {0} location "{1}" to determine '
                    "what changes to submit."
                ).format(remembered_target_branch, target_branch)
            )

        submit_branch = Branch.open(
            target_branch, possible_transports=possible_transports
        )
        possible_transports.append(submit_branch.controldir.root_transport)
        if mail_to is None or format is None:
            if mail_to is None:
                mail_to = submit_branch.get_config_stack().get("child_submit_to")
            if format is None:
                formatname = submit_branch.get_child_submit_format()
                try:
                    format = format_registry.get(formatname)
                except KeyError:
                    raise errors.CommandError(
                        gettext("No such send format '%s'.") % formatname
                    )

        stored_public_branch = branch.get_public_branch()
        if public_branch is None:
            public_branch = stored_public_branch
        # Remembers if asked explicitly or no previous location is set
        elif remember or (remember is None and stored_public_branch is None):
            branch.set_public_branch(public_branch)
        if no_bundle and public_branch is None:
            raise errors.CommandError(gettext("No public branch specified or known"))
        base_revision_id = None
        revision_id = None
        if revision is not None:
            if len(revision) > 2:
                raise errors.CommandError(
                    gettext("bzr send takes at most two one revision identifiers")
                )
            revision_id = revision[-1].as_revision_id(branch)
            if len(revision) == 2:
                base_revision_id = revision[0].as_revision_id(branch)
        if revision_id is None:
            if tree is not None:
                tree.check_changed_or_out_of_date(
                    strict,
                    "send_strict",
                    more_error="Use --no-strict to force the send.",
                    more_warning="Uncommitted changes will not be sent.",
                )
            revision_id = branch.last_revision()
        if revision_id == NULL_REVISION:
            raise errors.CommandError(gettext("No revisions to submit."))
        if format is None:
            format = format_registry.get()
        directive = format(
            branch,
            revision_id,
            target_branch,
            public_branch,
            no_patch,
            no_bundle,
            message,
            base_revision_id,
            submit_branch,
        )
        if output is None:
            directive.compose_merge_request(mail_client, mail_to, body, branch, tree)
        else:
            if directive.multiple_output_files:
                if output == "-":
                    raise errors.CommandError(
                        gettext(
                            "- not supported for "
                            "merge directives that use more than one output file."
                        )
                    )
                if not os.path.exists(output):
                    os.mkdir(output, 0o755)
                for filename, lines in directive.to_files():
                    path = os.path.join(output, filename)
                    with open(path, "wb") as outfile:
                        outfile.writelines(lines)
            else:
                if output == "-":
                    outfile = to_file
                else:
                    outfile = open(output, "wb")
                try:
                    outfile.writelines(directive.to_lines())
                finally:
                    if outfile is not to_file:
                        outfile.close()


def _send_4(
    branch,
    revision_id,
    target_branch,
    public_branch,
    no_patch,
    no_bundle,
    message,
    base_revision_id,
    local_target_branch=None,
):
    from breezy import merge_directive

    return merge_directive.MergeDirective2.from_objects(
        branch.repository,
        revision_id,
        time.time(),
        osutils.local_time_offset(),
        target_branch,
        public_branch=public_branch,
        include_patch=not no_patch,
        include_bundle=not no_bundle,
        message=message,
        base_revision_id=base_revision_id,
        local_target_branch=local_target_branch,
    )


def _send_0_9(
    branch,
    revision_id,
    submit_branch,
    public_branch,
    no_patch,
    no_bundle,
    message,
    base_revision_id,
    local_target_branch=None,
):
    if not no_bundle:
        if not no_patch:
            patch_type = "bundle"
        else:
            raise errors.CommandError(
                gettext("Format 0.9 does not permit bundle with no patch")
            )
    else:
        if not no_patch:
            patch_type = "diff"
        else:
            patch_type = None
    from breezy import merge_directive

    return merge_directive.MergeDirective.from_objects(
        branch.repository,
        revision_id,
        time.time(),
        osutils.local_time_offset(),
        submit_branch,
        public_branch=public_branch,
        patch_type=patch_type,
        message=message,
        local_target_branch=local_target_branch,
    )


format_registry.register("4", _send_4, "Bundle format 4, Merge Directive 2 (default)")
format_registry.register("0.9", _send_0_9, "Bundle format 0.9, Merge Directive 1")
format_registry.default_key = "4"
