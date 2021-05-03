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

"""Serializer factory for reading and writing bundles.
"""

import base64
from io import BytesIO
import re

from .... import (
    errors,
    registry,
    )
from ....diff import internal_diff
from ....revision import NULL_REVISION
# For backwards-compatibility
from ....timestamp import unpack_highres_date, format_highres_date


# New bundles should try to use this header format
BUNDLE_HEADER = b'# Bazaar revision bundle v'
BUNDLE_HEADER_RE = re.compile(
    br'^# Bazaar revision bundle v(?P<version>\d+[\w.]*)(?P<lineending>\r?)\n$')
CHANGESET_OLD_HEADER_RE = re.compile(
    br'^# Bazaar-NG changeset v(?P<version>\d+[\w.]*)(?P<lineending>\r?)\n$')


serializer_registry = registry.Registry()


def _get_bundle_header(version):
    return b''.join([BUNDLE_HEADER, version.encode('ascii'), b'\n'])


def _get_filename(f):
    return getattr(f, 'name', '<unknown>')


def read_bundle(f):
    """Read in a bundle from a filelike object.

    :param f: A file-like object
    :return: A list of Bundle objects
    """
    version = None
    for line in f:
        m = BUNDLE_HEADER_RE.match(line)
        if m:
            if m.group('lineending') != b'':
                raise errors.UnsupportedEOLMarker()
            version = m.group('version')
            break
        elif line.startswith(BUNDLE_HEADER):
            raise errors.MalformedHeader(
                'Extra characters after version number')
        m = CHANGESET_OLD_HEADER_RE.match(line)
        if m:
            version = m.group('version')
            raise errors.BundleNotSupported(version,
                                            'old format bundles not supported')

    if version is None:
        raise errors.NotABundle('Did not find an opening header')

    return get_serializer(version.decode('ascii')).read(f)


def get_serializer(version):
    try:
        serializer = serializer_registry.get(version)
    except KeyError:
        raise errors.BundleNotSupported(version,
                                        'unknown bundle format')

    return serializer(version)


def write(source, revision_ids, f, version=None, forced_bases={}):
    """Serialize a list of bundles to a filelike object.

    :param source: A source for revision information
    :param revision_ids: The list of revision ids to serialize
    :param f: The file to output to
    :param version: [optional] target serialization version
    """

    with source.lock_read():
        return get_serializer(version).write(source, revision_ids,
                                             forced_bases, f)


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
        return get_serializer(format).write_bundle(repository, revision_id,
                                                   base_revision_id, out)


class BundleSerializer(object):
    """The base class for Serializers.

    Common functionality should be included here.
    """

    def __init__(self, version):
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
    temp = BytesIO()
    internal_diff(old_filename, old_lines, new_filename, new_lines, temp,
                  allow_binary=True)
    temp.seek(0)
    base64.encode(temp, to_file)
    to_file.write(b'\n')


serializer_registry.register_lazy(
    '0.8', __name__ + '.v08', 'BundleSerializerV08')
serializer_registry.register_lazy(
    '0.9', __name__ + '.v09', 'BundleSerializerV09')
serializer_registry.register_lazy('4', __name__ + '.v4',
                                  'BundleSerializerV4')
serializer_registry.default_key = '4'
