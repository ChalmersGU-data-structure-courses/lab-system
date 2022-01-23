import itertools
import json
import logging

import ldap

from current_course_prelude import c
import ldap_tools


logger = logging.getLogger(__name__)

def write_to_resolve():
    guid_to_cid = c.config.read_guid_to_cid()
    c.canvas_course_refresh()

    def f():
        for student in c.canvas_course.students:
            if student.integration_id not in guid_to_cid:
                yield student.sis_user_id

    with (c.dir / 'to_resolve.json').open('w') as file:
        json.dump(list(f()), file, indent = 2)

def parse_cid(entry):
    (dn, attributes) = entry
    (cid_raw,) = attributes['uid']
    return cid_raw.decode(encoding = 'ascii')

def compute_guid_to_cid(strict = True):
    client = ldap.initialize('ldap://ldap.chalmers.se')

    def f():
        for student in itertools.chain(c.canvas_course.students, c.canvas_course.teachers):
            cid = c.config.irregular_guid_to_cid.get(student.login_id)
            if cid is None:
                results = ldap_tools.search_people_by_name(client, student.name)
                try:
                    (result,) = results
                except ValueError:
                    logger.error(f'{student.login_id} ({student.name}) has non-unique CID associated with name:')
                    for result in results:
                        logger.error(str(result))
                    if strict:
                        raise
                    continue
                cid = parse_cid(result)
            yield (student.login_id, cid)
    return dict(f())

#c.sync_students_to_gitlab(add = False, remove = False, restrict_to_known = False)
