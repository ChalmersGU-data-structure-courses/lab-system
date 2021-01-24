from pathlib import Path

this_dir = Path(__file__)
#this_dir = Path()

repo = this_dir / '..' / '..' / '..'

dir = repo / 'Lectures'

for x in list(dir.iterdir()):
    parts = x.name.split(' ')
    subdir = (dir / parts[0]).mkdir(exist_ok = True)
    x.rename(dir / parts[0] / ' '.join(parts[1:]))
