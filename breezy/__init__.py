# Copyright (C) 2005-2013, 2016, 2017 Canonical Ltd
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

"""All of Breezy.

Developer documentation is available at
https://www.breezy-vcs.org/developers/.

Some particularly interesting things in breezy are:

* breezy.initialize -- setup the library for use
* breezy.plugin.load_plugins -- load all installed plugins
* breezy.branch.Branch.open -- open a branch
* breezy.workingtree.WorkingTree.open -- open a working tree

We hope you enjoy this library.
"""

import time

# Keep track of when breezy was first imported, so that we can give rough
# timestamps relative to program start in the log file kept by breezy.trace.
_start_time = time.time()

import codecs
import sys

__copyright__ = (
    "Copyright 2005-2012 Canonical Ltd.\nCopyright 2017-2025 Breezy developers"
)

# same format as sys.version_info: "A tuple containing the five components of
# the version number: major, minor, micro, releaselevel, and serial. All
# values except releaselevel are integers; the release level is 'alpha',
# 'beta', 'candidate', or 'final'. The version_info value corresponding to the
# Python version 2.0 is (2, 0, 0, 'final', 0)."  Additionally we use a
# releaselevel of 'dev' for unreleased under-development code.

version_info = (3, 3, 12, "dev", 0)


def _format_version_tuple(version_info):
    """Turn a version number 2, 3 or 5-tuple into a short string.

    This format matches <http://docs.python.org/dist/meta-data.html>
    and the typical presentation used in Python output.

    This also checks that the version is reasonable: the sub-release must be
    zero for final releases.

    >>> print(_format_version_tuple((1, 0, 0, 'final', 0)))
    1.0.0
    >>> print(_format_version_tuple((1, 2, 0, 'dev', 0)))
    1.2.0.dev
    >>> print(_format_version_tuple((1, 2, 0, 'dev', 1)))
    1.2.0.dev1
    >>> print(_format_version_tuple((1, 1, 1, 'candidate', 2)))
    1.1.1.rc2
    >>> print(_format_version_tuple((2, 1, 0, 'beta', 1)))
    2.1.b1
    >>> print(_format_version_tuple((1, 4, 0)))
    1.4.0
    >>> print(_format_version_tuple((1, 4)))
    1.4
    >>> print(_format_version_tuple((2, 1, 0, 'final', 42)))
    2.1.0.42
    >>> print(_format_version_tuple((1, 4, 0, 'wibble', 0)))
    1.4.0.wibble.0
    """
    if len(version_info) == 2:
        main_version = f"{version_info[0]}.{version_info[1]}"
    else:
        main_version = f"{version_info[0]}.{version_info[1]}.{version_info[2]}"
    if len(version_info) <= 3:
        return main_version

    release_type = version_info[3]
    sub = version_info[4]

    if release_type == "final" and sub == 0:
        sub_string = ""
    elif release_type == "final":
        sub_string = "." + str(sub)
    elif release_type == "dev" and sub == 0:
        sub_string = ".dev"
    elif release_type == "dev":
        sub_string = ".dev" + str(sub)
    elif release_type in ("alpha", "beta"):
        if version_info[2] == 0:
            main_version = f"{version_info[0]}.{version_info[1]}"
        sub_string = "." + release_type[0] + str(sub)
    elif release_type == "candidate":
        sub_string = ".rc" + str(sub)
    else:
        return ".".join(map(str, version_info))

    return main_version + sub_string


__version__ = _format_version_tuple(version_info)
version_string = __version__
_core_version_string = ".".join(map(str, version_info[:3]))


def _patch_filesystem_default_encoding(new_enc):
    """Change the Python process global encoding for filesystem names.

    The effect is to change how open() and other builtin functions handle
    unicode filenames on posix systems. This should only be done near startup.

    The new encoding string passed to this function must survive until process
    termination, otherwise the interpreter may access uninitialized memory.
    The use of intern() may defer breakage is but is not enough, the string
    object should be secure against module reloading and during teardown.
    """
    try:
        import ctypes

        pythonapi = getattr(ctypes, "pythonapi", None)
        if pythonapi is not None:
            old_ptr = ctypes.c_void_p.in_dll(pythonapi, "Py_FileSystemDefaultEncoding")
            has_enc = ctypes.c_int.in_dll(pythonapi, "Py_HasFileSystemDefaultEncoding")
            as_utf8 = ctypes.PYFUNCTYPE(
                ctypes.POINTER(ctypes.c_char), ctypes.py_object
            )(("PyUnicode_AsUTF8", pythonapi))
    except (ImportError, ValueError):
        return  # No ctypes or not CPython implementation, do nothing
    new_enc = sys.intern(new_enc)
    enc_ptr = as_utf8(new_enc)
    has_enc.value = 1
    old_ptr.value = ctypes.cast(enc_ptr, ctypes.c_void_p).value
    if sys.getfilesystemencoding() != new_enc:
        raise RuntimeError("Failed to change the filesystem default encoding")
    return new_enc


# When running under the brz script, override bad filesystem default encoding.
# This is not safe to do for all users of breezy, other scripts should instead
# just ensure a usable locale is set via the $LANG variable on posix systems.
_fs_enc = sys.getfilesystemencoding()
if getattr(sys, "_brz_default_fs_enc", None) is not None:
    if _fs_enc is None or codecs.lookup(_fs_enc).name == "ascii":
        _fs_enc = _patch_filesystem_default_encoding(sys._brz_default_fs_enc)  # type: ignore
if _fs_enc is None:
    _fs_enc = "ascii"
else:
    _fs_enc = codecs.lookup(_fs_enc).name


# brz has various bits of global state that are slowly being eliminated.
# This variable is intended to permit any new state-like things to be attached
# to a library_state.BzrLibraryState object rather than getting new global
# variables that need to be hunted down. Accessing the current BzrLibraryState
# through this variable is not encouraged: it is better to pass it around as
# part of the context of an operation than to look it up directly, but when
# that is too hard, it is better to use this variable than to make a brand new
# global variable.
# If using this variable by looking it up (because it can't be easily obtained)
# it is important to store the reference you get, rather than looking it up
# repeatedly; that way your code will behave properly in the breezy test suite
# and from programs that do use multiple library contexts.
_global_state = None


def initialize(setup_ui=True, stdin=None, stdout=None, stderr=None):
    """Set up everything needed for normal use of breezy.

    Most applications that embed breezy, including brz itself, should call
    this function to initialize various subsystems.

    More options may be added in future so callers should use named arguments.

    The object returned by this function can be used as a contex manager
    through the 'with' statement to automatically shut down when the process
    is finished with breezy.  However it's not necessary to
    separately enter the context as well as starting brz: breezy is ready to
    go when this function returns.

    :param setup_ui: If true (default) use a terminal UI; otherwise
        some other ui_factory must be assigned to `breezy.ui.ui_factory` by
        the caller.
    :param stdin, stdout, stderr: If provided, use these for terminal IO;
        otherwise use the files in `sys`.
    :return: A context manager for the use of breezy. The __exit__
        should be called by the caller before exiting their process or
        otherwise stopping use of breezy. Advanced callers can use
        BzrLibraryState directly.
    """
    from breezy import library_state, trace

    if setup_ui:
        import breezy.ui

        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        stderr = stderr or sys.stderr
        ui_factory = breezy.ui.make_ui_for_terminal(stdin, stdout, stderr)
    else:
        ui_factory = None
    tracer = trace.DefaultConfig()
    state = library_state.BzrLibraryState(ui=ui_factory, trace=tracer)
    # Start automatically in case people don't realize this returns a context.
    state._start()
    return state


def get_global_state():
    if _global_state is None:
        return initialize()
    return _global_state


def test_suite():
    import tests

    return tests.test_suite()
