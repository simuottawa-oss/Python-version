"""Source launcher and PyInstaller entry point."""

import sys
import multiprocessing



if __name__ == "__main__":
    multiprocessing.freeze_support()
    from simuo.app import main
    sys.exit(main())
