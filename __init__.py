# Copyright (C) 2008, 2009, 2010 Canonical Ltd
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

"""Upload a working tree, incrementally.

Quickstart
----------

To get started, it's as simple as running::

    bzr upload sftp://user@host/location/on/webserver

This will initially upload the whole working tree, and leave a file on the
remote location indicating the last revision that was uploaded
(.bzr-upload.revid), in order to avoid uploading unnecessary information the
next time.

If you would like to upload a specific revision, you just do:

    bzr upload -r X  sftp://user@host/location/on/webserver

bzr-upload, just as bzr does, will remember the location where you upload the 
first time, so you don't need to specify it every time.

If you need to re-upload the whole working tree for some reason, you can:

    bzr upload --full sftp://user@host/location/on/webserver

This command only works on the revision beening uploaded is a decendent of the
revision that was previously uploaded, and that they are hence from branches
that have not diverged. Branches are considered diverged if the destination
branch's most recent commit is one that has not been merged (directly or
indirectly) by the source branch.

If branches have diverged, you can use 'bzr upload --overwrite' to replace
the other branch completely, discarding its unmerged changes.


Automatically Uploading
-----------------------

bzr-upload comes with a hook that can be used to trigger an upload whenever
the tip of the branch changes, including on commit, push, uncommit etc. This
would allow you to keep the code on the target up to date automatically.

The easiest way to enable this is to run upload with the --auto option.

     bzr upload --auto

will enable the hook for this branch. If you were to do a commit in this branch
now you would see it trigger the upload automatically.

If you wish to disable this for a branch again then you can use the --no-auto
option.

     bzr upload --no-auto

will disable the feature for that branch.

Since the auto hook is triggered automatically, you can't use the --quiet
option available for the upload command. Instead, you can set the
'upload_auto_quiet' configuration variable to True or False in either
bazaar.conf, locations.conf or branch.conf.


Storing the '.bzr-upload.revid' file
------------------------------------

The only bzr-related info uploaded with the working tree is the corresponding
revision id. The uploaded working tree is not linked to any other bzr data.

If the layout of your remote server is such that you can't write in the
root directory but only in the directories inside that root, you will need
to use the 'upload_revid_location' configuration variable to specify the
relative path to be used. That configuration variable can be specified in
locations.conf or branch.conf.

For example, given the following layout:

  Project/
    private/
    public/

you may have write access in 'private' and 'public' but in 'Project'
itself. In that case, you can add the following in your locations.conf or
branch.conf file:

  upload_revid_location = private/.bzr-upload.revid


Upload from Remote Location
---------------------------

It is possible to upload to a remote location from another remote location by
specifying it with the --directory option:

    bzr upload ftp://public.example.com --directory sftp://private.example.com 

This, together with --auto, can be used to upload when you push to your
central branch, rather than when you commit to your local branch.

Note that you will consume more bandwith this way than uploading from a local
branch.

Ignoring certain files
-----------------------

If you want to version a file, but not upload it, you can create a file called
.bzrignore-upload, which works in the same way as the regular .bzrignore file,
but only applies to bzr-upload.


Collaborating
-------------

While we don't have any platform setup, you can branch from trunk:

    bzr branch lp:bzr-upload

And change anything you'd like, and file a merge proposal on Launchpad.


Known Issues
------------

 * Symlinks are not supported (warnings are emitted when they are encountered).


"""

# TODO: the chmod bits *can* be supported via the upload protocols
# (i.e. poorly), but since the web developers use these protocols to upload
# manually, it is expected that the associated web server is coherent with
# their presence/absence. In other words, if a web hosting provider requires
# chmod bits but don't provide an ftp server that support them, well, better
# find another provider ;-)

# TODO: The message emitted in verbose mode displays local paths. That may be
# scary for the user when we say 'Deleting <path>' and are referring to
# remote files...

import bzrlib
import bzrlib.api

from bzrlib import (
    branch,
    )

from info import (
    bzr_plugin_version as version_info,
    bzr_compatible_versions,
    )

if version_info[3] == 'final':
    version_string = '%d.%d.%d' % version_info[:3]
else:
    version_string = '%d.%d.%d%s%d' % version_info
__version__ = version_string

bzrlib.api.require_any_api(bzrlib, bzr_compatible_versions)

from bzrlib.commands import plugin_cmds

plugin_cmds.register_lazy('cmd_upload', [], 'bzrlib.plugins.upload.cmds')

def auto_upload_hook(params):
    from bzrlib import (
        osutils,
        trace,
        transport,
        urlutils,
        )
    from bzrlib.plugins.upload.cmds import (
        BzrUploader,
        get_upload_location,
        get_upload_auto,
        get_upload_auto_quiet,
        )
    import sys
    source_branch = params.branch
    destination = get_upload_location(source_branch)
    if destination is None:
        return
    auto_upload = get_upload_auto(source_branch)
    if not auto_upload:
        return
    quiet = get_upload_auto_quiet(source_branch)
    if not quiet:
        display_url = urlutils.unescape_for_display(
            destination, osutils.get_terminal_encoding())
        trace.note('Automatically uploading to %s', display_url)
    to_transport = transport.get_transport(destination)
    last_revision = source_branch.last_revision()
    last_tree = source_branch.repository.revision_tree(last_revision)
    uploader = BzrUploader(source_branch, to_transport, sys.stdout,
                           last_tree, last_revision, quiet=quiet)
    uploader.upload_tree()


def install_auto_upload_hook():
    branch.Branch.hooks.install_named_hook('post_change_branch_tip',
            auto_upload_hook,
            'Auto upload code from a branch when it is changed.')


install_auto_upload_hook()
    auto_hook_available = True
else:
    auto_hook_available = False


def load_tests(basic_tests, module, loader):
    # This module shouldn't define any tests but I don't know how to report
    # that. I prefer to update basic_tests with the other tests to detect
    # unwanted tests and I think that's sufficient.

    testmod_names = [
        'tests',
        ]
    basic_tests.addTest(loader.loadTestsFromModuleNames(
            ["%s.%s" % (__name__, tmn) for tmn in testmod_names]))
    return basic_tests
