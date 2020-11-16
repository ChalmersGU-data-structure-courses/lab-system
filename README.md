
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
python collect_students_from_canvas.py > students.json
```

This will create the file `students.json`.

### 2. Download and split the submissions

- Go to the lab in Canvas, and click "Download submissions"
- Extract the zip file
- Put the extracted folder in this directory, call it e.g., `labX-raw-submissions`

The split the submissions:

```
python split_submissions.py --students students.json \
    --in labX/raw-submissions --out labX/submissions
```

This will create the folder `labX/submissions` (provided `labX` exists), and inside that one folder per lab group.

### 2 (alt). Download and split manually

If you only have a couple of submissions to grade (e.g., late submissions or resubmissions), then you can do (2) manually:

1. Create a folder `labX/submissions-late` or something.
2. Go to SpeedGrader in Canvas.
3. Locate the submission you want to grade, download all their submitted files (the down-arrow right of the file name).
4. Create a folder `Lab group Y` in the submissions folder, and move the downloaded files there. Make sure to clean all filenames ending with `-1.xxx`, `-2.xxx`, etc. (i.e., remove the `-N` from the filename). Also, make all `.txt` filenames lowercase.
5. Repeat 3–5 for each submission you want to grade.


### 3. Run the autograding script

```
python autograde.py --students students.json \
    --submissions labX/submissions \
    --solution ../LabX-solution/solution \
    --skeleton ../LabX \
    --out labX/results
```

This will create the folder `labX/results`, and in that folder `index.html` with the results for each submission.
(Plus lots of extra files that are linked from the index file)

The script will do the following:

- check that all required files are submitted, and no other
- compile all Java files and check for compilation errors
- calculate a diff (against the solution) for each submitted file, both in % and as a separate diff file

#### 3b. Autograde with test cases

If you have test cases, you must put them in a python file and provide to the autograder:

```
python autograde.py --students students.json \
    --submissions labX/submissions \
    --solution ../LabX-solution/solution \
    --skeleton ../LabX \
    --testfile ../LabX-solution/tests/tests.py \
    --out labX/results
```

The folder that contains the python file must also contain gold output files – text files called `*.gold`. Then the output files from running the tests are compared with the gold outputs. 

Your script file must have this structure:

```
tests = {}
tests["outfile-1.out"] = "java MainJavaClass some arguments ..."
tests["outfile-2.out"] = "java MainJavaClass some other arguments ..."
```

This will produce the two output files `outfile-{1,2}.out`, which are then compared with the files `outfile-{1,2}.out.gold` in the script folder.


#### 3c. Autograde resubmissions

If you have resubmissions, the script can compare them with the previous submissions:

```
python autograde.py --students students.json \
    --submissions labX/submissions-new \
    --previous labX/submissions-old \
    --solution ../LabX-solution/solution \
    --skeleton ../LabX \
    --out labX/results
```
