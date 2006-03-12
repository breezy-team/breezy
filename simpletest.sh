#!/bin/sh
TESTS="$*"

rm -rf bzr.test

if [ -z "$TESTS" ]; then
	TESTS=testdata/*.dump
fi

for I in $TESTS
do
	echo "Testing $I"
	./svn2bzr.py --log=debug --scheme=trunk $I bzr.test || exit 1
	rm -rf bzr.test
done
exit 0
