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

.PHONY: all clean extensions pyflakes api-docs

all: extensions

extensions:
	@echo "building extension modules."
	python setup.py build_ext -i

check: docs extensions
	python -Werror ./bzr selftest -v $(tests)
	@echo "Running all tests with no locale."
	LC_CTYPE= LANG=C LC_ALL= ./bzr selftest -v $(tests)
	python -O -Werror ./bzr selftest -v $(tests)

check-msgeditor:
	./bzr --no-plugins selftest -v msgeditor

# Run Python style checker (apt-get install pyflakes)
pyflakes:
	pyflakes bzrlib

pyflakes-nounused:
	# There are many of these warnings at the moment and they're not a
	# high priority to fix
	pyflakes bzrlib | grep -v ' imported but unused'

clean:
	python setup.py clean
	-find . -name "*.pyc" -o -name "*.pyo" | xargs rm -f
	rm -rf test????.tmp

# Build API documentation
docfiles = bzr bzrlib
api-docs:
	mkdir -p api/html
	PYTHONPATH=$(PWD) python tools/bzr_epydoc --html -o api/html --docformat 'restructuredtext en' $(docfiles)
check-api-docs:
	PYTHONPATH=$(PWD) python tools/bzr_epydoc --check --docformat 'restructuredtext en' $(docfiles)

# build emacs cross-reference
tag_files=./bzr ./bzrlib/*py ./bzrlib/selftest/*.py
TAGS: $(tag_files)
	ctags-exuberant -e $(tag_files)


### Documentation ###

# translate txt docs to html
derived_txt_files := \
	doc/en/user-reference/bzr_man.txt \
	doc/en/developer-guide/HACKING.txt \
	doc/en/release-notes/NEWS.txt
doc_dir := doc/en/user-guide
txt_files := $(wildcard $(addsuffix /*.txt, $(doc_dir))) $(derived_txt_files) \
	doc/en/mini-tutorial/index.txt \
	doc/index.txt
htm_files := $(patsubst %.txt, %.html, $(txt_files)) 
dev_txt_files := $(wildcard $(addsuffix /*.txt, doc/developers))
dev_htm_files := $(patsubst %.txt, %.html, $(dev_txt_files)) 

doc/developers/%.html: doc/developers/%.txt
	python tools/rst2html.py --link-stylesheet --stylesheet=../default.css --footnote-references=superscript $< $@

doc/index.html: doc/index.txt
	python tools/rst2html.py --link-stylesheet --stylesheet=default.css --footnote-references=superscript $< $@

%.html: %.txt
	python tools/rst2html.py --link-stylesheet --stylesheet=../../default.css --footnote-references=superscript $< $@

MAN_DEPENDENCIES = bzrlib/builtins.py \
		 bzrlib/bundle/commands.py \
		 bzrlib/conflicts.py \
		 bzrlib/sign_my_commits.py \
		 generate_docs.py \
		 tools/doc_generate/__init__.py \
		 tools/doc_generate/autodoc_man.py \
		 tools/doc_generate/autodoc_rstx.py

doc/en/user-reference/bzr_man.txt: $(MAN_DEPENDENCIES)
	python generate_docs.py -o $@ rstx

doc/en/developer-guide/HACKING.txt: doc/developers/HACKING.txt
	python tools/win32/ostools.py copytodir doc/developers/HACKING.txt doc/en/developer-guide

doc/en/release-notes/NEWS.txt: NEWS
	python -c "import shutil; shutil.copyfile('$<', '$@')"

MAN_PAGES = man1/bzr.1
man1/bzr.1: $(MAN_DEPENDENCIES)
	python generate_docs.py -o $@ man

WEB_DOCS = $(htm_files) $(dev_htm_files) \
	   doc/default.css \
	   doc/en/quick-reference/quick-start-summary.svg \
	   doc/developers/performance.png
ALL_DOCS = $(WEB_DOCS) $(MAN_PAGES)
docs: $(ALL_DOCS)

# build a png of our performance task list
doc/developers/performance.png: doc/developers/performance.dot
	@echo Generating $@
	@dot -Tpng $< -o$@ || echo "Dot not installed; skipping generation of $@"


### Pretty Documentation ###

HTMLDIR := html_docs
PRETTYDIR := pretty_docs

# Produce HTML docs to upload on Canonical server
html-docs: docs
	python tools/win32/ostools.py copytree $(WEB_DOCS) $(HTMLDIR)

$(PRETTYDIR)/%.html: pretty_docs doc/%.txt
	python tools/rst2prettyhtml.py doc/bazaar-vcs.org.kid doc/$*.txt \
	$(PRETTYDIR)/$*.html

pretty-html-docs: pretty_files

pretty_docs:
	python -c "import os; os.mkdir('$(PRETTYDIR)')"

pretty_files: $(patsubst doc/%.txt, $(PRETTYDIR)/%.html, $(txt_files))

# clean produced docs
clean-docs:
	python tools/win32/ostools.py remove $(ALL_DOCS) \
	$(HTMLDIR) $(PRETTYDIR) $(derived_txt_files)


### Windows Support ###

# make bzr.exe for win32 with py2exe
exe:
	@echo *** Make bzr.exe
	python setup.py build_ext -i -f
	python setup.py py2exe > py2exe.log
	python tools/win32/ostools.py copytodir tools/win32/start_bzr.bat win32_bzr.exe
	python tools/win32/ostools.py copytodir tools/win32/bazaar.url win32_bzr.exe

# win32 installer for bzr.exe
installer: exe copy-docs
	@echo *** Make windows installer
	cog.py -d -o tools/win32/bzr.iss tools/win32/bzr.iss.cog
	iscc /Q tools/win32/bzr.iss

# win32 python's distutils-based installer
# require to have python interpreter installed on win32
python-installer: docs
	python24 setup.py bdist_wininst --install-script="bzr-win32-bdist-postinstall.py" -d .
	python25 setup.py bdist_wininst --install-script="bzr-win32-bdist-postinstall.py" -d .

copy-docs: docs
	python tools/win32/ostools.py copytodir README win32_bzr.exe/doc
	python tools/win32/ostools.py copytree $(WEB_DOCS) win32_bzr.exe

# clean on win32 all installer-related files and directories
clean-win32: clean-docs
	python tools/win32/ostools.py remove build
	python tools/win32/ostools.py remove win32_bzr.exe
	python tools/win32/ostools.py remove py2exe.log
	python tools/win32/ostools.py remove tools/win32/bzr.iss
	python tools/win32/ostools.py remove bzr-setup*.exe
	python tools/win32/ostools.py remove bzr-*win32.exe
	python tools/win32/ostools.py remove dist
