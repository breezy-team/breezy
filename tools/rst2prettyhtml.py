#!/usr/bin/env python3

import sys
from io import StringIO

try:
    from docutils.core import publish_file
    from docutils.parsers import rst  # noqa: F401
except ModuleNotFoundError:
    print("Missing dependency.  Please install docutils.")
    sys.exit(1)
try:
    from elementtree import HTMLTreeBuilder
    from elementtree.ElementTree import XML  # noqa: F401
except ModuleNotFoundError:
    print("Missing dependency.  Please install ElementTree.")
    sys.exit(1)
try:
    import kid
except ModuleNotFoundError:
    print("Missing dependency.  Please install Kid.")
    sys.exit(1)


def kidified_rest(rest_file, template_name):
    xhtml_file = StringIO()
    # prevent docutils from autoclosing the StringIO
    xhtml_file.close = lambda: None
    publish_file(
        rest_file,
        writer_name="html",
        destination=xhtml_file,
        settings_overrides={"doctitle_xform": 0},
    )
    xhtml_file.seek(0)
    xml = HTMLTreeBuilder.parse(xhtml_file)
    head = xml.find("head")
    body = xml.find("body")
    if head is None:
        raise AssertionError("No head found in the document")
    if body is None:
        raise AssertionError("No body found in the document")
    template = kid.Template(file=template_name, head=head, body=body)
    return template.serialize(output="html")


def safe_open(filename, mode):
    try:
        return open(filename, mode + "b")
    except FileNotFoundError:
        sys.stderr.write(f"file not found: {sys.argv[2]}\n")
        sys.exit(3)


def main(template, source=None, target=None):
    rest_file = safe_open(source, "r") if source is not None else sys.stdin
    out_file = safe_open(target, "w") if target is not None else sys.stdout
    out_file.write(kidified_rest(rest_file, template))


if len(sys.argv) <= 1:
    print("Usage: rst2prettyhtml.py <template> [source] [target]")
    sys.exit(2)

# Strip options so only the arguments are passed
args = [x for x in sys.argv[1:] if not x.startswith("-")]
main(*args)
