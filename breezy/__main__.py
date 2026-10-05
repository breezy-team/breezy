# Copyright (C) 2005-2013, 2016, 2017 Canonical Ltd
# Copyright (C) 2018-2020 Breezy Developers
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

"""Breezy -- a free distributed version-control tool."""

import os
import sys

profiling = False
if "--profile-imports" in sys.argv:
    import profile_imports

    profile_imports.install()
    profiling = True


if os.name == "posix":
    import locale

    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error as e:
        sys.stderr.write(
            "brz: warning: {}\n"
            "  bzr could not set the application locale.\n"
            "  Although this should be no problem for bzr itself, it might\n"
            "  cause problems with some plugins. To investigate the issue,\n"
            "  look at the output of the locale(1p) tool.\n".format(e)
        )
    # Use better default than ascii with posix filesystems that deal in bytes
    # natively even when the C locale or no locale at all is given. Note that
    # we need an immortal string for the hack, hence the lack of a hyphen.
    sys._brz_default_fs_enc = "utf8"  # type: ignore


def main():
    """Main entry point for the Breezy command-line interface.

    Runs the command given in ``sys.argv`` inside a ``breezy.initialize``
    context. This never returns normally: the process is ended abruptly with
    ``os._exit``, as the ``brz`` binary does.
    """
    from breezy._cmd_rs import run_main

    run_main(profiling)


if __name__ == "__main__":
    main()
