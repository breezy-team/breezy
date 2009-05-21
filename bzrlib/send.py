# Copyright (C) 2009 Canonical Ltd
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


import time

from bzrlib import (
    errors,
    merge_directive,
    osutils,
    registry,
    trace,
    )
from bzrlib.commands import (
    Command,
    )
from bzrlib.option import (
    Option,
    RegistryOption,
    )


format_registry = registry.Registry()


class cmd_send(Command):
    """Mail or create a merge-directive for submitting changes.

    A merge directive provides many things needed for requesting merges:

    * A machine-readable description of the merge to perform

    * An optional patch that is a preview of the changes requested

    * An optional bundle of revision data, so that the changes can be applied
      directly from the merge directive, without retrieving data from a
      branch.

    If --no-bundle is specified, then public_branch is needed (and must be
    up-to-date), so that the receiver can perform the merge using the
    public_branch.  The public_branch is always included if known, so that
    people can check it later.

    The submit branch defaults to the parent, but can be overridden.  Both
    submit branch and public branch will be remembered if supplied.

    If a public_branch is known for the submit_branch, that public submit
    branch is used in the merge instructions.  This means that a local mirror
    can be used as your actual submit branch, once you have set public_branch
    for that mirror.

    Mail is sent using your preferred mail program.  This should be transparent
    on Windows (it uses MAPI).  On Linux, it requires the xdg-email utility.
    If the preferred client can't be found (or used), your editor will be used.

    To use a specific mail program, set the mail_client configuration option.
    (For Thunderbird 1.5, this works around some bugs.)  Supported values for
    specific clients are "claws", "evolution", "kmail", "mutt", and
    "thunderbird"; generic options are "default", "editor", "emacsclient",
    "mapi", and "xdg-email".  Plugins may also add supported clients.

    If mail is being sent, a to address is required.  This can be supplied
    either on the commandline, by setting the submit_to configuration
    option in the branch itself or the child_submit_to configuration option
    in the submit branch.

    Two formats are currently supported: "4" uses revision bundle format 4 and
    merge directive format 2.  It is significantly faster and smaller than
    older formats.  It is compatible with Bazaar 0.19 and later.  It is the
    default.  "0.9" uses revision bundle format 0.9 and merge directive
    format 1.  It is compatible with Bazaar 0.12 - 0.18.

    The merge directives created by bzr send may be applied using bzr merge or
    bzr pull by specifying a file containing a merge directive as the location.
    """

    encoding_type = 'exact'

    _see_also = ['merge', 'pull']

    takes_args = ['submit_branch?', 'public_branch?']

    takes_options = [
        Option('no-bundle',
               help='Do not include a bundle in the merge directive.'),
        Option('no-patch', help='Do not include a preview patch in the merge'
               ' directive.'),
        Option('remember',
               help='Remember submit and public branch.'),
        Option('from',
               help='Branch to generate the submission from, '
               'rather than the one containing the working directory.',
               short_name='f',
               type=unicode),
        Option('output', short_name='o',
               help='Write merge directive to this file; '
                    'use - for stdout.',
               type=unicode),
        Option('mail-to', help='Mail the request to this address.',
               type=unicode),
        'revision',
        'message',
        Option('body', help='Body for the email.', type=unicode),
        RegistryOption('format',
                       help='Use the specified output format.', 
                       registry=format_registry)
        ]

    def run(self, submit_branch=None, public_branch=None, no_bundle=False,
            no_patch=False, revision=None, remember=False, output=None,
            format=None, mail_to=None, message=None, body=None, **kwargs):
        return self._run(submit_branch, revision, public_branch, remember,
                         format, no_bundle, no_patch, output,
                         kwargs.get('from', '.'), mail_to, message, body)

    def _run(self, submit_branch, revision, public_branch, remember, format,
             no_bundle, no_patch, output, from_, mail_to, message, body):
        from bzrlib import bzrdir
        from bzrlib.branch import Branch
        from bzrlib.revision import NULL_REVISION
        tree, branch = bzrdir.BzrDir.open_containing_tree_or_branch(from_)[:2]
        # we may need to write data into branch's repository to calculate
        # the data to send.
        branch.lock_write()
        try:
            if output is None:
                config = branch.get_config()
                if mail_to is None:
                    mail_to = config.get_user_option('submit_to')
                mail_client = config.get_mail_client()
                if (not getattr(mail_client, 'supports_body', False)
                    and body is not None):
                    raise errors.BzrCommandError(
                        'Mail client "%s" does not support specifying body' %
                        mail_client.__class__.__name__)
            if remember and submit_branch is None:
                raise errors.BzrCommandError(
                    '--remember requires a branch to be specified.')
            stored_submit_branch = branch.get_submit_branch()
            remembered_submit_branch = None
            if submit_branch is None:
                submit_branch = stored_submit_branch
                remembered_submit_branch = "submit"
            else:
                if stored_submit_branch is None or remember:
                    branch.set_submit_branch(submit_branch)
            if submit_branch is None:
                submit_branch = branch.get_parent()
                remembered_submit_branch = "parent"
            if submit_branch is None:
                raise errors.BzrCommandError('No submit branch known or'
                                             ' specified')
            if remembered_submit_branch is not None:
                trace.note('Using saved %s location "%s" to determine what '
                           'changes to submit.', remembered_submit_branch,
                           submit_branch)

            if mail_to is None:
                submit_config = Branch.open(submit_branch).get_config()
                mail_to = submit_config.get_user_option("child_submit_to")

            stored_public_branch = branch.get_public_branch()
            if public_branch is None:
                public_branch = stored_public_branch
            elif stored_public_branch is None or remember:
                branch.set_public_branch(public_branch)
            if no_bundle and public_branch is None:
                raise errors.BzrCommandError('No public branch specified or'
                                             ' known')
            base_revision_id = None
            revision_id = None
            if revision is not None:
                if len(revision) > 2:
                    raise errors.BzrCommandError('bzr send takes '
                        'at most two one revision identifiers')
                revision_id = revision[-1].as_revision_id(branch)
                if len(revision) == 2:
                    base_revision_id = revision[0].as_revision_id(branch)
            if revision_id is None:
                revision_id = branch.last_revision()
            if revision_id == NULL_REVISION:
                raise errors.BzrCommandError('No revisions to submit.')
            if format is None:
                # TODO: Query submit branch for its preferred format
                format = format_registry.get()
            directive = format(branch, revision_id, submit_branch, 
                public_branch, no_patch, no_bundle, message, base_revision_id)
            if output is None:
                directive.compose_merge_request(mail_client, mail_to, body,
                                                branch, tree)
            else:
                if output == '-':
                    outfile = self.outf
                else:
                    outfile = open(output, 'wb')
                try:
                    outfile.writelines(directive.to_lines())
                finally:
                    if outfile is not self.outf:
                        outfile.close()
        finally:
            branch.unlock()


class cmd_bundle_revisions(cmd_send):

    """Create a merge-directive for submitting changes.

    A merge directive provides many things needed for requesting merges:

    * A machine-readable description of the merge to perform

    * An optional patch that is a preview of the changes requested

    * An optional bundle of revision data, so that the changes can be applied
      directly from the merge directive, without retrieving data from a
      branch.

    If --no-bundle is specified, then public_branch is needed (and must be
    up-to-date), so that the receiver can perform the merge using the
    public_branch.  The public_branch is always included if known, so that
    people can check it later.

    The submit branch defaults to the parent, but can be overridden.  Both
    submit branch and public branch will be remembered if supplied.

    If a public_branch is known for the submit_branch, that public submit
    branch is used in the merge instructions.  This means that a local mirror
    can be used as your actual submit branch, once you have set public_branch
    for that mirror.

    Two formats are currently supported: "4" uses revision bundle format 4 and
    merge directive format 2.  It is significantly faster and smaller than
    older formats.  It is compatible with Bazaar 0.19 and later.  It is the
    default.  "0.9" uses revision bundle format 0.9 and merge directive
    format 1.  It is compatible with Bazaar 0.12 - 0.18.
    """

    takes_options = [
        Option('no-bundle',
               help='Do not include a bundle in the merge directive.'),
        Option('no-patch', help='Do not include a preview patch in the merge'
               ' directive.'),
        Option('remember',
               help='Remember submit and public branch.'),
        Option('from',
               help='Branch to generate the submission from, '
               'rather than the one containing the working directory.',
               short_name='f',
               type=unicode),
        Option('output', short_name='o', help='Write directive to this file.',
               type=unicode),
        'revision',
        RegistryOption('format',
                       help='Use the specified output format.',
                       registry=format_registry),
        ]
    aliases = ['bundle']

    _see_also = ['send', 'merge']

    hidden = True

    def run(self, submit_branch=None, public_branch=None, no_bundle=False,
            no_patch=False, revision=None, remember=False, output=None,
            format=None, **kwargs):
        if output is None:
            output = '-'
        return self._run(submit_branch, revision, public_branch, remember,
                         format, no_bundle, no_patch, output,
                         kwargs.get('from', '.'), None, None, None)


def _send_4(branch, revision_id, submit_branch, public_branch,
            no_patch, no_bundle, message, base_revision_id):
    return merge_directive.MergeDirective2.from_objects(
        branch.repository, revision_id, time.time(),
        osutils.local_time_offset(), submit_branch,
        public_branch=public_branch, include_patch=not no_patch,
        include_bundle=not no_bundle, message=message,
        base_revision_id=base_revision_id)


def _send_0_9(branch, revision_id, submit_branch, public_branch,
              no_patch, no_bundle, message, base_revision_id):
    if not no_bundle:
        if not no_patch:
            patch_type = 'bundle'
        else:
            raise errors.BzrCommandError('Format 0.9 does not'
                ' permit bundle with no patch')
    else:
        if not no_patch:
            patch_type = 'diff'
        else:
            patch_type = None
    return merge_directive.MergeDirective.from_objects(
        branch.repository, revision_id, time.time(),
        osutils.local_time_offset(), submit_branch,
        public_branch=public_branch, patch_type=patch_type,
        message=message)


format_registry.register('4', 
    _send_4, 'Bundle format 4, Merge Directive 2 (default)')
format_registry.register('0.9',
    _send_0_9, 'Bundle format 0.9, Merge Directive 1')
format_registry.default_key = '4'
