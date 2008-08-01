# Copyright (C) 2008 Canonical Ltd
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

import sys


from bzrlib import branch, transport, urlutils


from bzrlib.plugins.upload import (
        BzrUploader,
        get_upload_location,
        get_upload_auto,
        )


def auto_upload_hook(params, quiet=False):
    source_branch = params.branch
    destination = get_upload_location(source_branch)
    if destination is None:
        return
    auto_upload = get_upload_auto(source_branch)
    if not auto_upload:
        return
    if not quiet:
        display_url = urlutils.unescape_for_display(destination,
                sys.stdout.encoding)
        print "Automatically uploading to %s" % display_url
    to_transport = transport.get_transport(destination)
    last_revision = source_branch.last_revision()
    last_tree = source_branch.repository.revision_tree(last_revision)
    uploader = BzrUploader(source_branch, to_transport, sys.stdout,
            last_tree, last_revision, quiet=quiet)
    uploader.upload_tree()
