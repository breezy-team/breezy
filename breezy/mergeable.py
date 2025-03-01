# Copyright (C) 2005-2010 Canonical Ltd
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

from io import BytesIO

from .lazy_import import lazy_import

lazy_import(
    globals(),
    """
from breezy.i18n import gettext
""",
)

from . import errors, urlutils
from .trace import note
from .transport import do_catching_redirections, get_transport, get_transport_from_url


class Mergeable:
    """A mergeable object."""

    def install_revisions(self, repository):
        """Install the data from this mergeable into the specified repository.

        :param repository: Repository
        """
        raise NotImplementedError(self.install_revisions)

    def get_merge_request(self, repository):
        """Extract merge request data.

        :return: tuple with (base_revision_id, target_revision_id, verified)
        """
        raise NotImplementedError(self.get_merge_request)


def read_mergeable_from_url(url, _do_directive=True, possible_transports=None):
    """Read mergable object from a given URL.

    :return: An object supporting get_target_revision.  Raises NotABundle if
        the target is not a mergeable type.
    """
    child_transport = get_transport(url, possible_transports=possible_transports)
    transport = child_transport.clone("..")
    filename = transport.relpath(child_transport.base)
    mergeable, transport = read_mergeable_from_transport(
        transport, filename, _do_directive
    )
    return mergeable


def read_mergeable_from_transport(transport, filename, _do_directive=True):
    def get_bundle(transport):
        return BytesIO(transport.get_bytes(filename)), transport

    def redirected_transport(transport, exception, redirection_notice):
        note(redirection_notice)
        url, filename = urlutils.split(exception.target, exclude_trailing_slash=False)
        if not filename:
            raise errors.NotABundle(gettext("A directory cannot be a bundle"))
        return get_transport_from_url(url)

    try:
        bytef, transport = do_catching_redirections(
            get_bundle, transport, redirected_transport
        )
    except errors.TooManyRedirections:
        raise errors.NotABundle(transport.clone(filename).base)
    except (errors.ConnectionReset, errors.ConnectionError):
        raise
    except (errors.TransportError, errors.PathError) as e:
        raise errors.NotABundle(str(e))
    except OSError as e:
        # jam 20060707
        # Abstraction leakage, SFTPTransport.get('directory')
        # doesn't always fail at get() time. Sometimes it fails
        # during read. And that raises a generic IOError with
        # just the string 'Failure'
        # StubSFTPServer does fail during get() (because of prefetch)
        # so it has an opportunity to translate the error.
        raise errors.NotABundle(str(e))

    if _do_directive:
        from .merge_directive import MergeDirective

        try:
            return MergeDirective.from_lines(bytef), transport
        except errors.NotAMergeDirective:
            bytef.seek(0)

    from .bzr.bundle import serializer as _serializer

    return _serializer.read_bundle(bytef), transport
