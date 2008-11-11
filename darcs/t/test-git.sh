. lib.sh

create_darcs test --old-fashioned-inventory

rm -rf test.darcs test.git
mkdir test.git
cd test.git
git --bare init
cd ..
if [ "$1" != "--stdout" ]; then
	../darcs-fast-export.py test |(cd test.git; git fast-import)
	if [ $? = 0 ]; then
		diff_git
		exit $?
	fi
else
	../darcs-fast-export.py test
fi
