#!/usr/bin/env python3
"""Convert reStructuredText to pretty HTML using Kid templates.

This tool converts reStructuredText files to HTML using docutils and then
applies Kid templating to create attractive, formatted HTML output. It requires
docutils, ElementTree, and Kid dependencies.
"""

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
    """Convert reStructuredText to HTML using a Kid template.

    Args:
        rest_file: File object containing reStructuredText content.
        template_name: Path to the Kid template file to use.

    Returns:
        HTML string generated from the template.

    Raises:
        AssertionError: If the generated HTML lacks head or body elements.
    """
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
    """Safely open a file with error handling.

    Args:
        filename: Path to the file to open.
        mode: File mode ('r' or 'w').

    Returns:
        File object opened in binary mode.

    Raises:
        SystemExit: If the file is not found.
    """
    try:
        return open(filename, mode + "b")
    except FileNotFoundError:
        sys.stderr.write(f"file not found: {sys.argv[2]}\n")
        sys.exit(3)


def main(template, source=None, target=None):
    """Main entry point for the RST to HTML converter.

    Args:
        template: Path to the Kid template file.
        source: Input file path (defaults to stdin if None).
        target: Output file path (defaults to stdout if None).
    """
    rest_file = safe_open(source, "r") if source is not None else sys.stdin
    out_file = safe_open(target, "w") if target is not None else sys.stdout
    out_file.write(kidified_rest(rest_file, template))


if len(sys.argv) <= 1:
    print("Usage: rst2prettyhtml.py <template> [source] [target]")
    sys.exit(2)

# Strip options so only the arguments are passed
args = [x for x in sys.argv[1:] if not x.startswith("-")]
main(*args)
