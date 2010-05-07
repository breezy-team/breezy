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

"""sphinx texinfo builder tests."""

import os
from sphinx import application

from bzrlib import tests
from bzrlib.doc_generate import (
    # FIXME: doc/en/conf.py should be used here, or rather merged into
    # bzrlib/doc_generate/conf.py -- vila 20100429
    conf,
    )
from bzrlib.tests import features


class TestBuilderDefined(tests.TestCase):

    def test_builder_defined(self):
        self.assertTrue('bzrlib.doc_generate.builders.texinfo'
                        in conf.extensions)

class TestSphinx(tests.TestCaseInTempDir):

    def make_sphinx(self):
        out = tests.StringIOWrapper()
        err = tests.StringIOWrapper()
        app = application.Sphinx(
            '.', confdir=os.path.dirname(conf.__file__), outdir='.',
            doctreedir='.',
            buildername='texinfo',
            confoverrides={},
            status=out, warning=err,
            freshenv=True)
        return app, out, err

    def build(self, app, all_files=True, file_names=None):
        if file_names is None:
            file_names = []
        app.build(all_files, file_names)

    # FIXME: something smells wrong here as we can't process a single file
    # alone. On top of that, it seems the doc tree must contain an index.txt
    # file. We may need a texinfo builder ? -- vila 20100505

    def create_content(self, content):
        """Put content into a single file.

        This is appropriate for simple tests about the content of a single file.
        """
        app, out, err = self.make_sphinx()
        self.build_tree_contents([('index.txt', content),])
        self.build(app)

    def assertContent(self, expected, end=None):
        """Check the content of the file created with creste_content().

        Most texinfo constructs can be tested this way without caring for any
        boilerplate that texinfo may require at the beginning or the end of the
        file.
        """
        if end is None:
            # By default we test constructs that are embedded into a paragraph
            # which always end with two \n (even if the input has none)
            end = '\n\n'
        self.assertFileEqual(expected + end, 'index.texi')


class TestBuilderLoaded(TestSphinx):

    def test_builder_loaded(self):
        app, out, err = self.make_sphinx()
        self.assertTrue('texinfo' in app.builderclasses)


class TestTextGeneration(TestSphinx):

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


class TestDocumentAttributesGeneration(TestSphinx):

    def test_title(self):
        self.create_content('''\
####################
Bazaar Release Notes
####################
''')
        self.assertContent('''@chapter Bazaar Release Notes\n''', end='')


class TestListGeneration(TestSphinx):

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


class TestTableGeneration(TestSphinx):

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


class TestTocTreeGeneration(TestSphinx):

    def test_toctree(self):
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
@chapter Table of Contents
@menu
* bzr 0.0.8: (bzr-0.0.8.info)bzr 0.0.8. 
@end menu
""",
                             'index.texi')
        self.assertFileEqual("""\
@chapter bzr 0.0.8
@section Improvements
@itemize @bullet
@item
Adding a file whose parent directory is not versioned will
implicitly add the parent, and so on up to the root.

@end itemize
""",
                             'bzr-0.0.8.texi')

class TestSections(TestSphinx):

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
@chapter Chapter one
Chapter introduction.

@section section one
The first section.

@subsection subsection one
The first subsection.

@subsection subsection two
The second subsection.

@subsubsection subsubsection one
Here is sus sub section one.

@heading blob one
Far tooo deep to get a name

@heading thing one
No idea how to call that, but sphinx says it's a paragraph.''')


class TestFileProduction(TestSphinx):

    def test_files_generated(self):
        self.build_tree_contents(
            [('index.txt', """
Table of Contents
=================

.. toctree::
   :maxdepth: 1

   content
"""),
             ('content.txt', """

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
        self.failUnlessExists('index.texi')
        self.failUnlessExists('content.texi')
        # FIXME: When the content of the files becomes clearer replace the
        # assertion above by the ones below -- vila 20100504
#         self.assertFileEqual("""\
# """,
#                               'content.texi')
#         self.assertFileEqual("""\
# """,
#                               'index.texi')
# 

