# Copyright (C) 2005 Canonical Ltd

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

"""Export functionality, which can take a Tree and create a different representation.

Such as non-controlled directories, tarfiles, zipfiles, etc.
"""

from bzrlib.trace import mutter
import os
import bzrlib.errors as errors

# Maps format name => export function
_exporters = {}
# Maps filename extensions => export format name
_exporter_extensions = {}

def register_exporter(format, extensions, func, override=False):
    """Register an exporter.

    :param format: This is the name of the format, such as 'tgz' or 'zip'
    :param extensions: Extensions which should be used in the case that a 
                       format was not explicitly specified.
    :type extensions: List
    :param func: The function. It will be called with (tree, dest, root)
    :param override: Whether to override an object which already exists.
                     Frequently plugins will want to provide functionality
                     until it shows up in mainline, so the default is False.
    """
    global _exporters, _exporter_extensions

    if not _exporters.has_key(format) or override:
        _exporters[format] = func

    for ext in extensions:
        if not _exporter_extensions.has_key(ext) or override:
            _exporter_extensions[ext] = format


def register_lazy_exporter(scheme, extensions, module, funcname):
    """Register lazy-loaded exporter function.

    When requesting a specific type of export, load the respective path.
    """
    def _loader(tree, dest, root):
        mod = __import__(module, globals(), locals(), [funcname])
        func = getattr(mod, funcname)
        return func(tree, dest, root)
    register_exporter(scheme, extensions, _loader)


def export(tree, dest, format=None, root=None):
    """Export the given Tree to the specific destination.

    :param tree: A Tree (such as RevisionTree) to export
    :param dest: The destination where the files,etc should be put
    :param format: The format (dir, zip, etc), if None, it will check the
                   extension on dest, looking for a match
    :param root: The root location inside the format.
                 It is common practise to have zipfiles and tarballs 
                 extract into a subdirectory, rather than into the
                 current working directory.
                 If root is None, the default root will be
                 selected as the destination without its
                 extension.
    """
    global _exporters, _exporter_extensions

    if format is None:
        for ext in _exporter_extensions:
            if dest.endswith(ext):
                format = _exporter_extensions[ext]
                break

    # Most of the exporters will just have to call
    # this function anyway, so why not do it for them
    if root is None:
        root = get_root_name(dest)

    if not _exporters.has_key(format):
        raise errors.NoSuchExportFormat(format)
    return _exporters[format](tree, dest, root)


def get_root_name(dest):
    """Get just the root name for an export.

    >>> get_root_name('mytar.tar')
    'mytar'
    >>> get_root_name('mytar.tar.bz2')
    'mytar'
    >>> get_root_name('tar.tar.tar.tgz')
    'tar.tar.tar'
    >>> get_root_name('bzr-0.0.5.tar.gz')
    'bzr-0.0.5'
    >>> get_root_name('bzr-0.0.5.zip')
    'bzr-0.0.5'
    >>> get_root_name('bzr-0.0.5')
    'bzr-0.0.5'
    >>> get_root_name('a/long/path/mytar.tgz')
    'mytar'
    >>> get_root_name('../parent/../dir/other.tbz2')
    'other'
    """
    global _exporter_extensions
    dest = os.path.basename(dest)
    for ext in _exporter_extensions:
        if dest.endswith(ext):
            return dest[:-len(ext)]


register_lazy_exporter(None, [], 'bzrlib.export.dir_exporter', 'dir_exporter')
register_lazy_exporter('dir', [], 'bzrlib.export.dir_exporter', 'dir_exporter')
register_lazy_exporter('tar', ['.tar'], 'bzrlib.export.tar_exporter', 'tar_exporter')
register_lazy_exporter('tgz', ['.tar.gz', '.tgz'], 'bzrlib.export.tar_exporter', 'tgz_exporter')
register_lazy_exporter('tbz2', ['.tar.bz2', '.tbz2'], 'bzrlib.export.tar_exporter', 'tbz2_exporter')
register_lazy_exporter('zip', ['.zip'], 'bzrlib.export.zip_exporter', 'zip_exporter')

