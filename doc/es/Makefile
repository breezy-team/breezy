# Copyright (C) 2005, 2006, 2007, 2008 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

### Documentation ###

# set PRETTY to get docs that look like the Bazaar web site
ifdef PRETTY
rst2html := $(PYTHON) ../../tools/rst2prettyhtml.py doc/bazaar-vcs.org.kid 
else
rst2html := $(PYTHON) ../../tools/rst2html.py --link-stylesheet --footnote-references=superscript --halt=warning
endif

# translate txt docs to html
doc_dir := tutorials
txt_files := $(wildcard $(addsuffix /*.txt, $(doc_dir))) \
	guia-usuario/index.txt \
	mini-tutorial/index.txt \
	../index.es.txt
non_txt_files := \
       ../default.css \
       referencia-rapida/referencia-rapida.svg \
       referencia-rapida/referencia-rapida.png \
       referencia-rapida/referencia-rapida.pdf \
       $(wildcard guia-usuario/images/*.png)
htm_files := $(patsubst %.txt, %.html, $(txt_files)) 

guia-usuario/index.html: $(wildcard $(addsuffix /*.txt, guia-usuario)) 
	$(rst2html) --stylesheet=../../default.css guia-usuario/index.txt $@

../index.es.html: ../index.es.txt
	$(rst2html) --stylesheet=default.css $< $@

%.html: %.txt
	$(rst2html) --stylesheet=../../default.css $< $@


derived_web_docs = $(htm_files)
WEB_DOCS = $(derived_web_docs) $(non_txt_files)
ALL_DOCS = $(derived_web_docs)

# the main target to build all the docs
docs: $(ALL_DOCS)
# produce a tree containing just the final docs, ready for uploading to the web
HTMLDIR := html_docs
html-docs: docs
	$(PYTHON) ../../tools/win32/ostools.py copytree $(WEB_DOCS) $(HTMLDIR)

# clean produced docs
clean-docs:
	$(PYTHON) ../../tools/win32/ostools.py remove $(ALL_DOCS) \
	$(HTMLDIR) $(derived_txt_files)
