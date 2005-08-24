all:
	chmod u+x ./bzr

check:
	./bzr selftest

.PHONY: all
