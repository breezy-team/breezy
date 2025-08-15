#! /usr/bin/env python

# Originally by Dave Goodger, from the docutils, distribution.
#
# Modified for Bazaar to accommodate options containing dots
#
# This file is in the public domain.

"""A minimal front end to the Docutils Publisher, producing HTML."""

try:
    import locale

    locale.setlocale(locale.LC_ALL, "")
except BaseException:
    pass

from docutils.core import default_description, publish_cmdline

if True:  # this is still required in the distutils trunk as-at June 2008.
    from docutils.parsers.rst.states import Body

    # we have some option names that contain dot; which is not allowed by
    # python-docutils 0.4-4 -- so monkeypatch in a better pattern
    #
    # This is a bit gross to patch because all this is built up at load time.
    Body.pats["optname"] = r"[a-zA-Z0-9][a-zA-Z0-9._-]*"
    Body.pats["longopt"] = r"(--|/){optname}([ =]{optarg})?".format(**Body.pats)
    Body.pats["option"] = r"({shortopt}|{longopt})".format(**Body.pats)
    Body.patterns["option_marker"] = r"{option}(, {option})*(  +| ?$)".format(
        **Body.pats
    )


description = (
    "Generates (X)HTML documents from standalone reStructuredText "
    "sources.  " + default_description
)


# workaround for bug with <xxx id="tags" name="tags"> in IE
from docutils.writers import html4css1


class IESafeHtmlTranslator(html4css1.HTMLTranslator):
    """HTML translator with Internet Explorer compatibility fixes.

    This translator extends the standard HTML4 CSS1 translator to work around
    specific Internet Explorer bugs related to element IDs and names. It ensures
    that problematic ID and name attributes are modified to prevent IE rendering
    issues.
    """

    def starttag(self, node, tagname, suffix="\n", empty=0, **attributes):
        """Generate an HTML start tag with IE-safe modifications.

        This method generates HTML start tags while applying workarounds for
        Internet Explorer bugs. Specifically, it modifies 'tags' IDs and names
        to 'tags_' to prevent rendering issues in IE.

        Args:
            node: The document tree node being processed.
            tagname (str): The HTML tag name (e.g., 'div', 'span').
            suffix (str, optional): String to append after the tag. Defaults to '\n'.
            empty (int, optional): Whether this is an empty/self-closing tag. Defaults to 0.
            **attributes: Additional HTML attributes for the tag.

        Returns:
            str: The generated HTML start tag with IE compatibility fixes applied.

        Note:
            The method specifically replaces:
            - id="tags" with id="tags_"
            - name="tags" with name="tags_"
            - href="#tags" with href="#tags_"
        """
        x = html4css1.HTMLTranslator.starttag(
            self, node, tagname, suffix, empty, **attributes
        )
        y = x.replace('id="tags"', 'id="tags_"')
        y = y.replace('name="tags"', 'name="tags_"')
        y = y.replace('href="#tags"', 'href="#tags_"')
        return y


# Create a custom writer that uses our IE-safe translator
mywriter = html4css1.Writer()
mywriter.translator_class = IESafeHtmlTranslator

# Run the docutils command line interface with our custom writer
publish_cmdline(writer=mywriter, description=description)
