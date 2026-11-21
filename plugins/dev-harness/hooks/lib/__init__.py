"""Pure helpers shared by the hook scripts one directory up: stdlib only, no I/O.

A helper stays private to its script until a second script needs it, then moves here.
A hook runs as `python3 hooks/<name>.py`, so `hooks/` is sys.path[0] and `lib` resolves
from any working directory.
"""
