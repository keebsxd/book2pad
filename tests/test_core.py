import os
import plistlib
import tempfile
import threading
import unittest
import zipfile

from book2pad.core import (Library, NotAnIPadError, Status, collect_books,
                           read_book_info, transfer)

CONTAINER = ('<?xml version="1.0"?><container version="1.0" '
             'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
             '<rootfile full-path="OEBPS/content.opf" '
             'media-type="application/oebps-package+xml"/></rootfiles></container>')


def make_epub(path, title, author):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('mimetype', 'application/epub+zip')
        z.writestr('META-INF/container.xml', CONTAINER)
        z.writestr('OEBPS/content.opf', (
            '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
            'version="2.0"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            '<dc:title>%s</dc:title><dc:creator>%s</dc:creator></metadata></package>')
            % (title, author))


def make_pdf(path, body=b''):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(b'%PDF-1.4\n' + body)


class TransferTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.ipad = os.path.join(self.root, 'ipad')
        self.dest = os.path.join(self.ipad, 'Books', 'Purchases')
        os.makedirs(self.dest)
        self.lib = os.path.join(self.root, 'lib')
        self.epub = os.path.join(self.lib, 'Fiction', 'dune.epub')
        self.pdf = os.path.join(self.lib, 'Science', 'Cosmos-Carl Sagan.pdf')
        make_epub(self.epub, 'Dune', 'Frank Herbert')
        make_pdf(self.pdf)

    def tearDown(self):
        self.tmp.cleanup()

    def run_transfer(self, paths, **kw):
        return transfer(Library(self.ipad), collect_books(paths), **kw)

    def statuses(self, summary):
        return {os.path.basename(r.path): r.status for r in summary.results}

    def records(self):
        return Library(self.ipad).books

    def test_not_an_ipad(self):
        with self.assertRaises(NotAnIPadError):
            Library(self.lib)

    def test_metadata(self):
        info = read_book_info(self.epub)
        self.assertEqual((info.title, info.author, info.genre), ('Dune', 'Frank Herbert', 'Fiction'))
        info = read_book_info(self.pdf)
        self.assertEqual((info.title, info.author, info.genre), ('Cosmos', 'Carl Sagan', 'Science'))

    def test_author_heuristic(self):
        long_name = os.path.join(self.lib, 'Classics', 'crime.epub')
        make_epub(long_name, 'Crime and Punishment', 'Fyodor Dostoyevsky')
        self.assertEqual(read_book_info(long_name).author, 'Fyodor Dostoyevsky')
        garbled = os.path.join(self.lib, 'X', 'Title-Real Author.epub')
        make_epub(garbled, 'Title', 'A1B2C3D4E5F6G7')
        self.assertEqual(read_book_info(garbled).author, 'Real Author')

    def test_new_then_skip_then_update(self):
        s = self.run_transfer([self.lib])
        self.assertEqual(set(self.statuses(s).values()), {Status.NEW})
        self.assertTrue(os.path.isdir(os.path.join(self.dest, 'dune.epub', 'OEBPS')))
        self.assertTrue(os.path.isfile(os.path.join(self.dest, 'Cosmos-Carl Sagan.pdf')))
        rec = self.records()['dune.epub']
        self.assertEqual((rec['Name'], rec['Artist'], rec['Genre']), ('Dune', 'Frank Herbert', 'Fiction'))

        s = self.run_transfer([self.lib])
        self.assertEqual(set(self.statuses(s).values()), {Status.EXISTS})

        make_pdf(self.pdf, b'changed')
        s = self.run_transfer([self.pdf], overrides={self.pdf: {'genre': 'Space'}})
        self.assertEqual(self.statuses(s)['Cosmos-Carl Sagan.pdf'], Status.UPDATED)
        self.assertEqual(self.records()['Cosmos-Carl Sagan.pdf']['Genre'], 'Space')

        s = self.run_transfer([self.epub], overrides={self.epub: {'title': 'Dune (1965)'}})
        self.assertEqual(self.statuses(s)['dune.epub'], Status.METADATA)
        self.assertEqual(self.records()['dune.epub']['Name'], 'Dune (1965)')
        self.assertEqual([n for n in os.listdir(self.dest) if 'partial' in n], [])

    def test_binary_plist_preserved_and_foreign_kept(self):
        plist = os.path.join(self.dest, 'Purchases.plist')
        foreign = [{'Name': 'Store book', 'Path': ''}, {'Name': 'Weird', 'Path': '..'}]
        with open(plist, 'wb') as f:
            plistlib.dump({'Books': foreign}, f, fmt=plistlib.FMT_BINARY)
        self.run_transfer([self.epub])
        with open(plist, 'rb') as f:
            self.assertTrue(f.read().startswith(b'bplist'))
        with open(plist, 'rb') as f:
            names = [b['Name'] for b in plistlib.load(f)['Books']]
        self.assertEqual(sorted(names), ['Dune', 'Store book', 'Weird'])

    def test_remove_never_escapes_purchases(self):
        self.run_transfer([self.lib])
        lib = Library(self.ipad)
        for bad in ('', '.', '..', 'Purchases.plist'):
            lib.remove(bad, delete_file=True)
        self.assertTrue(os.path.isdir(self.dest))
        lib.remove('dune.epub')
        lib.save()
        self.assertFalse(os.path.exists(os.path.join(self.dest, 'dune.epub')))
        self.assertEqual(list(self.records()), ['Cosmos-Carl Sagan.pdf'])

    def test_duplicate_filenames_and_bad_files(self):
        other = os.path.join(self.lib, 'Other', 'dune.epub')
        make_epub(other, 'Not Dune', 'Someone')
        txt = os.path.join(self.lib, 'notes.txt')
        open(txt, 'w').close()
        missing = os.path.join(self.lib, 'gone.pdf')
        s = transfer(Library(self.ipad), [self.epub, other, txt, missing])
        st = [r.status for r in s.results]
        self.assertEqual(st, [Status.NEW, Status.FAILED, Status.UNSUPPORTED, Status.FAILED])
        self.assertEqual(self.records()['dune.epub']['Name'], 'Dune')

    def test_cancel(self):
        cancel = threading.Event()
        cancel.set()
        s = self.run_transfer([self.lib], cancel=cancel)
        self.assertTrue(s.cancelled)
        self.assertEqual(s.results, [])


if __name__ == '__main__':
    unittest.main()
