#!/usr/bin/env python

# Author: David Goodger
# Contact: goodger@python.org
# Revision: $Revision: 3901 $
# Date: $Date: 2005-09-25 17:49:54 +0200 (Sun, 25 Sep 2005) $
# Copyright: This module has been placed in the public domain.

"""
A minimal front end to the Docutils Publisher, producing HTML.
"""

try:
    import locale
    locale.setlocale(locale.LC_ALL, '')
except:
    pass

from docutils.core import publish_cmdline, default_description


description = ('Generates (X)HTML documents from standalone reStructuredText '
               'sources.  ' + default_description)


# workaround for bug with <xxx id="tags" name="tags"> in IE
from docutils.writers import html4css1

class IESafeHtmlTranslator(html4css1.HTMLTranslator):

    def starttag(self, node, tagname, suffix='\n', empty=0, **attributes):
        x = html4css1.HTMLTranslator.starttag(self, node, tagname, suffix,
                                              empty, **attributes)
        y = x.replace('id="tags"', 'id="tags_"')
        y = y.replace('name="tags"', 'name="tags_"')
        y = y.replace('href="#tags"', 'href="#tags_"')
        return y

mywriter = html4css1.Writer()
mywriter.translator_class = IESafeHtmlTranslator


publish_cmdline(writer=mywriter, description=description)
