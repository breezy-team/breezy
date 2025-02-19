#! /usr/bin/env python

# Originally by Dave Goodger, from the docutils, distribution.
#
# Modified for Bazaar to accommodate options containing dots
#
# This file is in the public domain.

"""A minimal front end to the Docutils Publisher, producing HTML.
"""

try:
    import locale

    locale.setlocale(locale.LC_ALL, "")
except:
    pass

from docutils.core import default_description, publish_cmdline

if True:  # this is still required in the distutils trunk as-at June 2008.
    from docutils.parsers.rst.states import Body

    # we have some option names that contain dot; which is not allowed by
    # python-docutils 0.4-4 -- so monkeypatch in a better pattern
    #
    # This is a bit gross to patch because all this is built up at load time.
    Body.pats["optname"] = r"[a-zA-Z0-9][a-zA-Z0-9._-]*"
    Body.pats["longopt"] = r"(--|/)%(optname)s([ =]%(optarg)s)?" % Body.pats
    Body.pats["option"] = r"(%(shortopt)s|%(longopt)s)" % Body.pats
    Body.patterns["option_marker"] = r"%(option)s(, %(option)s)*(  +| ?$)" % Body.pats


description = (
    "Generates (X)HTML documents from standalone reStructuredText "
    "sources.  " + default_description
)


# workaround for bug with <xxx id="tags" name="tags"> in IE
from docutils.writers import html4css1


class IESafeHtmlTranslator(html4css1.HTMLTranslator):
    def starttag(self, node, tagname, suffix="\n", empty=0, **attributes):
        x = html4css1.HTMLTranslator.starttag(
            self, node, tagname, suffix, empty, **attributes
        )
        y = x.replace('id="tags"', 'id="tags_"')
        y = y.replace('name="tags"', 'name="tags_"')
        y = y.replace('href="#tags"', 'href="#tags_"')
        return y


mywriter = html4css1.Writer()
mywriter.translator_class = IESafeHtmlTranslator


publish_cmdline(writer=mywriter, description=description)
