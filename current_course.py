import json

from current_course_prelude import c, file_guid_to_cid

for s in c.canvas_course.students:
    print(s.name)
    print(s.integration_id)
    print(s.sis_user_id)
    print()

def read_guid_to_cid():
    with file_guid_to_cid.open() as file:
        return json.load(file)

def write_guid_to_cid(u):
    with file_guid_to_cid.open('w') as file:
        return json.dump(u, file)

def write_to_resolve():
    guid_to_cid = read_guid_to_cid()
    c.canvas_course_refresh()

    def f():
        for student in c.canvas_course.students:
            if student.integration_id not in guid_to_cid:
                yield student.sis_user_id

    with (c.dir / 'to_resolve.json').open('w') as file:
        json.dump(list(f()), file, indent = 2)

l = c.labs[1]

c.sync_students_to_gitlab(remove = False)
