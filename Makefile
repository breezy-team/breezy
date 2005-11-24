all: 

check:
	./bzr selftest $(tests)

clean: 
	./setup.py clean
	find . -name "*.pyc" | xargs rm
	rm -rf test????.tmp

.PHONY: all


# build emacs cross-reference
tag_files=./bzr ./bzrlib/*py ./bzrlib/selftest/*.py
TAGS: $(tag_files)
	ctags-exuberant -e $(tag_files)
