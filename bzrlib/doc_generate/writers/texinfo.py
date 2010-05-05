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

"""A sphinx/docutil writer producing texinfo output."""

from docutils import (
    nodes,
    writers,
    )


class TexinfoWriter(writers.Writer):

    supported = ('texinfo',)
    settings_spec = ('No options here.', '', ())
    settings_defaults = {}

    output = None

    def __init__(self, builder):
        writers.Writer.__init__(self)
        self.builder = builder

    def translate(self):
        visitor = TexinfoTranslator(self.document, self.builder)
        self.document.walkabout(visitor)
        self.output = visitor.body


class TexinfoTranslator(nodes.NodeVisitor):

    def __init__(self, document, builder):
        nodes.NodeVisitor.__init__(self, document)
        self.chunks = []

    def add_text(self, text):
        self.chunks.append(text)

    # The whole document

    def visit_document(self, node):
        pass

    def depart_document(self, node):
        self.body = ''.join(chunk for chunk in self.chunks)

    # Layout

    def visit_section(self, node):
        pass

    def depart_section(self, node):
        pass

    def visit_topic(self, node):
        pass

    def depart_topic(self, node):
        pass

    def visit_paragraph(self, node):
        # Start the paragraph on a new line.
        self.add_text('\n')

    def depart_paragraph(self, node):
        # End the paragraph with a new line.
        self.add_text('\n')

    def visit_compact_paragraph(self, node):
        pass

    def depart_compact_paragraph(self, node):
        pass

    def visit_block_quote(self, node):
        pass

    def depart_block_quote(self, node):
        pass

    def visit_note(self, node):
        pass

    def depart_warning(self, node):
        pass

    def visit_warning(self, node):
        pass

    def depart_note(self, node):
        pass

    def visit_footnote(self, node):
        pass

    def depart_footnote(self, node):
        pass

    def visit_comment(self, node):
        raise nodes.SkipNode

    # Attributes

    def visit_title(self, node):
        pass

    def depart_title(self, node):
        pass

    def visit_label(self, node):
        raise nodes.SkipNode

    def visit_substitution_definition(self, node):
        raise nodes.SkipNode

    # Plain text

    def visit_Text(self, node):
        pass

    def depart_Text(self, node):
        self.add_text(node.astext())

    # Styled text

    def visit_emphasis(self, node):
        self.add_text('@emph{')

    def depart_emphasis(self, node):
        self.add_text('}')

    def visit_strong(self, node):
        self.add_text('@strong{')

    def depart_strong(self, node):
        self.add_text('}')

    def visit_literal_block(self, node):
        pass

    def depart_literal_block(self, node):
        pass

    def visit_literal(self, node):
        pass

    def depart_literal(self, node):
        pass

    # Lists

    def visit_bullet_list(self, node):
        pass

    def depart_bullet_list(self, node):
        pass

    def visit_enumerated_list(self, node):
        pass

    def depart_enumerated_list(self, node):
        pass

    def visit_definition_list(self, node):
        pass

    def depart_definition_list(self, node):
        pass

    def visit_definition_list_item(self, node):
        pass

    def depart_definition_list_item(self, node):
        pass

    def visit_term(self, node):
        pass

    def depart_term(self, node):
        pass

    def visit_definition(self, node):
        pass

    def depart_definition(self, node):
        pass

    def visit_field_list(self, node):
        pass
    def depart_field_list(self, node):
        pass

    def visit_field(self, node):
        pass
    def depart_field(self, node):
        pass

    def visit_field_name(self, node):
        pass

    def depart_field_name(self, node):
        pass

    def visit_field_body(self, node):
        pass

    def depart_field_body(self, node):
        pass

    def visit_list_item(self, node):
        pass

    def depart_list_item(self, node):
        pass

    def visit_option_list(self, node):
        pass

    def depart_option_list(self, node):
        pass

    def visit_option_list_item(self, node):
        pass

    def depart_option_list_item(self, node):
        pass

    def visit_option_group(self, node):
        pass

    def depart_option_group(self, node):
        pass

    def visit_option(self, node):
        pass

    def depart_option(self, node):
        pass

    def visit_option_string(self, node):
        pass
    def depart_option_string(self, node):
        pass

    def visit_option_argument(self, node):
        pass

    def depart_option_argument(self, node):
        pass

    def visit_description(self, node):
        pass
    def depart_description(self, node):
        pass

    # Tables
    def visit_table(self, node):
        pass

    def depart_table(self, node):
        pass

    def visit_tgroup(self, node):
        pass

    def depart_tgroup(self, node):
        pass

    def visit_colspec(self, node):
        raise nodes.SkipNode

    def visit_thead(self, node):
        pass
    def depart_thead(self, node):
        pass

    def visit_row(self, node):
        pass

    def depart_row(self, node):
        pass

    def visit_entry(self, node):
        pass

    def depart_entry(self, node):
        pass

    def visit_tbody(self, node):
        pass

    def depart_tbody(self, node):
        pass

    # References

    def visit_reference(self, node):
        pass
    def depart_reference(self, node):
        pass

    def visit_footnote_reference(self, node):
        raise nodes.SkipNode

    def visit_citation_reference(self, node):
        raise nodes.SkipNode

    def visit_title_reference(self, node):
        pass

    def depart_title_reference(self, node):
        pass

    def visit_target(self, node):
        pass

    def depart_target(self, node):
        pass

    def visit_image(self, node):
        self.add_text(_('[image]'))
        raise nodes.SkipNode


# For quick debugging activate the lines below
# from sphinx.writers import text
# TexinfoWriter = text.TextWriter

