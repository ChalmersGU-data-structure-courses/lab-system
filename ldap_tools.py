# Observations for students of DIT181.
# Inconsistencies between user details on Canvas and in LDAP directory.

# * Users on GitLab may no longer have a CID.
#   Some of my students from DIT181 2021 are examples.
#   Sanna Zakrisson is still listed as a regular student on GU Canvas.
#   And she still has user account sannaza on Chalmers GitLab.
#   But LDAP shows no record of a correponding CID.
#   Other examples:
#   - Adam Shwehne, shwehne
#   -

# * Kumarapatabendige Silva on GU Canvas has LDAP entry:
#   - uid: maheli
#   - cn: Maheli Silva
#   - sn: Silva
#   - givenName: Maheli

# * Trenton Alexander Mellard on GU Canvas has LDAP entry:
#   - uid: trenton
#   - cn: Trenton Mellard
#   - sn: Trenton
#   - givenName: Trenton

# * Kevin Jalal on GU Canvas has LDAP entry:
#   - uid: didar
#   - cn: Didar Jalal
#   - sn: Jalal
#   - givenName: Didar

# * Najeb Albakar on GU Canvas has LDAP entry:
#   - uid: albakar
#   - cn: Mohamad Najeb Albakar
#   - sn: Mohamad Najeb Albakar
#   - givenName: Mohamad Najeb

# * Ahmed Yasser Abdelkarim on GU Canvas has LDAP entry:
#   - uid: ahmedya
#   - cn: Ahmed Yasser Abdelnaby Abdelkarim
#   - sn: Yasser Abdelnaby Abdelkarim
#   - givenName: Ahmed

# * Bora Kocak on GU Canvas has LDAP entry:
#   - uid: bora
#   - cn: b'Bora Ko\xc3\xa7ak'
#   - sn: b'Ko\xc3\xa7ak
#   - givenName: Bora

# Typical response for a GU student:
# ('uid=niklaxe,ou=people,dc=chalmers,dc=se', {'objectClass': [b'top', b'person', b'organizationalPerson', b'inetOrgPerson', b'eduPerson', b'norEduPerson'], 'cn': [b'Niklas Axelsson'], 'sn': [b'Axelsson'], 'givenName': [b'Niklas'], 'uid': [b'niklaxe'], 'mail': [b'niklaxe@student.chalmers.se'], 'eduPersonPrimaryAffiliation': [b'student'], 'eduPersonAffiliation': [b'student', b'member']})


import logging
import re

import ldap
import ldap.filter

import general


def list_all(client, base, scope, filterstr = None, attrlist = None, page_size = 100):
    # Chalmers LDAP has size limit 300.
    page_control = ldap.controls.SimplePagedResultsControl(
        True,
        size = page_size,
        cookie = str(),
    )

    while True:
        response = client.search_ext(
            base,
            scope,
            filterstr = filterstr,
            attrlist = attrlist,
            serverctrls = [page_control],
        )

        (rtype, rdata, rmsgid, serverctrls_response) = client.result3(response)
        yield from rdata

        (page_control_response,) = filter(
            lambda control: control.controlType == ldap.control.SimplePagedResultsControl.controlType,
            serverctrls_response,
        )
        page_control.cookie = page_control_response.cookie
        if not page_control.cookie:
            break



# logging.basicConfig()
# logging.getLogger().setLevel(logging.INFO)

#client = ldap.initialize('ldap://ldap.chalmers.se')

# #ldapsearch -x -H ldap://ldap.chalmers.se '(cn=Bardha Ahmeti)'

# import java_test.gitlab_config as config  # noqa: E402

# c = Course(config)
#a = c._gitlab_users

def is_bot_user(user):
    return any([
        re.fullmatch('project_\\d+_bot\\d*', user.username),
        user.username in ['alert-bot', 'support-bot'],
    ])

# Chalmers LDAP has size limit 300.
page_control = ldap.controls.SimplePagedResultsControl(True, size = 300, cookie = '')

def search_people(client, filter):
    return client.search_ext_s(
        'ou=people,dc=chalmers,dc=se',
        ldap.SCOPE_ONELEVEL,
        filter,
        serverctrls = [page_control],
    )

def search_people_by_cid(client, uid):
    return search_people(client, ldap.filter.filter_format('(uid=%s)', [uid]))

def search_people_by_name(client, cn):
    return search_people(client, ldap.filter.filter_format('(cn=%s)', [cn]))

def search_people_by_email_localpart(client, email_localpart):
    return search_people(client, ldap.filter.filter_format('(mail=%s@*)', [email_localpart]))

def print_record(record):
    (dn, attrs) = record
    print(dn)
    for (key, value) in attrs.items():
        print(key + ': ' + str(value))
    print()

# with general.timing('test'):
#     #r = search_people(client, ldap.filter.filter_format('(&(department=Data- och informationsteknik))', []))
#     r = search_people(client, ldap.filter.filter_format('(&(uid=niklaxe))', []))
#     rtype, rdata, rmsgid, serverctrls = client.result3(r)
#     print(rtype)
#     print('XXX')
#     print(rdata[0])
#     print(rmsgid)
#     print(serverctrls)
#     print(len(rdata))

# CID to email addresses
# Names to CID

#ldap_details = dict()

#ldap_details_by_email_localpart = dict()

# not_found = set()
# for user in c._gitlab_users.values():
#     if not is_bot_user(user):
#         if not (user.username in ldap_details or user.username in ldap_details_by_email_localpart):
#             #print(user.username)
#             r = search_people_by_cid(client, user.username)
#             if len(r) > 1:
#                 print(f'WARNING: more than one LDAP record found for CID {user.usern}')
#             elif len(r) == 1:
#                 ldap_details[user.username] = r[0]
#             else:
#                 r = search_people_by_email_localpart(client, user.username)
#                 if len(r) > 1:
#                     print(f'WARNING: more than one LDAP record found for email localpart {user.username}')
#                 elif len(r) == 1:
#                     ldap_details_by_email_localpart[user.username] = r[0]
#                 else:
#                     print(f'Nothing found for {user.username}')
#                     not_found.add(user.username)



# def g():
#     for group_id in range(45):
#         group = c.group(group_id)

#         def h():
#             for user in c.student_members(group).values():
#                 cid = user.username
#                 yield (cid, search_people_by_cid(client, cid))
#         yield (group.name, dict(h()))


# def h(u, v):
#     for (name, records) in u.items():
#         if name != 'Bora Kocak':
#             continue

#         if len(records) >= 1:
#             continue
#         print()

#         print(name)
#         user_id = c.canvas_course.user_name_to_id[name]
#         group_id = c.canvas_group_set.user_to_group.get(user_id)
#         if group_id is None:
#             print('No group')
#             continue

#         group = c.canvas_group_set.details[group_id]
#         print(group)
#         m = v[group.name]
#         for (cid, records) in m.items():
#             print(cid)
#             if len(records) == 1:
#                 print_record(records[0])
#             elif len(records) == 0:
#                 print('no record')
#             else:
#                 raise ValueError()
    #         print(group_id)
    #         if group_id != None:
    #             print(c.canvas_group_set.details[group_id].name)
    #         for record in records:
    #             print(record)

#r = x.search_st('ou=people,dc=chalmers,dc=se', ldap.SCOPE_SUBTREE, '(cn=Bardha Ahmeti)')
