import json
import sys
import requests
import pathlib

# Put your Canvas access token in AUTH_TOKEN
auth_file = pathlib.Path('AUTH_TOKEN')
try:
    auth_token = auth_file.open().read().strip()
except FileNotFoundError:
    print_error('No Canvas authorization token found.')
    print_error('Expected Canvas authorization token in file {}.'.format(auth_file))
    exit(1)

baseurl = 'https://chalmers.instructure.com/api/v1'
headers = {
    'Authorization': f'Bearer {auth_token}',
}
params = (('per_page', '100'),)

# This is the id for the lab group set
# You can find it by going to Course -> People -> click on the tab for your group set
# Then the groupset id is in the URL (.../groups#tab-5387)
groupset = 5387 


response = requests.get(f'{baseurl}/group_categories/{groupset}/groups', headers=headers, params=params)
groups = { g["id"]: g["name"] for g in response.json() }

while "next" in response.links:
    response = requests.get(response.links["next"]["url"], headers=headers)
    groups.update({ g["id"]: g["name"] for g in response.json() })

print(f"Nr. groups: {len(groups)}", file=sys.stderr)


users = {}

for gid, group in groups.items():
    response = requests.get(f'{baseurl}/groups/{gid}/users', headers=headers, params=params)
    for u in response.json():
        pnr = u["sis_user_id"]
        users[pnr] = {
            "id": u["id"],
            "name": u["name"],
            "sortname": u["sortable_name"],
            "gid": gid,
            "group": group,
        }
        print('.', end='', flush=True, file=sys.stderr)
print(file=sys.stderr)
print(f"Nr. students: len(users)", file=sys.stderr)
print(file=sys.stderr)

json.dump(users, sys.stdout, indent=4)
