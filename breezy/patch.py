# Copyright (C) 2005, 2006 Canonical Ltd
# Copyright (C) 2005, 2008 Aaron Bentley, 2006 Michael Ellerman
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

"""Diff and patch functionality."""

import errno
import os
import sys
import tempfile
from subprocess import PIPE, Popen

from .errors import BzrError, NoDiff3
from .textfile import check_text_path


class PatchFailed(BzrError):
    _fmt = """Patch application failed"""


class PatchInvokeError(BzrError):
    _fmt = """Error invoking patch: %(errstr)s%(stderr)s"""
    internal_error = False

    def __init__(self, e, stderr=""):
        self.exception = e
        self.errstr = os.strerror(e.errno)
        self.stderr = "\n" + stderr


_do_close_fds = True
if os.name == "nt":
    _do_close_fds = False


def write_to_cmd(args, input=""):
    """Spawn a process, and wait for the result.

    If the process is killed, an exception is raised

    :param args: The command line, the first entry should be the program name
    :param input: [optional] The text to send the process on stdin
    :return: (stdout, stderr, status)
    """
    process = Popen(
        args,
        bufsize=len(input),
        stdin=PIPE,
        stdout=PIPE,
        stderr=PIPE,
        close_fds=_do_close_fds,
    )
    stdout, stderr = process.communicate(input)
    status = process.wait()
    if status < 0:
        raise Exception(f"{args[0]} killed by signal {-status}")
    return stdout, stderr, status


def patch(patch_contents, filename, output_filename=None, reverse=False):
    """Apply a patch to a file, to produce another output file.  This is should
    be suitable for our limited purposes.

    :param patch_contents: The contents of the patch to apply
    :type patch_contents: str
    :param filename: the name of the file to apply the patch to
    :type filename: str
    :param output_filename: The filename to produce.  If None, file is \
    modified in-place
    :type output_filename: str or NoneType
    :param reverse: If true, apply the patch in reverse
    :type reverse: bool
    :return: 0 on success, 1 if some hunks failed
    """
    args = ["patch", "-f", "-s", "--posix", "--binary"]
    if reverse:
        args.append("--reverse")
    if output_filename is not None:
        args.extend(("-o", output_filename))
    args.append(filename)
    _stdout, _stderr, status = write_to_cmd(args, patch_contents)
    return status


def diff3(out_file, mine_path, older_path, yours_path):
    def add_label(args, label):
        args.extend(("-L", label))

    check_text_path(mine_path)
    check_text_path(older_path)
    check_text_path(yours_path)
    args = ["diff3", "-E", "--merge"]
    add_label(args, "TREE")
    add_label(args, "ANCESTOR")
    add_label(args, "MERGE-SOURCE")
    args.extend((mine_path, older_path, yours_path))
    try:
        output, stderr, status = write_to_cmd(args)
    except OSError as e:
        if e.errno == errno.ENOENT:
            raise NoDiff3
        else:
            raise
    if status not in (0, 1):
        raise Exception(stderr)
    with open(out_file, "wb") as f:
        f.write(output)
    return status


def patch_tree(
    tree, patches, strip=0, reverse=False, dry_run=False, quiet=False, out=None
):
    """Apply a patch to a tree.

    Args:
      tree: A MutableTree object
      patches: list of patches as bytes
      strip: Strip X segments of paths
      reverse: Apply reversal of patch
      dry_run: Dry run
    """
    return run_patch(tree.basedir, patches, strip, reverse, dry_run, quiet, out=out)


def run_patch(
    directory,
    patches,
    strip=0,
    reverse=False,
    dry_run=False,
    quiet=False,
    _patch_cmd="patch",
    target_file=None,
    out=None,
):
    args = [_patch_cmd, "-d", directory, "-s", f"-p{strip}", "-f"]
    if quiet:
        args.append("--quiet")

    if sys.platform == "win32":
        args.append("--binary")

    if reverse:
        args.append("-R")
    if dry_run:
        if sys.platform.startswith("freebsd"):
            args.append("--check")
        else:
            args.append("--dry-run")
        stderr = PIPE
    else:
        stderr = None
    if target_file is not None:
        args.append(target_file)

    try:
        process = Popen(args, stdin=PIPE, stdout=PIPE, stderr=stderr)
    except OSError as e:
        raise PatchInvokeError(e)
    try:
        for patch in patches:
            process.stdin.write(bytes(patch))
        process.stdin.close()

    except OSError as e:
        raise PatchInvokeError(e, process.stderr.read())

    result = process.wait()
    if not dry_run:
        if out is not None:
            out.write(process.stdout.read())
        else:
            process.stdout.read()
    if result != 0:
        raise PatchFailed()

    return result


def iter_patched_from_hunks(orig_lines, hunks):
    """Iterate through a series of lines with a patch applied.
    This handles a single file, and does exact, not fuzzy patching.

    :param orig_lines: The unpatched lines.
    :param hunks: An iterable of Hunk instances.

    This is different from breezy.patches in that it invokes the patch
    command.
    """
    with tempfile.NamedTemporaryFile() as f:
        f.writelines(orig_lines)
        f.flush()
        # TODO(jelmer): Stream patch contents to command, rather than
        # serializing the entire patch upfront.
        serialized = b"".join([hunk.as_bytes() for hunk in hunks])
        args = [
            "patch",
            "-f",
            "-s",
            "--posix",
            "--binary",
            "-o",
            "-",
            f.name,
            "-r",
            "-",
        ]
        stdout, stderr, status = write_to_cmd(args, serialized)
    if status == 0:
        return [stdout]
    raise PatchFailed(stderr)
