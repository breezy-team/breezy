import os
from subprocess import Popen, PIPE
"""
Diff and patch functionality
"""
__docformat__ = "restructuredtext"

def write_to_cmd(args, input=""):
    process = Popen(args, bufsize=len(input), stdin=PIPE, stdout=PIPE,
                    stderr=PIPE, close_fds=True)
    stdout, stderr = process.communicate(input)
    status = process.wait()
    if status < 0:
        raise Exception("%s killed by signal %i" (args[0], -status))
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
    stdout, stderr, status = write_to_cmd(args, patch_contents)
    return status 


def diff3(out_file, mine_path, older_path, yours_path):
    def add_label(args, label):
        args.extend(("-L", label))
    args = ['diff3', "-E", "--merge"]
    add_label(args, "TREE")
    add_label(args, "ANCESTOR")
    add_label(args, "MERGE-SOURCE")
    args.extend((mine_path, older_path, yours_path))
    output, stderr, status = write_to_cmd(args)
    if status not in (0, 1):
        raise Exception(stderr)
    file(out_file, "wb").write(output)
    return status
