import os
import popen2
"""
Diff and patch functionality
"""
__docformat__ = "restructuredtext"

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
    process = popen2.Popen3(args, bufsize=len(patch_contents))
    process.tochild.write(patch_contents)
    process.tochild.close()
    status = os.WEXITSTATUS(process.wait())
    return status 


def diff(orig_file, mod_str, orig_label=None, mod_label=None):
    """Compare two files, and produce a patch.

    :param orig_file: path to the old file
    :type orig_file: str
    :param mod_str: Contents of the new file
    :type mod_str: str
    :param orig_label: The label to use for the old file
    :type orig_label: str
    :param mod_label: The label to use for the new file
    :type mod_label: str
    """
    args = ["diff", "-u" ]
    if orig_label is not None and mod_label is not None:
        args.extend(("-L", orig_label, "-L", mod_label))
    args.extend(("--", orig_file, "-"))
    process = popen2.Popen3(args, bufsize=len(mod_str))
    process.tochild.write(mod_str)
    process.tochild.close()
    patch = process.fromchild.read()
    status = os.WEXITSTATUS(process.wait())
    if status == 0:
        return None
    else:
        return patch

def diff3(out_file, mine_path, older_path, yours_path):
    def add_label(args, label):
        args.extend(("-L", label))
    args = ['diff3', "-E", "--merge"]
    add_label(args, "TREE")
    add_label(args, "ANCESTOR")
    add_label(args, "MERGE-SOURCE")
    args.extend((mine_path, older_path, yours_path))
    process = popen2.Popen4(args)
    process.tochild.close()
    output = process.fromchild.read()
    status = os.WEXITSTATUS(process.wait())
    if status not in (0, 1):
        raise Exception(output)
    file(out_file, "wb").write(output)
    return status
