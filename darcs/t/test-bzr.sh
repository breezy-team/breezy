. lib.sh

create_darcs test --old-fashioned-inventory

rm -rf test.darcs test.bzr
mkdir test.bzr
cd test.bzr
bzr init-repo .
cd ..
if [ "$1" != "--stdout" ]; then
	../darcs-fast-export test |(cd test.bzr; bzr fast-import -)
	diff_bzr test
	exit $?
else
	../darcs-fast-export test
fi
