from collections import namedtuple
import cv2
import ffmpeg
import itertools
import math
import numpy
from pathlib import Path, PurePath
import operator
import os
import shlex
import subprocess
import sys
import tempfile

this_dir = Path(__file__).parent
repo = this_dir / '..' / '..'
sys.path.insert(1, str(repo / 'Lab-grading'))
from general import *

# Slow for large masks, should not be done in Python.
def get_rect_from_alpha_mask(mask):
    (y0, x0) = mask.shape
    (x1, y1) = (0, 0)
    for p in cv2.findNonZero(mask):
        x, y = p[0]
        x0 = min(x0, x)
        y0 = min(y0, y)
        x1 = max(x1, x + 1)
        y1 = max(y1, y + 1)
    return ((x0, y0), (x1, y1))

Mask = namedtuple('Mask', ['rect', 'position', 'size', 'mask'])

def get_mask(image):
    r = get_rect_from_alpha_mask(image[:, :, 3])
    ((x0, y0), (x1, y1)) = r
    return Mask(
        rect = r,
        position = (x0, y0),
        size = (x1 - x0, y1 - y0),
        mask = numpy.ascontiguousarray(image[r[0][1]:r[1][1], r[0][0]:r[1][0], 0:3])
    )

def mask_size(mask):
    return memoryview(mask.mask).nbytes

def is_pathlike(s):
    return isinstance(s, str) or isinstance(s, PurePath)

def load_mask(image):
    if is_pathlike(image):
        image = cv2.imread(str(image), cv2.IMREAD_UNCHANGED)
    if not isinstance(image, Mask):
        image = get_mask(image)
    return image

Overlay = namedtuple('Overlay', ['name', 'search', 'replace'])

def load_overlay(dir):
    return Overlay(
        name = dir.name,
        search = load_mask(dir / 'search.png'),
        replace = load_mask(dir / 'replace.png'),
    )

def ffmpeg_get_frame(input, timestamp, output = None):
    with tempfile.TemporaryDirectory() as dir:
        file = output or Path(dir) / 'frame.png'
        ffmpeg.input(input, ss = timestamp).output(str(file), vframes = 1).run()
        image = cv2.imread(str(file))
        return image

def get_mask_image(image, rect):
    ((x0, y0), (x1, y1)) = rect
    output = numpy.zeros(shape = [*image.shape[0:2], 4] , dtype = 'uint8')
    output[y0:y1, x0:x1, 0:3] = image[y0:y1, x0:x1, :]
    output[y0:y1, x0:x1, 3] = 255
    return output

def get_mask_image_from_frame(input, timestamp, rect):
    return get_mask_image(ffmpeg_get_frame(input, timestamp), rect)

# def escape_percent(s):
#     return s.replace('%', '%%')

# def template_path(dir, template_name):
#     return str(Path(escape_percent(str(dir))) / template_name)

def print_similarities_info(similarities, threshold):
    def h(f, g, desc):
        key = operator.itemgetter(1)
        r = f(filter(compose(key, g), enumerate(similarities)), key = key, default = None)
        res = '{} at frame {}'.format(r[1], r[0]) if r else 'none'
        print('{}: {}'.format(desc, res))

    h(max, lambda x: x < threshold, 'Largest similarity below threshold {}'.format(threshold))
    h(min, lambda x: not (x < threshold), 'Smallest similarity not below threshold {}'.format(threshold))

def segments(xs):
    s = None
    for n, v in enumerate(itertools.chain(xs, [False])):
        if v:
            if s == None:
                s = n
        else:
            if s != None:
                yield (s, n)
                s = None

def ffmpeg_pipe(fd):
    return 'pipe:{}'.format(fd)

def ffmpeg_segments_expression(segments):
    return '+'.join('between(n,{},{})'.format(start, end - 1) for start, end in segments) if segments else '0'

def ffmpeg_add_overlays(input, overlay_segments_list, output, quiet = False):
    stream = ffmpeg.input(str(input))
    audio = stream.audio

    def image_writer(file, image):
        def f():
            file.write(memoryview(image))
            file.close()
        return f

    pipe_ins = []
    writers = []
    for overlay, segments in overlay_segments_list:
        mask = overlay.replace
        (r, w) = pipe(mask_size(mask))
        pipe_ins.append(r)
        writers.append(image_writer(os.fdopen(w, 'wb'), mask.mask))
        stream = stream.overlay(
            ffmpeg.input(
                ffmpeg_pipe(r),
                format = 'rawvideo',
                pix_fmt = 'rgb24',
                s='{}x{}'.format(*mask.size)
            ),
            x = mask.position[0],
            y = mask.position[1],
            enable = ffmpeg_segments_expression(segments),
        )

    stream = stream.output(audio, str(output))
    cmd = ffmpeg.compile(stream, overwrite_output = True)
    p = Popen(cmd, pass_fds = pipe_ins, stderr = subprocess.PIPE if quiet else None)

    for writer in writers:
        writer()
    check_process(p)

# def ffmpeg_add_overlays(input, overlay_segments_list, output):
#     stream = ffmpeg.input(input)
#     audio = stream.audio
#     for overlay, segments in overlay_segments_list:
#         stream = stream.overlay(
#             ffmpeg.input(overlay.replace_file),  
#             x = overlay.position[0],
#             y = overlay.position[1],
#             enable = ffmpeg_segments_expression(segments),
#         )
#     stream.output(audio, str(output)).overwrite_output().run()

def mse(image_a, image_b):
    return numpy.sum((image_a.astype("float") - image_b.astype("float")) ** 2) / float(image_a.shape[0] * image_a.shape[1])

def match_with_mask(file, mask):
    while True:
        buffer = file.read(mask_size(mask))
        if not buffer:
            file.close()
            break

        image = numpy.frombuffer(buffer, dtype = 'uint8')
        image = image.reshape((mask.size[1], mask.size[0], 3))

        image = image.astype('uint64')
        numpy.subtract(image, mask.mask, out = image)
        numpy.square(image, out = image)
        yield math.sqrt(float(numpy.sum(image)) / (mask.size[0] * mask.size[1]))

def crop_to_mask(source, mask):
    return source.crop(
        x = mask.position[0],
        y = mask.position[1],
        width = mask.size[0],
        height = mask.size[1],
        exact = 1,
    )

import fcntl

F_GETPIPE_SZ = 1032
F_SETPIPE_SZ = 1031

def ffmpeg_match_overlays(input, overlay_list, quiet = False):
    source = ffmpeg.input(str(input))

    outputs = []
    pipe_outs = []
    matchers = []
    for overlay in overlay_list:
        mask = overlay.search
        (r, w) = pipe(mask_size(mask))
        pipe_outs.append(w)
        matchers.append(match_with_mask(os.fdopen(r, 'rb'), mask))
        outputs.append(
            crop_to_mask(source, mask).output(ffmpeg_pipe(w), format = 'rawvideo', pix_fmt = 'rgb24')
        )

    cmd = ffmpeg.compile(ffmpeg.merge_outputs(*outputs))
    p = Popen(cmd, pass_fds = pipe_outs, stderr = subprocess.PIPE if quiet else None)
    
    r = list(zip(*matchers))
    check_process(p)
    return r

def segments_from_similarities(overlay, similarities, threshold):
    print('similarities for {}:'.format(overlay.name))
    print_similarities_info(similarities, threshold)

    segs = list(segments([s < threshold for s in similarities]))
    print('Computed segments: {}'.format(segs))
    return (overlay, segs)

def process_video(video_file, threshold, output_file):
    print('Processing video file {}...'.format(shlex.quote(str(video_file))))

    r = ffmpeg_match_overlays(video_file, overlay_list)
    num_frames = len(r)
    similarities_list = list(zip(*r))
    print('Found {} frames'.format(num_frames))

    ffmpeg_add_overlays(
        video_file,
        map(lambda x: segments_from_similarities(*x, threshold), zip(overlay_list, similarities_list)),
        output_file)
    print('Output written to {}.'.format(shlex.quote(str(output_file))))
    print()

def load_overlay_list(dir):
    for file in dir.iterdir():
        if file.is_dir():
            yield load_overlay(file)

# position and size are for the webcam video that should be copies from the original recording
# You can supply a starting time string for the slides video.
def replace_slides_video(output, input_recording, input_slides, position, size, slides_starting_time = '0'):
    slides = ffmpeg.input(str(input_slides), ss = slides_starting_time)
    recording = ffmpeg.input(str(input_recording))

    audio = recording.audio

    (x, y) = position
    (sx, sy) = size

    webcam = recording.crop(x, y, sx, sy)
    video = slides.overlay(webcam, x = x, y = y, eof_action = 'endall')

    ffmpeg.output(video, audio, str(output)).run()

# Usage: change below as required

lectures = repo / '..' / 'Lectures'

#dir_overlays = 'nick'
#dir_overlays = 'peter-2020-11-10-A'
dir_overlays = 'peter-2020-11-10-B'

overlay_list = list(load_overlay_list(this_dir / dir_overlays))

print('Found the following overlays:')
for overlay in overlay_list:
    print('* {}'.format(shlex.quote(overlay.name)))
print()

# This seems to be a reasonable threshold for sqrt(MSE) detection
threshold = 40

#for date in ['2020-11-02', '2020-11-03', '2020-11-05']:
#    for file in list((lectures / date).iterdir()):
#        if file.suffix == '.mp4':
#            output_file = with_stem(file, file.stem + '-overlaid')
#            process_video(file, threshold, output_file)

for date in ['2020-11-10']:
    for file in list((lectures / date).iterdir()):
        if file.suffix == '.mp4' and file.name.startswith('B'):
            output_file = with_stem(file, file.stem + '-overlaid')
            process_video(file, threshold, output_file)
