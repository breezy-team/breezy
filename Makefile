BZR ?= bzr
SETUP ?= ./setup.py
PYDOCTOR ?= pydoctor
CTAGS = ?= ctags
PYLINT ?= pylint

all:: build

build::
	$(SETUP) build

install::
	$(SETUP) install

clean::
	$(SETUP) clean

check::

lint::
	$(PYLINT) -f parseable *.py */*.py

pydoctor::
	$(PYDOCTOR) --make-html -c bzr-svn.cfg

tags::
	$(CTAGS) -R .

ctags:: tags
