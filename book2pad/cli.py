"""Command-line interface. Run without arguments to open the GUI."""
import argparse
import os
import shutil
import sys
import threading

from book2pad import __version__
from book2pad.core import Book2PadError, Library, Status, collect_books, transfer


def build_parser():
    parser = argparse.ArgumentParser(
        prog='book2pad', description='Transfer PDF/EPUB books to an iPad. '
        'Run without arguments to open the graphical interface.')
    parser.add_argument('-d', '--ipad', dest='mount', default=os.getcwd(),
                        help='where the iPad is mounted (default: current directory)')
    parser.add_argument('-b', '--book', dest='books', nargs='+', action='extend',
                        help='books or directories to transfer; a book\'s parent '
                             'directory name is used as its genre')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='report every book, not just a summary')
    parser.add_argument('--gui', action='store_true', help='open the graphical interface')
    parser.add_argument('--version', action='version', version='%(prog)s ' + __version__)
    return parser


def run_cli(args):
    try:
        library = Library(args.mount)
    except Book2PadError as e:
        sys.exit('book2pad: %s' % e)

    books = collect_books(args.books)
    if not books:
        sys.exit('book2pad: no PDF or EPUB files found')

    width = max(20, shutil.get_terminal_size().columns - 30)

    def progress(i, total, path, result):
        if result is None:
            if not args.verbose:
                done = int(width * i / total)
                sys.stdout.write('\r[%s%s] %d/%d' % ('=' * done, ' ' * (width - done), i, total))
                sys.stdout.flush()
        elif args.verbose:
            note = result.status.value + (': ' + result.message if result.message else '')
            print('%s  [%s]' % (path, note))

    print('Transferring %d book(s) to %s' % (len(books), library.mount))
    cancel = threading.Event()
    try:
        summary = transfer(library, books, progress, cancel)
    except KeyboardInterrupt:
        sys.exit('\nInterrupted; library saved with the books completed so far.')
    except Book2PadError as e:
        sys.exit('\nbook2pad: %s' % e)

    if not args.verbose:
        print('\r[%s] %d/%d' % ('=' * width, len(books), len(books)))
    print('Finished: ' + summary.describe())
    for r in summary.results:
        if r.status is Status.FAILED:
            print('  failed: %s (%s)' % (r.path, r.message))


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.gui or not args.books:
        try:
            from book2pad.gui import main as gui_main
        except ImportError as e:
            sys.exit('book2pad: the GUI needs Tkinter (%s).\nInstall it (e.g. "pacman -S tk" '
                     'or "apt install python3-tk"), or use -b to transfer from the '
                     'command line.' % e)
        gui_main(None if args.mount == os.getcwd() else args.mount)
    else:
        run_cli(args)


if __name__ == '__main__':
    main()
