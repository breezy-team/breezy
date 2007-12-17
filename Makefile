# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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

# A relatively simple Makefile to assist in building parts of bzr. Mostly for
# building documentation, etc.


### Core Stuff ###

PYTHON=python

.PHONY: all clean extensions pyflakes api-docs

all: extensions

extensions:
	@echo "building extension modules."
	$(PYTHON) setup.py build_ext -i

check: docs extensions
	$(PYTHON) -Werror -O ./bzr selftest -1v $(tests)
	@echo "Running all tests with no locale."
	LC_CTYPE= LANG=C LC_ALL= ./bzr selftest -1v $(tests) 2>&1 | sed -e 's/^/[ascii] /'

# Run Python style checker (apt-get install pyflakes)
#
# Note that at present this gives many false warnings, because it doesn't
# know about identifiers loaded through lazy_import.
pyflakes:
	pyflakes bzrlib

pyflakes-nounused:
	# There are many of these warnings at the moment and they're not a
	# high priority to fix
	pyflakes bzrlib | grep -v ' imported but unused'

clean:
	$(PYTHON) setup.py clean
	-find . -name "*.pyc" -o -name "*.pyo" -o -name "*.so" | xargs rm -f

# Build API documentation
docfiles = bzr bzrlib
api-docs:
	mkdir -p api/html
	PYTHONPATH=$(PWD) $(PYTHON) tools/bzr_epydoc --html -o api/html --docformat 'restructuredtext en' $(docfiles)
check-api-docs:
	PYTHONPATH=$(PWD) $(PYTHON) tools/bzr_epydoc --check --docformat 'restructuredtext en' $(docfiles)

# build tags for emacs and vim
TAGS:
	ctags -R -e bzrlib

tags:
	ctags -R bzrlib

# these are treated as phony so they'll always be rebuilt - it's pretty quick
.PHONY: TAGS tags

### Documentation ###

# set PRETTY to get docs that look like the Bazaar web site
ifdef PRETTY
rst2html := $(PYTHON) tools/rst2prettyhtml.py doc/bazaar-vcs.org.kid 
else
rst2html := $(PYTHON) tools/rst2html.py --link-stylesheet --footnote-references=superscript --halt=warning
endif

# translate txt docs to html
derived_txt_files := \
	doc/en/user-reference/bzr_man.txt \
	doc/en/developer-guide/HACKING.txt \
	doc/en/release-notes/NEWS.txt
doc_dir := doc/en/tutorials
txt_files := $(wildcard $(addsuffix /*.txt, $(doc_dir))) $(derived_txt_files) \
	doc/en/user-guide/index.txt \
	doc/en/mini-tutorial/index.txt \
	doc/index.txt
non_txt_files := \
       doc/default.css \
       doc/en/quick-reference/quick-start-summary.svg \
       doc/en/quick-reference/quick-start-summary.png \
       doc/en/quick-reference/quick-start-summary.pdf \
       $(wildcard doc/en/user-guide/images/*.png)
htm_files := $(patsubst %.txt, %.html, $(txt_files)) 
dev_txt_files := $(wildcard $(addsuffix /*.txt, doc/developers))
dev_htm_files := $(patsubst %.txt, %.html, $(dev_txt_files)) 

doc/en/user-guide/index.html: $(wildcard $(addsuffix /*.txt, doc/en/user-guide)) 
	$(rst2html) --stylesheet=../../default.css doc/en/user-guide/index.txt $@

doc/developers/%.html: doc/developers/%.txt
	$(rst2html) --stylesheet=../default.css $< $@

doc/index.html: doc/index.txt
	$(rst2html) --stylesheet=default.css $< $@

%.html: %.txt
	$(rst2html) --stylesheet=../../default.css $< $@

MAN_DEPENDENCIES = bzrlib/builtins.py \
		 bzrlib/bundle/commands.py \
		 bzrlib/conflicts.py \
		 bzrlib/help_topics/__init__.py \
		 bzrlib/sign_my_commits.py \
		 bzrlib/bugtracker.py \
		 generate_docs.py \
		 tools/doc_generate/__init__.py \
		 tools/doc_generate/autodoc_man.py \
		 tools/doc_generate/autodoc_rstx.py \
		 $(wildcard $(addsuffix /*.txt, bzrlib/help_topics/en)) 

doc/en/user-reference/bzr_man.txt: $(MAN_DEPENDENCIES)
	$(PYTHON) generate_docs.py -o $@ rstx

doc/en/developer-guide/HACKING.txt: doc/developers/HACKING.txt
	$(PYTHON) tools/win32/ostools.py copytodir doc/developers/HACKING.txt doc/en/developer-guide

doc/en/release-notes/NEWS.txt: NEWS
	$(PYTHON) -c "import shutil; shutil.copyfile('$<', '$@')"

MAN_PAGES = man1/bzr.1
man1/bzr.1: $(MAN_DEPENDENCIES)
	$(PYTHON) generate_docs.py -o $@ man

# build a png of our performance task list
doc/developers/performance.png: doc/developers/performance.dot
	@echo Generating $@
	@dot -Tpng $< -o$@ || echo "Dot not installed; skipping generation of $@"

derived_web_docs = $(htm_files) $(dev_htm_files) doc/developers/performance.png
WEB_DOCS = $(derived_web_docs) $(non_txt_files)
ALL_DOCS = $(derived_web_docs) $(MAN_PAGES)

# the main target to build all the docs
docs: $(ALL_DOCS)

# produce a tree containing just the final docs, ready for uploading to the web
HTMLDIR := html_docs
html-docs: docs
	$(PYTHON) tools/win32/ostools.py copytree $(WEB_DOCS) $(HTMLDIR)

# clean produced docs
clean-docs:
	$(PYTHON) tools/win32/ostools.py remove $(ALL_DOCS) \
	$(HTMLDIR) $(derived_txt_files)


### Windows Support ###

# make bzr.exe for win32 with py2exe
exe:
	@echo *** Make bzr.exe
	$(PYTHON) setup.py build_ext -i -f
	$(PYTHON) setup.py py2exe > py2exe.log
	$(PYTHON) tools/win32/ostools.py copytodir tools/win32/start_bzr.bat win32_bzr.exe
	$(PYTHON) tools/win32/ostools.py copytodir tools/win32/bazaar.url win32_bzr.exe

# win32 installer for bzr.exe
installer: exe copy-docs
	@echo *** Make windows installer
	cog.py -d -o tools/win32/bzr.iss tools/win32/bzr.iss.cog
	iscc /Q tools/win32/bzr.iss

# win32 Python's distutils-based installer
# require to have Python interpreter installed on win32
py-inst-24: docs
	python24 setup.py bdist_wininst --install-script="bzr-win32-bdist-postinstall.py" -d .

py-inst-25: docs
	python25 setup.py bdist_wininst --install-script="bzr-win32-bdist-postinstall.py" -d .

python-installer: py-inst-24 py-inst-25


copy-docs: docs
	$(PYTHON) tools/win32/ostools.py copytodir README win32_bzr.exe/doc
	$(PYTHON) tools/win32/ostools.py copytree $(WEB_DOCS) win32_bzr.exe

# clean on win32 all installer-related files and directories
clean-win32: clean-docs
	$(PYTHON) tools/win32/ostools.py remove build
	$(PYTHON) tools/win32/ostools.py remove win32_bzr.exe
	$(PYTHON) tools/win32/ostools.py remove py2exe.log
	$(PYTHON) tools/win32/ostools.py remove tools/win32/bzr.iss
	$(PYTHON) tools/win32/ostools.py remove bzr-setup*.exe
	$(PYTHON) tools/win32/ostools.py remove bzr-*win32.exe
	$(PYTHON) tools/win32/ostools.py remove dist
