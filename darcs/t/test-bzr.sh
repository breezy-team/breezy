. lib.sh

create_darcs test --old-fashioned-inventory

rm -rf test.darcs test.bzr
mkdir test.bzr
cd test.bzr
bzr init-repo .
cd ..
if [ "$1" != "--stdout" ]; then
	../darcs-fast-export.py test |(cd test.bzr; bzr fast-import -)
	if [ $? = 0 ]; then
		cd test.bzr/master
		bzr update
		cd - >/dev/null
		echo "bugs:"
		diff --exclude _darcs --exclude .bzr --exclude '*-darcs-backup*' -Naur test.bzr/master test
		exit $?
	fi
else
	../darcs-fast-export.py test
fi
