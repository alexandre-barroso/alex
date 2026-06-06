#!/usr/bin/env python3
"""Strip empty and whitespace-only CTM lines from standard input."""

import sys

lines = [ line.strip() for line in sys.stdin if line.strip() != "" ]
for line in lines:
    sys.stdout.write(f"{line}\n")
sys.stdout.flush()
