all:

check:
	python -Werror ./bzr selftest -v $(tests)
	@echo "Running all tests with no locale."
	LC_CTYPE= LANG=C LC_ALL= ./bzr selftest -v $(tests)

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
	./setup.py clean
	-find . -name "*.pyc" -o -name "*.pyo" | xargs rm -f
	rm -rf test????.tmp

.PHONY: all


# build emacs cross-reference
tag_files=./bzr ./bzrlib/*py ./bzrlib/selftest/*.py
TAGS: $(tag_files)
	ctags-exuberant -e $(tag_files)


# Produce HTML docs to upload on Canonical server
HTMLDIR := html_docs

html-docs: docs
	python tools/win32/ostools.py copytodir $(htm_files) doc/default.css $(HTMLDIR)


# translate txt docs to html
doc_dir := doc 
txt_files := $(wildcard $(addsuffix /*.txt, $(doc_dir)))
htm_files := $(patsubst %.txt, %.htm, $(txt_files)) doc/bzr_man.htm

%.htm: %.txt
	python tools/rst2html.py --link-stylesheet --stylesheet=default.css $*.txt $*.htm

doc/bzr_man.txt: bzrlib/builtins.py \
		 bzrlib/bundle/commands.py \
		 bzrlib/conflicts.py \
		 bzrlib/sign_my_commits.py \
		 generate_docs.py \
		 tools/doc_generate/__init__.py \
		 tools/doc_generate/autodoc_rstx.py
	python generate_docs.py -o doc/bzr_man.txt rstx

docs: $(htm_files)

copy-docs: docs
	python tools/win32/ostools.py copytodir $(htm_files) doc/default.css NEWS README  win32_bzr.exe/doc

# clean produced docs
clean-docs:
	python tools/win32/ostools.py remove doc/bzr_man.txt $(htm_files) $(HTMLDIR)


# make bzr.exe for win32 with py2exe
exe:
	@echo *** Make bzr.exe
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
	python setup.py bdist_wininst --title="Bazaar" --install-script="bzr-win32-bdist-postinstall.py"


# clean on win32 all installer-related files and directories
clean-win32:
	python tools/win32/ostools.py remove build
	python tools/win32/ostools.py remove win32_bzr.exe
	python tools/win32/ostools.py remove py2exe.log
	python tools/win32/ostools.py remove doc/*.htm
	python tools/win32/ostools.py remove doc/bzr_man.txt
	python tools/win32/ostools.py remove tools/win32/bzr.iss
	python tools/win32/ostools.py remove bzr-setup*.exe
	python tools/win32/ostools.py remove dist
