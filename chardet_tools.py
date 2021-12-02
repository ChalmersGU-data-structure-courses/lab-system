from pathlib import Path

import chardet


# Detection seems not to be so good.
# A Unicode file with 'Markus Järveläinen' is detected as EUC-KR.
def detect_encoding(files):
    detector = chardet.universaldetector.UniversalDetector()
    for file in files:
        if isinstance(file, str):
            file = Path(file)
        detector.feed(file.read_bytes())
    detector.close()
    return detector.result['encoding']

def read_text_detect_encoding(path):
    try:
        return path.read_text()
    except UnicodeDecodeError:
        return path.read_text(encoding=detect_encoding([path]))
