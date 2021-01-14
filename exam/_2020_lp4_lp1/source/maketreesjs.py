#!/usr/bin/env python3

import sys
import base64

def make_data_uri(file):
    data = open(file, 'rb').read()
    encoded = base64.b64encode(data)
    return "data:image/png;base64," + str(encoded, 'ascii').replace('\n', '')

print("trees = [")
for file in sys.argv[1:]:
    print('    "%s",' % make_data_uri(file))
print("    undefined]")
