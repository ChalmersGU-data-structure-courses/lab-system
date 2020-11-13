
# Auto-grading the labs

If you want to grade all submissions:

1. Collect the students
2. Download and split the submissions
3. Run the test script

If you only have a couple of submissions to grade (e.g., late submissions or resubmissions), then you can replace (2) with:

2 (alt). Download and split manually 


### 1. Collect the students

***Note***: Before you do this you have to get an access token, and the lab group id.
See the files `config.py` and `collect_students_from_canvas.py` for more details.

```
python collect_students_from_canvas.py > labX-students.json
```

This will create the file `labX-students.json`.

### 2. Download and split the submissions

- Go to the lab in Canvas, and click "Download submissions"
- Extract the zip file
- Put the extracted folder in this directory, call it e.g., `labX-raw-submissions`

The split the submissions:

```
python split_submissions.py --users labX-students.json --in labX-raw-submissions --out labX-submissions
```

This will create the folder `labX-submissions`, and inside that one folder per lab group.

### 2 (alt). Download and split manually

If you only have a couple of submissions to grade (e.g., late submissions or resubmissions), then you can do (2) manually:

1. Create a folder `labX-submissions-late` or something.
2. Go to SpeedGrader in Canvas.
3. Locate the submission you want to grade, download all their submitted files (the down-arrow right of the file name).
4. Create a folder `Lab group Y` in the submissions folder, and move the downloaded files there. Make sure to clean all filenames ending with `-1.xxx`, `-2.xxx`, etc. (i.e., remove the `-N` from the filename). Also, make all `.txt` filenames lowercase.
5. Repeat 3–5 for each submission you want to grade.


### 3. Run the test script

```
python autograde_generic_lab.py --users labX-students.json --subs labX-submissions --solution ../LabX-solution/solution/ --skeleton ../LabX --out labX-test-results
```

This will create the folder `labX-results`, and in that folder `index.html` with the results for each submission.
(Plus lots of extra files that are linked from the index file)

The script will do the following:

- check that all required files are submitted, and no other
- compile all Java files and check for compilation errors
- calculate a diff (against the solution) for each submitted file, both in % and as a separate diff file

