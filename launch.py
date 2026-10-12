#!/usr/bin/env python3
"""Run book2pad from a checkout without installing it.

    ./launch.py                  # open the GUI
    ./launch.py -d /media -b ~/books   # command line
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from book2pad.cli import main  # noqa: E402

main()
