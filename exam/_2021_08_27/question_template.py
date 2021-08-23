# To write a generator for question N, copy this file to questionN.py in the same directory and fill out the below class.
# import pathlib
import random
# import tempfile

class Generator:
    # Use 'seed' to initialize random number generation.
    # For pregenerated problems, use the version number (ranges from 0 to number of versions) to select the problem.
    def __init__(self, seed, version = None):
        self.r = random.Random(seed)
        self.version = version

    # A generator function returning key-value string replacement pairs.
    # The boolean parameter 'solution' indicates if this is for the exam or solution document.
    # This function is called only once per class instance, so it is safe to mutate self.r.
    def replacements(self, solution = False):
        yield ('key_0', 'A') # Replaces '{{QN:key_0}}' by 'A'
        yield ('key_1', 'B')
        if solution:
            yield ('key_solution_0', 'B')

    # Implement this generator function to replace placeholder images in the exam or solution document by generated images.
    # Parameters are as for the method 'replacements'.
    # Yield key-value pairs of a string id of the placeholder image and the local path to an image to replace it.
    # The caller takes ownership of the image and will delete it.
    #
    # Supported image formats are PNG, JPEG, GIF.
    # The Google Docs API says:
    # > Scales and centers the image to fill the bounds of the original image.
    # > The image may be cropped in order to fill the original image's bounds.
    # > The rendered size of the image will be the same as that of the original image.  
    # def replacements_img(self, solution = False):
    #     (fd, name) = tempfile.mkstemp(suffix = '.png')
    #     os.close(fd)
    #     path = pathlib.Path(name)
    #
    #     # generate custom image and store it under 'path'
    #
    #     yield ('kix.gq7jtslsbc2f', path) # replace id by actual id
