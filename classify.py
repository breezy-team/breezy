"""Classify a commit based on the types of files it changed."""

from bzrlib import urlutils 

def classify_filename(name):
    """Classify a file based on its name.
    
    :param name: File path.
    :return: One of code, documentation, translation or art. 
        None if determining the file type failed.
    """
    # FIXME: Use mime types?
    basename = urlutils.basename(name)
    try:
        extension = basename.split(".")[1]
        if extension in ("c", "py", "cpp", "rb"):
            return "code"
        if extension in ("html", "xml", "txt", "rst"):
            return "documentation"
        if extension in ("po"):
            return "translation"
        if extension in ("svg", "png", "jpg"):
            return "art"
    except IndexError:
        if basename in ("README", "NEWS", "TODO"):
            return "documentation"

    return None

def classify_delta(delta):
    types = []
    for d in delta.added + delta.modified:
        types.append(classify_filename(d[0]))
    return types
