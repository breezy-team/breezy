"""Classify a commit based on the types of files it changed."""

from bzrlib import urlutils 
from bzrlib.trace import mutter


def classify_filename(name):
    """Classify a file based on its name.
    
    :param name: File path.
    :return: One of code, documentation, translation or art. 
        None if determining the file type failed.
    """
    # FIXME: Use mime types? Ohcount? 
    basename = urlutils.basename(name)
    try:
        extension = basename.split(".")[1]
        if extension in ("c", "h", "py", "cpp", "rb", "ac"):
            return "code"
        if extension in ("html", "xml", "txt", "rst", "TODO"):
            return "documentation"
        if extension in ("po"):
            return "translation"
        if extension in ("svg", "png", "jpg"):
            return "art"
    except IndexError:
        if basename in ("README", "NEWS", "TODO", 
                        "AUTHORS", "COPYING"):
            return "documentation"
        if basename in ("Makefile"):
            return "code"

    mutter("don't know how to classify %s", name)
    return None


def classify_delta(delta):
    """Determine what sort of changes a delta contains.

    :param delta: A TreeDelta to inspect
    :return: List with classes found (see classify_filename)
    """
    # TODO: This is inaccurate, since it doesn't look at the 
    # number of lines changed in a file.
    types = []
    for d in delta.added + delta.modified:
        types.append(classify_filename(d[0]))
    return types
