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

class TestBuilderLoaded(TestSphinx):

    def test_builder_loaded(self):
        app, out, err = self.make_sphinx()
        self.assertTrue('texinfo' in app.builderclasses)


class TestTextGeneration(TestSphinx):

    # FIXME: something smells wrong here as we can't process a single file
    # alone. On top of that, it seems the doc tree must contain an index.txt
    # file. We may need a texinfo builder ? -- vila 20100505

    def test_special_chars(self):
        self.build_tree_contents([('index.txt', """A '@' a '{' and a '}'"""),])
        app, out, err = self.make_sphinx()
        app.build(True, [])
        # Note that since the input is a paragraph, we get two \n (even if the
        # input has none)
        self.assertFileEqual("""A '@@' a '@{' and a '@}'\n\n""", 'index.texi')

    def test_emphasis(self):
        self.build_tree_contents([('index.txt', """*important*"""),])
        app, out, err = self.make_sphinx()
        app.build(True, [])
        # Note that since the input is a paragraph, we get two \n (even if the
        # input has none)
        self.assertFileEqual("""@emph{important}\n\n""", 'index.texi')

    def test_strong(self):
        self.build_tree_contents([('index.txt', """**very important**"""),])
        app, out, err = self.make_sphinx()
        app.build(True, [])
        # Note that since the input is a paragraph, we get two \n (even if the
        # input has none)
        self.assertFileEqual("""@strong{very important}\n\n""", 'index.texi')

    def test_literal(self):
        self.build_tree_contents([('index.txt', """the command is ``foo``"""),])
        app, out, err = self.make_sphinx()
        app.build(True, [])
        # Note that since the input is a paragraph, we get two \n (even if the
        # input has none)
        self.assertFileEqual("""the command is @code{foo}\n\n""", 'index.texi')

    def test_paragraphs(self):
        self.build_tree_contents([('index.txt', """\
This is a paragraph.

This is another one.
"""),])
        app, out, err = self.make_sphinx()
        app.build(True, [])
        self.assertFileEqual("""\
This is a paragraph.

This is another one.

""",
                             'index.texi')

    def test_literal_block(self):
        self.build_tree_contents([('index.txt', """\
Do this::

   bzr xxx
   bzr yyy
"""),])
        app, out, err = self.make_sphinx()
        app.build(True, [])
        self.assertFileEqual("""\
Do this:

@samp{bzr xxx
bzr yyy}

""",
                             'index.texi')

    def test_block_quote(self):
        self.build_tree_contents([('index.txt', """\
This is an ordinary paragraph, introducing a block quote.

    "It is my business to know things.  That is my trade."

"""),])
        app, out, err = self.make_sphinx()
        app.build(True, [])
        self.assertFileEqual("""\
This is an ordinary paragraph, introducing a block quote.

@example
"It is my business to know things.  That is my trade."

@end example
""",
                             'index.texi')


class TestDocumentAttributesGeneration(TestSphinx):

    def test_title(self):
        self.build_tree_contents([('index.txt', """\
####################
Bazaar Release Notes
####################
"""),])
        app, out, err = self.make_sphinx()
        app.build(True, [])
        self.assertFileEqual("""@chapter Bazaar Release Notes\n""",
                             'index.texi')


class TestListGeneration(TestSphinx):

    def test_bullet_list(self):
        self.build_tree_contents([('index.txt', """\
* This is a bulleted list.
* It has two items, the second
  item uses two lines.
"""),])
        app, out, err = self.make_sphinx()
        app.build(True, [])
        print err.getvalue()
        self.assertFileEqual("""\
@itemize @bullet
@item
This is a bulleted list.

@item
It has two items, the second
item uses two lines.

@end itemize
""",
                             'index.texi')

    def test_enumerated_list(self):
        self.build_tree_contents([('index.txt', """\
#. This is a numbered list.
#. It has two items, the second
   item uses two lines.
"""),])
        app, out, err = self.make_sphinx()
        app.build(True, [])
        print err.getvalue()
        self.assertFileEqual("""\
@enumerate
@item
This is a numbered list.

@item
It has two items, the second
item uses two lines.

@end enumerate
""",
                             'index.texi')


class TestTableGeneration(TestSphinx):

    def test_table(self):
        self.build_tree_contents([('index.txt', """\
  ===========         ================
  Prefix              Description
  ===========         ================
  first               The first
  second              The second
  last                The last
  ===========         ================
"""),])
        app, out, err = self.make_sphinx()
        app.build(True, [])
        print err.getvalue()
        # FIXME: Sphinx bug ? Why are tables enclosed in a block_quote
        # (translated as an @example).
        self.assertFileEqual("""\
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

@end example
""",
                             'index.texi')


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
        app.build(True, [])
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
        self.build_tree_contents([('index.txt', '''\
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
'''),])
        app, out, err = self.make_sphinx()
        app.build(True, [])
        print err.getvalue()
        self.assertFileEqual("""\
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
No idea how to call that, but sphinx says it's a paragraph.

""",
                             'index.texi')


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
        app.build(True, [])
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

