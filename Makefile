all: executables

executables:
	chmod u+x ./bzr
	chmod u+x ./setup.py

check:
	./bzr selftest

clean: executables
	./setup.py clean
	find . -name "*.pyc" | xargs rm
	rm -rf test????.tmp

.PHONY: all


# build emacs cross-reference
tag_files=./bzr ./bzrlib/*py ./bzrlib/selftest/*.py
TAGS: $(tag_files)
	ctags-exuberant -e $(tag_files)
