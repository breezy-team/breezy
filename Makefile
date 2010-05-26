# Copyright (C) 2005-2010 Canonical Ltd
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

# A relatively simple Makefile to assist in building parts of bzr. Mostly for
# building documentation, etc.


### Core Stuff ###

PYTHON=python
PYTHON24=python24
PYTHON25=python25
PYTHON26=python26
BZR_TARGET=release
PLUGIN_TARGET=plugin-release
PYTHON_BUILDFLAGS=

.PHONY: all clean extensions pyflakes api-docs check-nodocs check

all: extensions

extensions:
	@echo "building extension modules."
	$(PYTHON) setup.py build_ext -i $(PYTHON_BUILDFLAGS)

check: docs check-nodocs

check-nodocs: extensions
	# Generate a stream for PQM to watch.
	$(PYTHON) -Werror -O ./bzr selftest --subunit $(tests) | tee selftest.log
	# Check that there were no errors reported.
	subunit-stats < selftest.log

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

docs: docs-sphinx

clean-docs: clean-sphinx

html-docs: html-sphinx


### Man-page Documentation ###

MAN_DEPENDENCIES = bzrlib/builtins.py \
	$(wildcard bzrlib/*.py) \
	$(wildcard bzrlib/*/*.py) \
	tools/generate_docs.py \
	$(wildcard $(addsuffix /*.txt, bzrlib/help_topics/en)) 

MAN_PAGES = man1/bzr.1
man1/bzr.1: $(MAN_DEPENDENCIES)
	$(PYTHON) tools/generate_docs.py -o $@ man


### Sphinx-style Documentation ###

# Build the documentation. To keep the dependencies down to a minimum
# for distro packagers, we only build the html documentation by default.
# Sphinx 0.6 or later is preferred for the best rendering, though
# Sphinx 0.4 or later should work. See http://sphinx.pocoo.org/index.html
# for installation instructions.
docs-sphinx: html-sphinx

# Clean out generated documentation
clean-sphinx:
	cd doc/en && make clean
	cd doc/es && make clean
	cd doc/ja && make clean
	cd doc/ru && make clean
	cd doc/developers && make clean

SPHINX_DEPENDENCIES = \
        doc/en/release-notes/index.txt \
        doc/en/user-reference/index.txt \
	doc/es/Makefile \
	doc/es/make.bat \
	doc/ja/Makefile \
	doc/ja/make.bat \
	doc/ru/Makefile \
	doc/ru/make.bat \
	doc/developers/Makefile \
	doc/developers/make.bat

doc/en/user-reference/index.txt: $(MAN_DEPENDENCIES)
	$(PYTHON) tools/generate_docs.py -o $@ rstx

doc/en/release-notes/index.txt: NEWS tools/generate_release_notes.py
	$(PYTHON) tools/generate_release_notes.py NEWS $@

doc/%/Makefile: doc/en/Makefile
	$(PYTHON) -c "import shutil; shutil.copyfile('$<', '$@')"

doc/%/make.bat: doc/en/make.bat
	$(PYTHON) -c "import shutil; shutil.copyfile('$<', '$@')"

# Build the html docs using Sphinx.
html-sphinx: $(SPHINX_DEPENDENCIES)
	cd doc/en && make html
	cd doc/es && make html
	cd doc/ru && make html
	cd doc/ja && make html
	cd doc/developers && make html

# Build the PDF docs using Sphinx. This requires numerous LaTeX
# packages. See http://sphinx.pocoo.org/builders.html for details.
# Note: We don't currently build PDFs for the Russian docs because
# they require additional packages to be installed (to handle
# Russian hyphenation rules, etc.)
pdf-sphinx: $(SPHINX_DEPENDENCIES)
	cd doc/en && make latex
	cd doc/es && make latex
	cd doc/ja && make latex
	cd doc/developers && make latex
	cd doc/en/_build/latex && make all-pdf
	cd doc/es/_build/latex && make all-pdf
	cd doc/developers/_build/latex && make all-pdf

# Build the CHM (Windows Help) docs using Sphinx.
# Note: HtmlHelp Workshop needs to be used on the generated hhp files
# to generate the final chm files.
chm-sphinx: $(SPHINX_DEPENDENCIES)
	cd doc/en && make htmlhelp
	cd doc/es && make htmlhelp
	cd doc/ru && make htmlhelp
	cd doc/ja && make htmlhelp
	cd doc/developers && make htmlhelp


### Documentation Website ###

# Where to build the website
DOC_WEBSITE_BUILD = build_doc_website

# Build and package docs into a website, complete with downloads.
doc-website: html-sphinx pdf-sphinx
	$(PYTHON) tools/package_docs.py doc/en $(DOC_WEBSITE_BUILD)
	$(PYTHON) tools/package_docs.py doc/es $(DOC_WEBSITE_BUILD)
	$(PYTHON) tools/package_docs.py doc/ru $(DOC_WEBSITE_BUILD)
	$(PYTHON) tools/package_docs.py doc/ja $(DOC_WEBSITE_BUILD)
	$(PYTHON) tools/package_docs.py doc/developers $(DOC_WEBSITE_BUILD)


### Miscellaneous Documentation Targets ###

# build a png of our performance task list
# this is no longer built by default; you can build it if you want to look at it
doc/developers/performance.png: doc/developers/performance.dot
	@echo Generating $@
	@dot -Tpng $< -o$@ || echo "Dot not installed; skipping generation of $@"


### Windows Support ###

# make all the installers completely from scratch, using zc.buildout
# to fetch the dependencies
# These are files that need to be copied into the build location to boostrap
# the build process.
# Note that the path is relative to tools/win32
BUILDOUT_FILES = buildout.cfg \
	buildout-templates/bin/build-installer.bat.in \
	ostools.py bootstrap.py

installer-all:
	@echo Make all the installers from scratch
	@# Build everything in a separate directory, to avoid cluttering the WT
	$(PYTHON) tools/win32/ostools.py makedir build-win32
	@# cd to tools/win32 so that the relative paths are copied correctly
	cd tools/win32 && $(PYTHON) ostools.py copytree $(BUILDOUT_FILES) ../../build-win32
	@# There seems to be a bug in gf.release.bzr, It doesn't correctly update
	@# existing release directories, so delete them manually before building
	@# It means things may be rebuilt that don't need to be, but at least
	@# it will be correct when they do.
	cd build-win32 && $(PYTHON) ostools.py remove release */release
	cd build-win32 && $(PYTHON) bootstrap.py
	cd build-win32 && bin/buildout
	cd build-win32 && bin/build-installer.bat $(BZR_TARGET) $(PLUGIN_TARGET)


clean-installer-all:
	$(PYTHON) tools/win32/ostools.py remove build-win32

# make bzr.exe for win32 with py2exe
exe:
	@echo *** Make bzr.exe
	$(PYTHON) tools/win32/ostools.py remove bzrlib/*.pyd
	$(PYTHON) setup.py build_ext -i -f $(PYTHON_BUILDFLAGS)
	$(PYTHON) setup.py py2exe > py2exe.log
	$(PYTHON) tools/win32/ostools.py copytodir tools/win32/start_bzr.bat win32_bzr.exe
	$(PYTHON) tools/win32/ostools.py copytodir tools/win32/bazaar.url win32_bzr.exe

# win32 installer for bzr.exe
installer: exe copy-docs
	@echo *** Make Windows installer
	$(PYTHON) tools/win32/run_script.py cog.py -d -o tools/win32/bzr.iss tools/win32/bzr.iss.cog
	iscc /Q tools/win32/bzr.iss

# win32 Python's distutils-based installer
# require to have Python interpreter installed on win32
py-inst-24: docs
	$(PYTHON24) setup.py bdist_wininst --install-script="bzr-win32-bdist-postinstall.py" -d .

py-inst-25: docs
	$(PYTHON25) setup.py bdist_wininst --install-script="bzr-win32-bdist-postinstall.py" -d .

py-inst-26: docs
	$(PYTHON26) setup.py bdist_wininst --install-script="bzr-win32-bdist-postinstall.py" -d .

python-installer: py-inst-24 py-inst-25 py-inst-26


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


### Packaging Targets ###

.PHONY: dist check-dist-tarball

# build a distribution source tarball
#
# this method of copying the pyrex generated files is a bit ugly; it would be
# nicer to generate it from distutils.
dist: 
	version=`./bzr version --short` && \
	echo Building distribution of bzr $$version && \
	expbasedir=`mktemp -t -d tmp_bzr_dist.XXXXXXXXXX` && \
	expdir=$$expbasedir/bzr-$$version && \
	tarball=$$PWD/../bzr-$$version.tar.gz && \
	$(MAKE) clean && \
	$(MAKE) && \
	bzr export $$expdir && \
	cp bzrlib/*.c bzrlib/*.h $$expdir/bzrlib/. && \
	tar cfz $$tarball -C $$expbasedir bzr-$$version && \
	gpg --detach-sign $$tarball && \
	rm -rf $$expbasedir

# run all tests in a previously built tarball
check-dist-tarball:
	tmpdir=`mktemp -t -d tmp_bzr_check_dist.XXXXXXXXXX` && \
	version=`./bzr version --short` && \
	tarball=$$PWD/../bzr-$$version.tar.gz && \
	tar Cxz $$tmpdir -f $$tarball && \
	$(MAKE) -C $$tmpdir/bzr-$$version check && \
	rm -rf $$tmpdir
