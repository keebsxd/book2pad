"""Core logic for transferring PDF/EPUB books into an iPad's iBooks library.

Everything here is UI-agnostic: the CLI and GUI both drive :class:`Library`
and :func:`transfer`, receiving progress through a callback.
"""
import enum
import hashlib
import os
import plistlib
import re
import shutil
import threading
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field

PLIST_REL = os.path.join('Books', 'Purchases', 'Purchases.plist')
SUPPORTED_EXTS = ('.pdf', '.epub')
PARTIAL_SUFFIX = '.book2pad-partial'


class Book2PadError(Exception):
    pass


class NotAnIPadError(Book2PadError):
    pass


# --------------------------------------------------------------------------
# Book metadata
# --------------------------------------------------------------------------

@dataclass
class BookInfo:
    path: str
    title: str = ''
    author: str = ''
    genre: str = ''
    hash: str = ''

    @property
    def filename(self):
        return os.path.basename(self.path)

    @property
    def ext(self):
        return os.path.splitext(self.path)[1].lower()


def hash_md5(path):
    md5 = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            md5.update(chunk)
    return md5.hexdigest().upper()


def parse_filename(path):
    """Fall back to the recommended ``title-author.ext`` naming scheme."""
    stem = os.path.splitext(os.path.basename(path))[0]
    if '-' in stem:
        title, author = stem.rsplit('-', 1)
        return title.strip() or stem, author.strip()
    return stem, ''


def _epub_metadata(path):
    ns = {'c': 'urn:oasis:names:tc:opendocument:xmlns:container',
          'dc': 'http://purl.org/dc/elements/1.1/'}
    with zipfile.ZipFile(path) as z:
        container = ET.fromstring(z.read('META-INF/container.xml'))
        rootfile = container.find('.//c:rootfile', ns)
        opf = ET.fromstring(z.read(rootfile.get('full-path')))
    title = opf.find('.//dc:title', ns)
    creators = [c.text.strip() for c in opf.findall('.//dc:creator', ns) if c.text]
    return (title.text.strip() if title is not None and title.text else '',
            ', '.join(creators))


def _pdf_metadata(path):
    try:
        from pypdf import PdfReader  # optional dependency
    except ImportError:
        return '', ''
    meta = PdfReader(path).metadata or {}
    return (str(meta.get('/Title') or '').strip(),
            str(meta.get('/Author') or '').strip())


def _looks_garbled(author):
    # Long letter+digit runs (e.g. "A1B2C3D4E5F6") are IDs, not names.
    return bool(re.search(r'(?=[A-Za-z]*\d)(?=\d*[A-Za-z])[A-Za-z0-9]{11,}', author))


def read_book_info(path, with_hash=True):
    """Read title/author from metadata, falling back to the filename.

    The genre is taken from the name of the book's parent directory.
    """
    path = os.path.abspath(path)
    info = BookInfo(path=path, genre=os.path.basename(os.path.dirname(path)))
    title = author = ''
    try:
        if info.ext == '.epub':
            title, author = _epub_metadata(path)
        elif info.ext == '.pdf':
            title, author = _pdf_metadata(path)
    except Exception:
        pass  # unreadable metadata just means we use the filename
    fn_title, fn_author = parse_filename(path)
    if _looks_garbled(author):
        author = ''
    title, author = title or fn_title, author or fn_author
    info.title, info.author = title, author
    if with_hash:
        info.hash = hash_md5(path)
    return info


def collect_books(paths):
    """Expand files and directories into a sorted list of supported books."""
    books = []
    for p in paths:
        p = os.path.abspath(os.path.expanduser(p))
        if os.path.isdir(p):
            for cur, _dirs, files in os.walk(p):
                books += [os.path.join(cur, f) for f in files
                          if f.lower().endswith(SUPPORTED_EXTS)]
        else:
            books.append(p)
    return sorted(dict.fromkeys(books))


# --------------------------------------------------------------------------
# The iPad side: Purchases.plist
# --------------------------------------------------------------------------

def _safe_name(path):
    """Basename of a library entry's Path, or None if it can't be a book file."""
    name = os.path.basename(str(path).rstrip('/'))
    return name if name not in ('', '.', '..', os.path.basename(PLIST_REL)) else None


def check_mount(mount):
    purchases = os.path.join(mount, 'Books', 'Purchases')
    for p in (os.path.join(mount, 'Books'), purchases):
        if not os.path.isdir(p):
            raise NotAnIPadError('Not an iPad mount point (missing %s)' % p)


class Library:
    """The iBooks library on a mounted iPad, keyed by book filename."""

    def __init__(self, mount):
        self.mount = os.path.abspath(mount)
        check_mount(self.mount)
        self.plist_path = os.path.join(self.mount, PLIST_REL)
        self.dest = os.path.dirname(self.plist_path)
        self.fmt = plistlib.FMT_XML
        self.tree = {'Books': []}
        self.books = {}
        self.load()

    def load(self):
        self.tree = {'Books': []}
        if os.path.isfile(self.plist_path):
            with open(self.plist_path, 'rb') as f:
                data = f.read()
            if data:
                if data.startswith(b'bplist'):
                    self.fmt = plistlib.FMT_BINARY
                try:
                    self.tree = plistlib.loads(data)
                except Exception as e:
                    raise Book2PadError('Cannot read %s: %s' % (self.plist_path, e))
        self.books = {}
        self.foreign = []  # entries we can't key by filename; kept untouched
        for b in self.tree.get('Books', []):
            name = _safe_name(b.get('Path', '')) if isinstance(b, dict) else None
            if name:
                self.books[name] = b
            else:
                self.foreign.append(b)

    def save(self):
        self.tree['Books'] = list(self.books.values()) + self.foreign
        tmp = self.plist_path + PARTIAL_SUFFIX
        try:
            with open(tmp, 'wb') as f:
                plistlib.dump(self.tree, f, fmt=self.fmt)
            os.replace(tmp, self.plist_path)
        except OSError as e:
            raise Book2PadError(
                'Could not write the iBooks library (%s). Close iBooks on the '
                'iPad, keep it connected and try again.' % e)

    def get(self, filename):
        return self.books.get(filename)

    def is_current(self, info):
        rec = self.get(info.filename)
        return bool(rec) and (rec.get('Package Hash'), rec.get('Name'),
                              rec.get('Artist'), rec.get('Genre')) == \
            (info.hash, info.title, info.author, info.genre)

    def add(self, info):
        self.books[info.filename] = {
            'Name': info.title or os.path.splitext(info.filename)[0],
            'Artist': info.author,
            'Genre': info.genre,
            'Path': info.filename,
            'Package Hash': info.hash,
            'Inserted-By-iBooks': False,
        }

    def remove(self, filename, delete_file=True):
        rec = self.books.pop(filename, None)
        if rec and delete_file and _safe_name(filename) == filename:
            _rm(os.path.join(self.dest, filename))
        return rec

    def cleanup_partials(self):
        for name in os.listdir(self.dest):
            if name.endswith(PARTIAL_SUFFIX):
                _rm(os.path.join(self.dest, name))


def _rm(path):
    if os.path.isdir(path):
        shutil.rmtree(path)
    elif os.path.lexists(path):
        os.remove(path)


# --------------------------------------------------------------------------
# Transferring
# --------------------------------------------------------------------------

class Status(enum.Enum):
    NEW = 'new'
    UPDATED = 'updated'
    METADATA = 'metadata updated'
    EXISTS = 'already on iPad'
    UNSUPPORTED = 'unsupported file'
    FAILED = 'failed'

    @property
    def ok(self):
        return self in (Status.NEW, Status.UPDATED, Status.METADATA)


@dataclass
class Result:
    path: str
    status: Status
    message: str = ''


@dataclass
class Summary:
    results: list = field(default_factory=list)
    cancelled: bool = False

    def count(self, ok):
        return sum(1 for r in self.results if r.status.ok == ok)

    def describe(self):
        present = sum(1 for r in self.results if r.status is Status.EXISTS)
        return '%d transferred, %d already on iPad, %d skipped or failed' % (
            self.count(True), present, self.count(False) - present)


def _install(info, dest):
    """Copy a PDF, or unpack an EPUB, into place atomically."""
    final = os.path.join(dest, info.filename)
    tmp = final + PARTIAL_SUFFIX
    _rm(tmp)
    try:
        if info.ext == '.pdf':
            shutil.copyfile(info.path, tmp)
        else:
            with zipfile.ZipFile(info.path) as z:
                z.extractall(tmp)
        _rm(final)
        os.replace(tmp, final)
    finally:
        _rm(tmp)


def transfer_one(library, info):
    """Transfer a single book; ``info`` must include its hash."""
    if info.ext not in SUPPORTED_EXTS:
        return Result(info.path, Status.UNSUPPORTED)
    if not os.path.isfile(info.path):
        return Result(info.path, Status.FAILED, 'file not found')
    if library.is_current(info):
        return Result(info.path, Status.EXISTS)
    old = library.get(info.filename)
    on_disk = os.path.exists(os.path.join(library.dest, info.filename))
    if old and old.get('Package Hash') == info.hash and on_disk:
        status = Status.METADATA  # same file, only title/author/genre changed
    else:
        _install(info, library.dest)
        status = Status.UPDATED if old else Status.NEW
    library.add(info)
    return Result(info.path, status)


def transfer(library, books, progress=None, cancel=None, overrides=None):
    """Transfer ``books`` (paths) into ``library`` and save the plist.

    progress(index, total, path, result_or_None) is called before (result is
    None) and after each book. ``cancel`` is an optional threading.Event.
    ``overrides`` maps a path to a dict of title/author/genre to use instead
    of the detected metadata.
    """
    cancel = cancel or threading.Event()
    overrides = overrides or {}
    summary = Summary()
    total = len(books)
    seen = {}  # filename -> path; the iPad stores books by filename only
    try:
        for i, path in enumerate(books):
            if cancel.is_set():
                summary.cancelled = True
                break
            if progress:
                progress(i, total, path, None)
            name = os.path.basename(path)
            try:
                if not path.lower().endswith(SUPPORTED_EXTS):
                    result = Result(path, Status.UNSUPPORTED)
                elif not os.path.isfile(path):
                    result = Result(path, Status.FAILED, 'file not found')
                elif name in seen:
                    result = Result(path, Status.FAILED, 'same filename as %s; rename one'
                                    % seen[name])
                else:
                    seen[name] = path
                    info = read_book_info(path)
                    for k, v in overrides.get(path, {}).items():
                        setattr(info, k, v)
                    result = transfer_one(library, info)
            except Exception as e:
                result = Result(path, Status.FAILED, str(e))
            summary.results.append(result)
            if progress:
                progress(i + 1, total, path, result)
    finally:
        try:
            library.cleanup_partials()
        except OSError:
            pass
        library.save()
    return summary
