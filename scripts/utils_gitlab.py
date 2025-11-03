import gitlab

def get_group_id(gl, lab_number):
    lab_full_path = f"courses/data-structures/lp2/2024/lab-{lab_number}"
    groups = gl.groups.list(iterator=True)
    print(lab_full_path, len(groups))
    for group in groups:
        if lab_full_path == group.full_path:
            return group.id
    raise Exception("The gitlab path format changed.")

# To check if there are protected main branches
def check_protected_main_branches(gl, lab_number):
    try:
        group = gl.groups.get(f"courses/data-structures/lp2/2024/lab-{lab_number}")
    except:
        raise Exception("The lab does not exist or the name has a different format")
    projects = group.projects.list(as_list=False)
    n_pages = projects.total_pages
    print(f"Pages: {n_pages}")
    res = {}
    for page in range(n_pages):
        print(f"Checking page {page}")
        projects = group.projects.list(page=page)
        for p in projects:
            project = gl.projects.get(p.id)
            protected_branches = project.protectedbranches.list(iterator=True)
            branches = [e.name for e in protected_branches]
            if "main" in branches and "primary" not in project.web_url:
                res[project.web_url] = branches
    return res

# To check who has worked on the lab
def check_commits_tags(gl, lab_number):
    try:
        group = gl.groups.get(f"courses/data-structures/lp2/2024/lab-{lab_number}")
    except:
        raise Exception("The lab does not exist or the name has a different format")
    projects = group.projects.list(as_list=False)
    n_pages = projects.total_pages
    # print(f"Pages: {n_pages}")
    total, n_commits, n_tags = len(projects), 0, 0
    for page in range(n_pages):
        # print(f"Checking page {page}")
        projects = group.projects.list(page=page)
        for p in projects:
            project = gl.projects.get(p.id)
            # print(p.name)
            if "lab" in p.name:
                commits = project.commits.list(iterator=True)
                # print(commits); return
                tags = project.tags.list(iterator=True)
                tags = [t.name for t in tags]
                test_tags = {t for t in tags if t.lower().startswith("test")}
                sub_tags = {t for t in tags if t.lower().startswith("submission")}
                other_tags = {t for t in tags if t not in test_tags and t not in sub_tags}
                if len(commits) >= 1:
                    n_commits += 1
                if len(tags) >= 1:
                    n_tags += 1
                if True or other_tags or (bool(sub_tags) != bool(test_tags)) or len(test_tags) > 5:
                    # name_pos = p.name.find("Lab-group")
                    # group_name = p.name[name_pos:]
                    group_name = p.name
                    print(
                        f"{group_name:20s} {len(test_tags):2d} tests   {len(sub_tags):d} submissions" +
                        (f"  + {len(other_tags):2d} error tags: " + ", ".join(sorted(other_tags)) if other_tags else "")
                    )
    return n_commits, n_tags, total
            
