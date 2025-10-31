#!/bin/bash
set -e -u

usage () {
	cat <<EOF
Usage: $_SCRIPTNAME repo main-branch
EOF
}

usage_and_exit_zero () {
	usage
	exit 0
}

usage_and_exit_nonzero () {
	usage
	exit 2
}

_SCRIPTNAME=$(basename $0)

if [ $# -lt 2 ]
then
  usage_and_exit_nonzero
fi

export REPO=$1
export MAIN_COMMIT=$(git -C $REPO rev-parse $2)

printf "Fetching from all repos...\n"

git -C $REPO fetch --all

printf "Calculating the commits that differ from $2 ($MAIN_COMMIT).\n"
SAME=$(git -C $REPO branch --list --remotes | xargs -I {} bash -c 'if [ $(git -C $REPO rev-parse {}) =  $MAIN_COMMIT ]; then echo {}; fi' | wc -l)
DIFF=$(git -C $REPO branch --list --remotes | xargs -I {} bash -c 'if [ $(git -C $REPO rev-parse {}) != $MAIN_COMMIT ]; then echo {}; fi' | wc -l)

printf "Results (different/same):\n"
printf "$DIFF/$SAME\n"
