#    info.py -- Plugin information for bzr-builddeb
#
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

brz_plugin_name = 'debian'

brz_plugin_version = (2, 8, 72, 'final', 0)

brz_commands = [
    "builddeb",
    "merge_upstream",
    "import_dsc",
    "bd_do",
    ]


def versions_dict():
    import breezy
    import debian
    import debmutate
    return {
        'python-debian': debian.__version__,
        'debmutate': debmutate.version_string,
        'breezy': breezy.version_string,
        'breezy-debian': ".".join(
            [str(v) for v in brz_plugin_version[:3]]),
    }
