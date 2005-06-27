#! /usr/bin/python

# Copyright (C) 2005 Canonical Ltd

# GNU GPL v2

# Author: Martin Pool <mbp@canonical.com>


"""knit - a weave-like structure

A Knit manages versions of line-based text files, keeping track of the
originating version for each line.

Versions are referenced by nonnegative integers.  In a full system
this will be just a local shorthand for some universally-unique
version identifier.

Texts are represented as a seqence of (version, text, live) tuples.
An empty sequence represents an empty text.  The version is the
version in which the line was introduced.  The *live* flag is false if
the line is no longer present and being tracked only for the purposes
of merging.
"""


text1 = [(0, "hello world", True)]

knit2 = [(0, "hello world", True),
         (1, "hello boys", True)
         ]



def show_annotated(knit):
    """Show a knit in 'blame' style"""
    for vers, text, live in knit:
        if not live:
            continue
        print '%6d | %s' % (vers, text)


def knit2text(knit):
    """Return a sequence of lines containing just the live text from a knit."""
    return [text for (vers, text, live) in knit if live]



def update_knit(knit, new_vers, new_lines):
    """Return a new knit whose text matches new_lines.

    First of all the knit is diffed against the new lines, considering
    only the text of the lines from the knit.  This identifies lines
    unchanged from the knit, plus insertions and deletions.

    The deletions are marked as deleted.  The insertions are added
    with their new values.

    
    """
    if not isinstance(new_vers, int):
        raise TypeError('new version-id must be an int: %r' % new_vers)
    
    from difflib import SequenceMatcher
    knit_lines = knit2text(knit)
    m = SequenceMatcher(None, knit_lines, new_lines)

    for block in m.get_matching_blocks():
        print "a[%d] and b[%d] match for %d elements" % block
    
    new_knit = []
    for tag, i1, i2, j1, j2 in m.get_opcodes():
        print ("%7s a[%d:%d] (%s) b[%d:%d] (%s)" %
               (tag, i1, i2, knit_lines[i1:i2], j1, j2, new_lines[j1:j2]))

        if tag == 'equal':
            new_knit.extend(knit[i1:i2])
        elif tag == 'delete':
            for i in range(i1, i2):
                kl = knit[i]
                new_knit.append((kl[0], kl[1], False))

    return new_knit
        
    


print '***** annotated:'
show_annotated(knit2)

print '***** plain text:'
print '\n'.join(knit2text(knit2))

text3 = """hello world
an inserted line
hello boys""".split('\n')

print repr(knit2text(knit2))
print repr(text3)
knit3 = update_knit(knit2, 3, text3)

print '***** result of update:'
show_annotated(knit3)



