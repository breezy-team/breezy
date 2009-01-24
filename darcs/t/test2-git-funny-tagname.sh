. lib.sh

create_darcs test2 --darcs-2
cd test2
darcs tag "this :just (won't work; die)"
cd ..

rm -rf test2.darcs test2.git
mkdir test2.git
cd test2.git
git --bare init
cd ..
if [ "$1" != "--stdout" ]; then
	darcs-fast-export test2 |(cd test2.git; git fast-import)
	ret=$?
	if [ $ret = 0 ]; then
		diff_git test2
		exit $?
	else
		exit $ret
	fi
else
	darcs-fast-export test2
fi
