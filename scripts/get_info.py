import argparse
from pathlib import Path

import utils_gitlab
import gitlab


def main():
    parser = argparse.ArgumentParser(description='Scripts to get information from gitlab')

    ## arguments
    parser.add_argument('--num-lab', '-n', help='Lab number to obtain stats from', type=int, required=True)
    parser.add_argument('--tags', '-t', action='store_true', help='show users with unexpteced tags')
    parser.add_argument('--protected', '-p', action='store_true', help='show users with protected main branches')
    parser.add_argument('--log-path', type=Path, help='log file to print protected branches to')

    args = parser.parse_args()
    if not (args.tags or args.protected):
        parser.print_help()
        return

    gl = gitlab.Gitlab("https://git.chalmers.se/", private_token="glpat-zQ79CZkPLtbPYqMqrWNo")
    gl.auth()

    if args.protected:
        prot_branches = utils_gitlab.check_protected_main_branches(gl, args.num_lab)
        print("The following groups have their main branch protected:")
        for web_url in prot_branches.keys():
            print(web_url)
            if args.log_path:
                with open(args.log_path, "w") as f:
                    print(web_url, file=f)

    if args.tags:
        n_commits, n_tags, total = utils_gitlab.check_commits_tags(gl, args.num_lab)
        print(f"A total of {n_commits} out of {total} groups have made at least one commit, and a total of {n_tags} have made at least one tag")


if __name__ == "__main__":
    main()
