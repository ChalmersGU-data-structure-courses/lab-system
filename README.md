
# Auto-grading the labs

Do the following, in order:

### Download the submissions

- Go to the lab in Canvas, and click "Download submissions"
- Extract the zip file
- Put the extracted folder in this directory, call it e.g., `labX-raw-submissions`

### Collect the students

***Note***: Before you do this you have to get an access token, and the lab group id.
See the file `collect_students_from_canvas.py` for more details.


```
python collect_students_from_canvas.py > labX-students.json
```

This will create the file `labX-students.json`.

### Split the submissions

```
python split_submissions.py --users labX-students.json --in labX-raw-submissions --out labX-submissions
```

This will create the folder `labX-submissions`, and inside that one folder per lab group.

### Run the test script

```
python test_lab.py --subs labX-submissions --solution ../LabX-solution/solution/ --skeleton ../LabX --out labX-results
```

This will create the folder `labX-results`, and in that folder `index.html` with the results for each submission.
(Plus lots of extra files that are linked from the index file)

The script will do the following:

- check that all required files are submitted, and no other
- compile all Java files and check for compilation errors
- calculate a diff (against the solution) for each submitted file, both in % and as a separate diff file

