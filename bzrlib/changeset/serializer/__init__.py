# (C) 2005 Canonical Development Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Serializer factory for reading and writing changesets.
"""

import re

import bzrlib.errors as errors

# New changesets should try to use this header format
CHANGESET_HEADER = '# Bazaar changeset v'
CHANGESET_HEADER_RE = re.compile(r'^# Bazaar changeset v(?P<version>\d+[\w.]*)\n$')
CHANGESET_OLD_HEADER_RE = re.compile(r'^# Bazaar-NG changeset v(?P<version>\d+[\w.]*)\n$')


_serializers = {} 


def _get_filename(f):
    if hasattr(f, 'name'):
        return f.name
    return '<unknown>'


def read(f):
    """Read in a changeset from a filelike object.

    :param f: A file-like object
    :return: A list of Changeset objects
    """
    version = None
    for line in f:
        m = CHANGESET_HEADER_RE.match(line)
        if m:
            version = m.group('version')
            break
        m = CHANGESET_OLD_HEADER_RE.match(line)
        if m:
            version = m.group('version')
            raise errors.ChangesetNotSupported(version, 'old format changesets not supported')

    if version is None:
        raise errors.NoChangesetFound(_get_filename(f))

    # Now we have a version, to figure out how to read the changeset
    if not _serializers.has_key(version):
        raise errors.ChangesetNotSupported(version, 'version not listed in known versions')

    serializer = _serializers[version](version)

    return serializer.read(f)


def write(csets, f, version=None):
    """Serialize a list of changesets to a filelike object.

    :param csets: The list of changesets to serialize
    :param f: The file to output to
    :param version: [optional] target serialization version
    """

    if not _serializers.has_key(version):
        raise errors.ChangesetNotSupported(version, 'unknown changeset format')

    serializer = serializer[version](version)
    return serializer.write(csets, f) 


def ChangesetSerializer(object):
    """The base class for Serializers.

    Common functionality should be included here.
    """
    def __init__(self, version):
        self.version = version

    def read(self, f):
        """Read the rest of the changesets from the supplied file.

        :param f: The file to read from
        :return: A list of changesets
        """
        raise NotImplementedError

    def write(self, csets, f):
        """Write the changesets to the supplied files.

        :param csets: A list of changesets to be serialized
        :param f: The file to write to
        """

def register(version, klass, overwrite=False):
    """Register a ChangesetSerializer version.

    :param version: The version associated with this format
    :param klass: The class to instantiate, which must take a version argument
    """
    global _serializers
    if overwrite:
        _serializers[version] = klass
        return

    if not _serializers.has_key(version):
        _serializers[version] = klass


def register_lazy(version, module, classname, overwrite=False):
    """Register lazy-loaded changeset serializer.

    :param version: The version associated with this reader
    :param module: String indicating what module should be loaded
    :param classname: Name of the class that will be instantiated
    :param overwrite: Should this version override a default
    """
    def _loader(version):
        mod = __import__(module, globals(), locals(), [classname])
        klass = getattr(mod, classname)
        return klass(version)
    register(scheme, _loader, overwrite=overwrite)


register_lazy('0.6', 'bzrlib.changeset.serializer.v06', 'ChangesetSerializerV06')

