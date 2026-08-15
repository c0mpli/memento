#!/usr/bin/env python3
"""Root entrypoint so `git clone`d users can run without installing:

    python main.py init
    python main.py start

Installed users get the same via the `memento` command (see pyproject scripts).
"""

import sys

from memento.cli import main

if __name__ == "__main__":
    sys.exit(main())
