# Copyright (C) 2010 Canonical Ltd
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

"""sphinx texinfo writer tests."""

from bzrlib import tests
from bzrlib.tests import (
    doc_generate as test_dg, # Avoid clash with from bzrlib import doc_generate
    )


class TestTextGeneration(test_dg.TestSphinx):

    def test_special_chars(self):
        self.create_content("A '@' a '{' and a '}'")
        self.assertContent("A '@@' a '@{' and a '@}'")

    def test_emphasis(self):
        self.create_content('*important*')
        self.assertContent('@emph{important}')

    def test_strong(self):
        self.create_content('**very important**')
        self.assertContent('@strong{very important}')

    def test_literal(self):
        self.create_content('the command is ``foo``')
        self.assertContent('the command is @code{foo}')

    def test_paragraphs(self):
        self.create_content('''\
This is a paragraph.

This is another one.
''')
        self.assertContent('''\
This is a paragraph.

This is another one.''')

    def test_literal_block(self):
        self.create_content('''\
Do this::

   bzr xxx
   bzr yyy
''')
        self.assertContent('''\
Do this:

@samp{bzr xxx
bzr yyy}

''',
                           end='')

    def test_block_quote(self):
        self.create_content('''\
This is an ordinary paragraph, introducing a block quote.

    "It is my business to know things.  That is my trade."

This is another ordinary paragraph.
''')
        self.assertContent('''\
This is an ordinary paragraph, introducing a block quote.

@example
"It is my business to know things.  That is my trade."

@end example

This is another ordinary paragraph.

''',
                           # examples are not followed by an empty line
                           end='')


class TestDocumentAttributesGeneration(test_dg.TestSphinx):

    def test_title(self):
        self.create_content('''\
####################
Bazaar Release Notes
####################
''')
        self.assertContent('''\
@node bazaar-release-notes
@chapter Bazaar Release Notes
''',
                           end='')


class TestListGeneration(test_dg.TestSphinx):

    def test_bullet_list(self):
        self.create_content('''\
* This is a bulleted list.
* It has two items, the second
  item uses two lines.
''')
        self.assertContent('''\
@itemize @bullet
@item
This is a bulleted list.

@item
It has two items, the second
item uses two lines.

@end itemize
''',
                           end='')

    def test_enumerated_list(self):
        self.create_content('''\
#. This is a numbered list.
#. It has two items, the second
   item uses two lines.
''')
        self.assertContent('''\
@enumerate
@item
This is a numbered list.

@item
It has two items, the second
item uses two lines.

@end enumerate
''',
                           end='')


class TestTableGeneration(test_dg.TestSphinx):

    def test_table(self):
        self.create_content('''\
  ===========         ================
  Prefix              Description
  ===========         ================
  first               The first
  second              The second
  last                The last
  ===========         ================
''')
        # FIXME: Sphinx bug ? Why are tables enclosed in a block_quote
        # (translated as an @example).
        self.assertContent('''\
@example
@multitable {xxxxxxxxxxx}{xxxxxxxxxxxxxxxx}
@headitem Prefix @tab Description
@item first
@tab The first
@item second
@tab The second
@item last
@tab The last
@end multitable
@end example''')


class TestTocTreeGeneration(test_dg.TestSphinx):

    def test_toctree(self):
        if self.sphinx_version() >= (1, 0):
            raise tests.TestSkipped('Not compatible with sphinx >= 1.0')
        self.build_tree_contents(
            [('index.txt', """
Table of Contents
=================

.. toctree::
   :maxdepth: 1

   bzr 0.0.8 <bzr-0.0.8>
"""),
             ('bzr-0.0.8.txt', """

bzr 0.0.8
*********

Improvements
============

* Adding a file whose parent directory is not versioned will
  implicitly add the parent, and so on up to the root.
"""),
             ])
        app, out, err = self.make_sphinx()
        self.build(app)
        self.assertFileEqual("""\
This file has been converted using a beta rst->texinfo converter. 
Most of the info links are currently bogus, don't report bugs about them,
this is currently worked on.
@node Top
@top Placeholder
@node table-of-contents
@chapter Table of Contents
@menu
* bzr 0.0.8: (bzr-0.0.8.info)bzr 0.0.8. 
@end menu
""",
                             'index.texi')
        self.assertFileEqual("""\
This file has been converted using a beta rst->texinfo converter. 
Most of the info links are currently bogus, don't report bugs about them,
this is currently worked on.
@node Top
@top Placeholder
@node bzr-0-0-8
@chapter bzr 0.0.8
@node improvements
@section Improvements
@itemize @bullet
@item
Adding a file whose parent directory is not versioned will
implicitly add the parent, and so on up to the root.

@end itemize
""",
                             'bzr-0.0.8.texi')

class TestSections(test_dg.TestSphinx):

    def test_sections(self):
        self.create_content('''\
###########
Chapter one
###########

Chapter introduction.

***********
section one
***********

The first section.


subsection one
==============

The first subsection.

subsection two
==============

The second subsection.

subsubsection one
-----------------

Here is sus sub section one.

blob one
^^^^^^^^

Far tooo deep to get a name

thing one
"""""""""

No idea how to call that, but sphinx says it's a paragraph.
''')
        self.assertContent('''\
@node chapter-one
@chapter Chapter one
Chapter introduction.

@node section-one
@section section one
The first section.

@node subsection-one
@subsection subsection one
The first subsection.

@node subsection-two
@subsection subsection two
The second subsection.

@node subsubsection-one
@subsubsection subsubsection one
Here is sus sub section one.

@node blob-one
@heading blob one
Far tooo deep to get a name

@node thing-one
@heading thing one
No idea how to call that, but sphinx says it's a paragraph.''')


class TestReferences(test_dg.TestSphinx):

    def test_external_reference(self):
        self.create_content('''\
The `example web site`_ is nice.

.. _example web site: http://www.example.com/
''')
        self.assertContent('''\
The @uref{http://www.example.com/,example web site} is nice.''')


    def test_internal_reference(self):
        self.create_content('''\
The `example web site`_ contains more examples.

Example web site
----------------

Here we have a lot of nice examples.

''')
        self.assertContent('''\
The example web site (@pxref{example-web-site}) contains more examples.

@node example-web-site
@chapter Example web site
Here we have a lot of nice examples.''')

