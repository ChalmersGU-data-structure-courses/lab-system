# Suggestions from TAs

1. As a small comment on the grading procedure. I think our
   performance will increase if there was a link on the canvas current
   submission sheet that directly created a new issue on the gitlab repo
   with the handlers for the students in the comments part and the title
   already partially filled in Grading for.
   
   * [Christian]
	 We can give a link to the "new issue" page of the group in the live submissions table.
	 
	 The issue template is a nice idea, but I don't know how to do that.
	 GitLab has a feature where issue templates ("description templates")
	 can be configured via a folder .gitlab in the default branch of a repository.
	 But this would be editable by the students (unless we protect the default branch with high
	 access rights and make them work on a separate branch, but that's too inconvenient for them).

	 The premium version of GitLab has group-level templates.
	 That would be a solution: we could use a project in the group
	 as template source that the students don't have access to.

	 For the notifications to the students, it should be possible for the script
	 to post a comment mentioning the students. However, whichever user runs
	 the script will then have their GitLab notifications be made worthless
	 as GitLab will think they participated in every thread.

   * [Christian]
     I found a way to do it using GET URL parameters!
	 Added "open issue" links to the live submissions.
	 These retrieve default content from a template issue in the official grading repository of the lab.

2. All labs should have some automatic tests:
   Maybe for next iteration there should be, I am grading a group
   whose code doesn't compile and is a bit hard to spot by just
   looking. (They use medianOfThree with three arguments not four)
   
   * [Christian]
	 We can check that the code compiles.
	 It hasn't been integrated in the current submissions table yet.
	 But how should compile errors and warnings be displayed?
	 
	 - We could create a file or issue in the grading repository in link to that.
	 - We could embed the compiler output via a toggle.
	   That might screw up the table layout.
