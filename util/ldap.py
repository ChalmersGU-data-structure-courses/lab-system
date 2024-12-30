# Observations for students of DIT181.
# Inconsistencies between user details on Canvas and in LDAP directory.

# * Users on GitLab may no longer have a CID.
#   Some of my students from DIT181 2021 are examples.
#   Sanna Zakrisson is still listed as a regular student on GU Canvas.
#   And she still has user account sannaza on Chalmers GitLab.
#   But LDAP shows no record of a correponding CID.
#   Other examples:
#   - Aaaa Sssssss, ssssss
#   -

# * Kkkkkkkkkkkkkkkkk Ssssss on GU Canvas has LDAP entry:
#   - uid: mmmmmm
#   - cn: Mmmmmm Sssss
#   - sn: Sssss
#   - givenName: Mmmmmm

# * Ttttttt Aaaaaaaaa Mmmmmmm on GU Canvas has LDAP entry:
#   - uid: ttttttt
#   - cn: Ttttttt Mmmmmmm
#   - sn: Ttttttt
#   - givenName: Ttttttt

# * Kkkkk Jjjjj on GU Canvas has LDAP entry:
#   - uid: ddddd
#   - cn: Ddddd Jjjjj
#   - sn: Jjjjj
#   - givenName: Ddddd

# * Nnnnn Aaaaaaa on GU Canvas has LDAP entry:
#   - uid: aaaaaaa
#   - cn: Mohamad Nnnnn Aaaaaaa
#   - sn: Mohamad Nnnnn Aaaaaaa
#   - givenName: Mmmmmmm Nnnnn

# * Aaaaa Yyyyyy Aaaaaaaaaa on GU Canvas has LDAP entry:
#   - uid: aaaaaaa
#   - cn: Aaaaa Yyyyyy Aaaaaaaaa Aaaaaaaaaa
#   - sn: Yyyyyy Aaaaaaaaa Aaaaaaaaaa
#   - givenName: Aaaaa

# * Bbbb Kkkkk on GU Canvas has LDAP entry:
#   - uid: bbbb
#   - cn: b'Bbbb Kk<non-ascii-codepoints>kk'
#   - sn: b'Kk<non-ascii-codepoints>kk'
#   - givenName: Bbbb

# Typical response for a GU student:
# (
#     "uid=REDACTED,ou=people,dc=chalmers,dc=se",
#     {
#         "objectClass": [
#             b"top",
#             b"person",
#             b"organizationalPerson",
#             b"inetOrgPerson",
#             b"eduPerson",
#             b"norEduPerson",
#         ],
#         "cn": [b"REDACTED REDACTED"],
#         "sn": [b"REDACTED"],
#         "givenName": [b"REDACTED"],
#         "uid": [b"REDACTED"],
#         "mail": [b"REDACTED@student.chalmers.se"],
#         "eduPersonPrimaryAffiliation": [b"student"],
#         "eduPersonAffiliation": [b"student", b"member"],
#     },
# )

import re

import ldap
import ldap.filter


def list_all(client, base, scope, filterstr=None, attrlist=None, page_size=100):
    # Chalmers LDAP has size limit 300.
    page_control = ldap.controls.SimplePagedResultsControl(
        True,
        size=page_size,
        cookie=str(),
    )

    while True:
        response = client.search_ext(
            base,
            scope,
            filterstr=filterstr,
            attrlist=attrlist,
            serverctrls=[page_control],
        )

        (_rtype, rdata, _rmsgid, serverctrls_response) = client.result3(response)
        yield from rdata

        (page_control_response,) = filter(
            lambda control: control.controlType
            == ldap.controls.SimplePagedResultsControl.controlType,
            serverctrls_response,
        )
        page_control.cookie = page_control_response.cookie
        if not page_control.cookie:
            break


# logging.basicConfig()
# logging.getLogger().setLevel(logging.INFO)

# client = ldap.initialize('ldap://ldap.chalmers.se')

# #ldapsearch -x -H ldap://ldap.chalmers.se '(cn=Bbbbbb Aaaaaa)'

# import java_test.gitlab_config as config  # noqa: E402

# c = Course(config)
# a = c._gitlab_users


def is_bot_user(user):
    return any(
        [
            re.fullmatch("project_\\d+_bot\\d*", user.username),
            user.username in ["alert-bot", "support-bot"],
        ]
    )


# Chalmers LDAP has size limit 300.
def search_people(
    client,
    filter_,
    page_control=ldap.controls.SimplePagedResultsControl(
        True,
        size=300,
        cookie="",
    ),
):
    return client.search_ext_s(
        "ou=people,dc=chalmers,dc=se",
        # False positive.
        # pylint: disable=no-member
        ldap.SCOPE_ONELEVEL,
        filter_,
        serverctrls=[page_control],
    )


def search_people_by_cid(client, uid):
    return search_people(client, ldap.filter.filter_format("(uid=%s)", [uid]))


def search_people_by_name(client, cn):
    return search_people(client, ldap.filter.filter_format("(cn=%s)", [cn]))


def search_people_by_email_localpart(client, email_localpart):
    return search_people(
        client, ldap.filter.filter_format("(mail=%s@*)", [email_localpart])
    )


def print_record(record):
    (dn, attrs) = record
    print(dn)
    for key, value in attrs.items():
        print(key + ": " + str(value))
    print()


# with util.general.timing('test'):
#     #r = search_people(client, ldap.filter.filter_format('(&(department=Data- och informationsteknik))', []))
#     r = search_people(client, ldap.filter.filter_format('(&(uid=REDACTED))', []))
#     rtype, rdata, rmsgid, serverctrls = client.result3(r)
#     print(rtype)
#     print('XXX')
#     print(rdata[0])
#     print(rmsgid)
#     print(serverctrls)
#     print(len(rdata))

# CID to email addresses
# Names to CID

# ldap_details = {}

# ldap_details_by_email_localpart = {}

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
#         if name != 'Bbbb Kkkkk':
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

# r = x.search_st('ou=people,dc=chalmers,dc=se', ldap.SCOPE_SUBTREE, '(cn=Bbbbbb Aaaaaa)')
