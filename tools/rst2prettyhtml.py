#!/usr/bin/env python2.4
import errno
import os
from StringIO import StringIO
import sys

from docutils.core import publish_file
from docutils.parsers import rst
from elementtree.ElementTree import XML
import kid

def kidified_rest(rest_file, template_name):
    xhtml = publish_file(rest_file, writer_name='html', destination=StringIO())
    xml = XML(xhtml)
    head = xml.find('{http://www.w3.org/1999/xhtml}head')
    body = xml.find('{http://www.w3.org/1999/xhtml}body')
    assert head is not None
    assert body is not None
    template=kid.Template(file=template_name, 
                          head=head, body=body)
    return (template.serialize(output="html"))

def safe_open(filename, mode):
    try:
        return open(filename, mode + 'b')
    except IOError, e:
        if e.errno != errno.ENOENT:
            raise
        sys.stderr.write('file not found: %s\n' % sys.argv[2])
        sys.exit(3)
args = sys.argv[1:]

assert len(args) > 0

if len(args) > 1:
    rest_file = safe_open(args[1], 'r')
else:
    rest_file = sys.stdin

if len(args) > 2:
    out_file = safe_open(args[2], 'w')
else:
    out_file = sys.stdout

out_file.write(kidified_rest(rest_file, args[0]))
