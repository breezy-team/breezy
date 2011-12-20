#    quilt.py -- Quilt patch handling
#    Copyright (C) 2011 Canonical Ltd.
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
#

"""Quilt patch handling."""

from __future__ import absolute_import

import errno
import os
import signal
import subprocess
import tempfile
from bzrlib import (
    errors,
    trace,
    )


class QuiltError(errors.BzrError):

    _fmt = "An error occurred running quilt: %(msg)s"

    def __init__(self, msg):
        self.msg = msg


def run_quilt(args, working_dir, series_file=None, patches_dir=None, quiet=None):
    """Run quilt.

    :param args: Arguments to quilt
    :param working_dir: Working dir
    :param series_file: Optional path to the series file
    :param patches_dir: Optional path to the patches
    :param quilt: Whether to be quiet (quilt stderr not to terminal)
    :raise QuiltError: When running quilt fails
    """
    def subprocess_setup():
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    env = {}
    if patches_dir is not None:
        env["QUILT_PATCHES"] = patches_dir
    else:
        env["QUILT_PATCHES"] = os.path.join(working_dir, "debian", "patches")
    if series_file is not None:
        env["QUILT_SERIES"] = series_file
    else:
        env["QUILT_SERIES"] = os.path.join(env["QUILT_PATCHES"], "series")
    # Hide output if -q is in use.
    if quiet is None:
        quiet = trace.is_quiet()
    if quiet:
        kwargs = {"stderr": subprocess.STDOUT, "stdout": subprocess.PIPE}
    else:
        kwargs = {}
    command = ["quilt"] + args
    trace.mutter("running: %r", command)
    try:
        proc = subprocess.Popen(command, cwd=working_dir,
                stdin=subprocess.PIPE, preexec_fn=subprocess_setup, **kwargs)
    except OSError, e:
        if e.errno != errno.ENOENT:
            raise
        raise errors.BzrError("quilt is not installed, please install it")
    output = proc.communicate()
    if proc.returncode not in (0, 2):
        raise QuiltError(output)


def quilt_pop_all(working_dir, patches_dir=None, series_file=None, quiet=None):
    """Pop all patches.

    :param working_dir: Directory to work in
    :param patches_dir: Optional patches directory
    :param series_file: Optional series file
    """
    return run_quilt(["pop", "-a", "-v"], working_dir=working_dir, quiet=quiet)


def tree_unapply_patches(orig_tree):
    """Return a tree with patches unapplied.

    :param tree: Tree from which to unapply quilt patches
    :return: Tuple with tree and temp path.
        The tree is a tree with unapplied patches; either a checkout of
        tree or tree itself if there were no patches
    """
    series_file_id = orig_tree.path2id("debian/patches/series")
    if series_file_id is None:
        # No quilt patches
        return orig_tree, None

    target_dir = tempfile.mkdtemp()
    tree = orig_tree.branch.create_checkout(target_dir, lightweight=True)
    trace.warning("Applying quilt patches for %r in %s", orig_tree, target_dir)
    quilt_pull_all(working_dir=tree.basedir)
    return tree, target_dir
