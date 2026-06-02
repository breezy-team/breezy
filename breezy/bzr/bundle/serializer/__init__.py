# Copyright (C) 2005, 2006, 2007, 2009, 2010 Canonical Ltd
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

"""Serializer factory for reading and writing bundles."""

import base64
import re
from io import BytesIO

from .... import errors, registry
from ....diff import internal_diff

# For backwards-compatibility

# New bundles should try to use this header format
BUNDLE_HEADER = b"# Bazaar revision bundle v"
BUNDLE_HEADER_RE = re.compile(
    rb"^# Bazaar revision bundle v(?P<version>\d+[\w.]*)(?P<lineending>\r?)\n$"
)
CHANGESET_OLD_HEADER_RE = re.compile(
    rb"^# Bazaar-NG changeset v(?P<version>\d+[\w.]*)(?P<lineending>\r?)\n$"
)


def _get_bundle_header(version):
    r"""Generate a bundle header string for the specified version.

    Creates a properly formatted bundle header by combining the standard
    bundle header prefix with the specified version string.

    Args:
        version: The version string to include in the header (e.g., "4", "0.9").

    Returns:
        bytes: The complete bundle header as bytes, including trailing newline.

    Example:
        >>> _get_bundle_header("4")
        b'# Bazaar revision bundle v4\n'
    """
    return b"".join([BUNDLE_HEADER, version.encode("ascii"), b"\n"])


def _get_filename(f):
    """Get the filename from a file-like object.

    Attempts to extract the filename from a file-like object's 'name' attribute.
    If the object doesn't have a name attribute, returns a default placeholder.

    Args:
        f: A file-like object that may have a 'name' attribute.

    Returns:
        str: The filename if available, otherwise "<unknown>".

    Note:
        This is commonly used for error reporting and debugging purposes
        when working with file objects that may not have associated filenames.
    """
    return getattr(f, "name", "<unknown>")


def read_bundle(f):
    """Read in a bundle from a filelike object.

    :param f: A file-like object
    :return: A list of Bundle objects
    """
    version = None
    for line in f:
        m = BUNDLE_HEADER_RE.match(line)
        if m:
            if m.group("lineending") != b"":
                raise errors.UnsupportedEOLMarker()
            version = m.group("version")
            break
        elif line.startswith(BUNDLE_HEADER):
            raise errors.MalformedHeader("Extra characters after version number")
        m = CHANGESET_OLD_HEADER_RE.match(line)
        if m:
            version = m.group("version")
            raise errors.BundleNotSupported(version, "old format bundles not supported")

    if version is None:
        raise errors.NotABundle("Did not find an opening header")

    return get_serializer(version.decode("ascii")).read(f)


def get_serializer(version):
    """Get a bundle serializer instance for the specified version.

    Looks up and instantiates a bundle serializer from the registry based on
    the provided version string. The serializer handles reading and writing
    bundles in the specified format.

    Args:
        version: The bundle format version string (e.g., "4", "0.9", "0.8").

    Returns:
        BundleSerializer: An instantiated serializer object for the specified version.

    Raises:
        BundleNotSupported: If the specified version is not registered or supported.

    Example:
        >>> serializer = get_serializer("4")
        >>> isinstance(serializer, BundleSerializer)
        True
    """
    try:
        serializer = serializer_registry.get(version)
    except KeyError as e:
        raise errors.BundleNotSupported(version, "unknown bundle format") from e

    return serializer(version)


def write(source, revision_ids, f, version=None, forced_bases=None):
    """Serialize a list of bundles to a filelike object.

    :param source: A source for revision information
    :param revision_ids: The list of revision ids to serialize
    :param f: The file to output to
    :param version: [optional] target serialization version
    """
    if forced_bases is None:
        forced_bases = {}
    with source.lock_read():
        return get_serializer(version).write(source, revision_ids, forced_bases, f)


def write_bundle(repository, revision_id, base_revision_id, out, format=None):
    """Write a bundle of revisions.

    :param repository: Repository containing revisions to serialize.
    :param revision_id: Head revision_id of the bundle.
    :param base_revision_id: Revision assumed to be present in repositories
         applying the bundle.
    :param out: Output file.
    :return: List of revision ids written
    """
    with repository.lock_read():
        return get_serializer(format).write_bundle(
            repository, revision_id, base_revision_id, out
        )


class BundleSerializer:
    """The base class for Serializers.

    Common functionality should be included here.
    """

    def __init__(self, version):
        """Initialize a BundleSerializer instance.

        Args:
            version: The bundle format version this serializer handles.
                    This determines the specific serialization format and
                    capabilities of the serializer instance.

        Attributes:
            version: The bundle format version string this serializer supports.
        """
        self.version = version

    def read(self, f):
        """Read the rest of the bundles from the supplied file.

        :param f: The file to read from
        :return: A list of bundle trees
        """
        raise NotImplementedError

    def write_bundle(self, repository, target, base, fileobj):
        """Write the bundle to the supplied file.

        :param repository: The repository to retrieve revision data from
        :param target: The revision to provide data for
        :param base: The most recent of ancestor of the revision that does not
            need to be included in the bundle
        :param fileobj: The file to output to
        :return: List of revision ids written
        """
        raise NotImplementedError


def binary_diff(old_filename, old_lines, new_filename, new_lines, to_file):
    """Generate a base64-encoded diff for binary or text content.

    Creates a unified diff between old and new content, then encodes the result
    in base64 format. This is useful for including binary file changes in
    text-based bundle formats where raw binary data cannot be embedded directly.

    Args:
        old_filename: The original filename or identifier for the old content.
        old_lines: List of lines representing the original file content.
        new_filename: The new filename or identifier for the modified content.
        new_lines: List of lines representing the modified file content.
        to_file: The file-like object to write the base64-encoded diff to.

    Note:
        The diff is generated using internal_diff with binary support enabled,
        then base64-encoded for safe inclusion in text-based formats. A trailing
        newline is appended after the base64 content.

    Side Effects:
        Writes base64-encoded diff data followed by a newline to the to_file object.
    """
    temp = BytesIO()
    internal_diff(
        old_filename, old_lines, new_filename, new_lines, temp, allow_binary=True
    )
    temp.seek(0)
    base64.encode(temp, to_file)
    to_file.write(b"\n")


serializer_registry = registry.Registry[str, BundleSerializer, None]()

serializer_registry.register_lazy("0.8", __name__ + ".v08", "BundleSerializerV08")
serializer_registry.register_lazy("0.9", __name__ + ".v09", "BundleSerializerV09")
serializer_registry.register_lazy("4", __name__ + ".v4", "BundleSerializerV4")
serializer_registry.default_key = "4"
