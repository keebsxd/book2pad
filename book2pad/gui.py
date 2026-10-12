"""Tkinter GUI for book2pad."""
import os
import queue
import shutil
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from book2pad import __version__
from book2pad.core import (Book2PadError, Library, Status, collect_books, read_book_info,
                           transfer)

DEFAULT_MOUNT = os.path.expanduser('~/ipad')
FIELDS = ('title', 'author', 'genre')


class EditDialog(tk.Toplevel):
    """Edit title/author/genre. With several books, blank fields are left alone."""

    def __init__(self, parent, values, multiple):
        super().__init__(parent)
        self.title('Edit %s' % ('books' if multiple else 'book'))
        self.transient(parent)
        self.resizable(False, False)
        self.result = None
        self.vars = {}
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill='both', expand=True)
        for row, name in enumerate(FIELDS):
            ttk.Label(frame, text=name.capitalize() + ':').grid(row=row, column=0, sticky='w', pady=3)
            var = self.vars[name] = tk.StringVar(value=values.get(name, ''))
            entry = ttk.Entry(frame, textvariable=var, width=45)
            entry.grid(row=row, column=1, sticky='ew', pady=3)
            if row == 0:
                entry.focus_set()
        if multiple:
            ttk.Label(frame, text='Blank fields are left unchanged.', foreground='gray') \
                .grid(row=3, column=0, columnspan=2, sticky='w', pady=(6, 0))
        buttons = ttk.Frame(frame)
        buttons.grid(row=4, column=0, columnspan=2, sticky='e', pady=(10, 0))
        ttk.Button(buttons, text='Cancel', command=self.destroy).pack(side='right')
        ttk.Button(buttons, text='OK', command=self.ok).pack(side='right', padx=6)
        self.bind('<Return>', lambda e: self.ok())
        self.bind('<Escape>', lambda e: self.destroy())
        self.wait_visibility()
        self.grab_set()
        parent.wait_window(self)

    def ok(self):
        self.result = {k: v.get().strip() for k, v in self.vars.items()}
        self.destroy()


class App(ttk.Frame):
    def __init__(self, root, mount=None):
        super().__init__(root, padding=8)
        self.root = root
        self.library = None
        self.events = queue.Queue()
        self.cancel = None
        self.busy = False
        self.meta = {}          # path -> {'title', 'author', 'genre'}
        self.quit_when_done = False
        self.mount_var = tk.StringVar(value=mount or DEFAULT_MOUNT)
        self.status_var = tk.StringVar()
        self.lib_var = tk.StringVar(value='Not connected')

        root.title('book2pad %s' % __version__)
        root.minsize(760, 460)
        root.protocol('WM_DELETE_WINDOW', self.on_close)
        self.pack(fill='both', expand=True)
        self.build()
        self.poll()
        self.connect(quiet=True)

    # ---- layout ---------------------------------------------------------

    def build(self):
        top = ttk.LabelFrame(self, text='iPad', padding=6)
        top.pack(fill='x')
        ttk.Label(top, text='Mount point:').pack(side='left')
        entry = ttk.Entry(top, textvariable=self.mount_var)
        entry.pack(side='left', fill='x', expand=True, padx=4)
        entry.bind('<Return>', lambda e: self.connect())
        ttk.Button(top, text='Browse…', command=self.browse_mount).pack(side='left')
        ttk.Button(top, text='Connect', command=self.connect).pack(side='left', padx=4)
        self.mount_btn = ttk.Button(top, text='Mount (ifuse)', command=self.toggle_mount)
        self.mount_btn.pack(side='left')
        ttk.Label(self, textvariable=self.lib_var, foreground='gray').pack(anchor='w', pady=(2, 6))

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill='both', expand=True)

        # -- transfer queue tab
        qtab = ttk.Frame(self.tabs, padding=6)
        self.tabs.add(qtab, text='To transfer')
        bar = ttk.Frame(qtab)
        bar.pack(fill='x', pady=(0, 6))
        self.queue_buttons = [
            ttk.Button(bar, text='Add files…', command=self.add_files),
            ttk.Button(bar, text='Add folder…', command=self.add_folder),
            ttk.Button(bar, text='Edit…', command=self.edit_selected),
            ttk.Button(bar, text='Remove', command=self.remove_selected),
            ttk.Button(bar, text='Clear', command=self.clear_queue),
        ]
        for b in self.queue_buttons:
            b.pack(side='left', padx=(0, 4))
        self.queue = self.make_tree(qtab, (('title', 'Title', 220), ('author', 'Author', 140),
                                           ('genre', 'Genre', 100), ('file', 'File', 180),
                                           ('status', 'Status', 120)))
        self.queue.bind('<Double-1>', lambda e: self.edit_selected())
        self.queue.bind('<Delete>', lambda e: self.remove_selected())

        # -- library tab
        ltab = ttk.Frame(self.tabs, padding=6)
        self.tabs.add(ltab, text='On iPad')
        bar = ttk.Frame(ltab)
        bar.pack(fill='x', pady=(0, 6))
        self.lib_buttons = [
            ttk.Button(bar, text='Refresh', command=self.connect),
            ttk.Button(bar, text='Delete from iPad', command=self.delete_selected),
        ]
        for b in self.lib_buttons:
            b.pack(side='left', padx=(0, 4))
        self.libtree = self.make_tree(ltab, (('title', 'Title', 260), ('author', 'Author', 160),
                                             ('genre', 'Genre', 110), ('file', 'File', 220)))

        # -- bottom: progress + actions
        bottom = ttk.Frame(self, padding=(0, 8, 0, 0))
        bottom.pack(fill='x')
        self.progress = ttk.Progressbar(bottom, mode='determinate')
        self.progress.pack(fill='x')
        row = ttk.Frame(bottom)
        row.pack(fill='x', pady=(4, 0))
        ttk.Label(row, textvariable=self.status_var).pack(side='left')
        self.cancel_btn = ttk.Button(row, text='Cancel', command=self.cancel_transfer, state='disabled')
        self.cancel_btn.pack(side='right')
        self.transfer_btn = ttk.Button(row, text='Transfer to iPad', command=self.start_transfer)
        self.transfer_btn.pack(side='right', padx=4)
        self.update_status()

    def make_tree(self, parent, columns):
        frame = ttk.Frame(parent)
        frame.pack(fill='both', expand=True)
        tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show='headings')
        for key, label, width in columns:
            tree.heading(key, text=label, command=lambda k=key: self.sort(tree, k))
            tree.column(key, width=width, anchor='w')
        sb = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        return tree

    @staticmethod
    def sort(tree, key):
        rows = sorted(tree.get_children(), key=lambda i: tree.set(i, key).lower())
        for n, iid in enumerate(rows):
            tree.move(iid, '', n)

    # ---- threading helpers ----------------------------------------------

    def later(self, fn, *args):
        """Run fn(*args) on the Tk thread (safe to call from workers)."""
        self.events.put((fn, args))

    def poll(self):
        try:
            while True:
                fn, args = self.events.get_nowait()
                fn(*args)
        except queue.Empty:
            pass
        except tk.TclError:
            return  # window was closed by one of the callbacks
        try:
            self.root.after(80, self.poll)
        except tk.TclError:
            pass

    def run_bg(self, fn, *args):
        threading.Thread(target=fn, args=args, daemon=True).start()

    # ---- iPad connection --------------------------------------------------

    def browse_mount(self):
        path = filedialog.askdirectory(title='iPad mount point', initialdir=self.mount_var.get())
        if path:
            self.mount_var.set(path)
            self.connect()

    def mount_path(self):
        return os.path.expanduser(self.mount_var.get().strip())

    def is_mounted(self):
        return os.path.ismount(self.mount_path())

    def connect(self, quiet=False):
        if self.busy:
            return
        mount = self.mount_path()
        self.libtree.delete(*self.libtree.get_children())
        self.library = None
        try:
            self.library = Library(mount)
        except Book2PadError as e:
            self.lib_var.set('Not connected: %s' % e)
            if not quiet:
                messagebox.showwarning('book2pad', '%s\n\nMount the iPad (e.g. with the '
                                       '"Mount (ifuse)" button) and try again.' % e)
        else:
            for name, rec in sorted(self.library.books.items()):
                self.libtree.insert('', 'end', iid=name, values=(
                    rec.get('Name', ''), rec.get('Artist', ''), rec.get('Genre', ''), name))
            self.lib_var.set('Connected: %s — %d book(s) in iBooks'
                             % (self.library.mount, len(self.library.books)))
            self.tabs.tab(1, text='On iPad (%d)' % len(self.library.books))
        self.mount_btn.config(text='Unmount' if self.is_mounted() else 'Mount (ifuse)')
        self.update_status()

    def toggle_mount(self):
        mount = self.mount_path()
        unmounting = self.is_mounted()
        if unmounting:
            tool = next((t for t in ('fusermount3', 'fusermount') if shutil.which(t)), None)
            cmd = [tool, '-u', mount] if tool else ['umount', mount]
        else:
            if not shutil.which('ifuse'):
                messagebox.showerror('book2pad', 'ifuse is not installed.\n\nInstall it with '
                                     'your package manager, e.g. "sudo pacman -S ifuse" or '
                                     '"sudo apt install ifuse".')
                return
            try:
                os.makedirs(mount, exist_ok=True)
            except OSError as e:
                messagebox.showerror('book2pad', 'Cannot create %s:\n%s' % (mount, e))
                return
            cmd = ['ifuse', mount]
        self.root.config(cursor='watch')
        self.root.update_idletasks()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            error = proc.returncode and (proc.stderr.strip() or 'exit code %d' % proc.returncode)
        except (OSError, subprocess.TimeoutExpired) as e:
            error = str(e)
        finally:
            self.root.config(cursor='')
        if error:
            hint = '' if unmounting else ('\n\nMake sure the iPad is plugged in, unlocked, and '
                                          'that you tapped "Trust" on it.')
            messagebox.showerror('book2pad', '%s failed:\n%s%s' % (cmd[0], error, hint))
        self.connect(quiet=unmounting or bool(error))

    # ---- queue ------------------------------------------------------------

    def add_files(self):
        paths = filedialog.askopenfilenames(title='Add books', filetypes=[
            ('Books', '*.pdf *.PDF *.epub *.EPUB'), ('All files', '*')])
        self.add_paths(paths)

    def add_folder(self):
        path = filedialog.askdirectory(title='Add a folder of books (subfolder names become genres)')
        if path:
            self.add_paths([path])

    def add_paths(self, paths):
        new = [p for p in collect_books(paths) if not self.queue.exists(p)]
        for p in new:
            self.queue.insert('', 'end', iid=p, values=(
                os.path.splitext(os.path.basename(p))[0], '',
                os.path.basename(os.path.dirname(p)), os.path.basename(p), 'reading…'))
        if new:
            self.run_bg(self.load_metadata, new)
        self.update_status()

    def load_metadata(self, paths):
        for p in paths:
            try:
                info = read_book_info(p, with_hash=False)
                meta = {'title': info.title, 'author': info.author, 'genre': info.genre}
            except Exception:
                meta = None
            self.later(self.set_metadata, p, meta)

    def set_metadata(self, path, meta):
        if not self.queue.exists(path) or path in self.meta:
            return  # removed, or already edited by the user
        if meta is None:
            self.queue.set(path, 'status', 'unreadable')
            return
        self.meta[path] = meta
        for k in FIELDS:
            self.queue.set(path, k, meta[k])
        self.queue.set(path, 'status', 'queued')

    def edit_selected(self):
        sel = self.queue.selection()
        if not sel or self.busy:
            return
        common = {}
        for k in FIELDS:
            vals = {self.queue.set(i, k) for i in sel}
            common[k] = vals.pop() if len(vals) == 1 else ''
        dlg = EditDialog(self.root, common, multiple=len(sel) > 1)
        if not dlg.result:
            return
        for iid in sel:
            meta = {k: self.queue.set(iid, k) for k in FIELDS}
            for k, v in dlg.result.items():
                if v or len(sel) == 1:
                    meta[k] = v
            self.meta[iid] = meta
            for k in FIELDS:
                self.queue.set(iid, k, meta[k])
            self.queue.set(iid, 'status', 'queued (edited)')

    def remove_selected(self):
        if self.busy:
            return
        for iid in self.queue.selection():
            self.queue.delete(iid)
            self.meta.pop(iid, None)
        self.update_status()

    def clear_queue(self):
        if not self.busy:
            self.queue.delete(*self.queue.get_children())
            self.meta.clear()
            self.update_status()

    # ---- library ----------------------------------------------------------

    def delete_selected(self):
        sel = self.libtree.selection()
        if not sel or not self.library or self.busy:
            return
        if not messagebox.askyesno('book2pad', 'Delete %d book(s) from the iPad?' % len(sel)):
            return
        try:
            for name in sel:
                self.library.remove(name, delete_file=True)
            self.library.save()
        except (OSError, Book2PadError) as e:
            messagebox.showerror('book2pad', str(e))
        self.connect(quiet=True)

    # ---- transfer -----------------------------------------------------------

    def update_status(self):
        n = len(self.queue.get_children())
        if not self.busy:
            self.status_var.set('%d book(s) queued' % n)
            self.transfer_btn.config(state='normal' if n and self.library else 'disabled')

    def set_busy(self, busy):
        self.busy = busy
        state = 'disabled' if busy else 'normal'
        for b in self.queue_buttons + self.lib_buttons + [self.mount_btn]:
            b.config(state=state)
        self.cancel_btn.config(state='normal' if busy else 'disabled')
        self.transfer_btn.config(state='disabled' if busy else 'normal')
        self.update_status()

    def start_transfer(self):
        books = list(self.queue.get_children())
        if not books or not self.library:
            return
        self.cancel = threading.Event()
        self.progress.config(maximum=len(books), value=0)
        self.set_busy(True)
        overrides = {p: dict(m) for p, m in self.meta.items()}
        self.run_bg(self.transfer_worker, books, overrides)

    def transfer_worker(self, books, overrides):
        def progress(i, total, path, result):
            self.later(self.on_progress, i, total, path, result)
        try:
            summary = transfer(self.library, books, progress, self.cancel, overrides)
        except Exception as e:
            self.later(self.on_done, None, e)
        else:
            self.later(self.on_done, summary, None)

    def on_progress(self, i, total, path, result):
        self.progress.config(value=i)
        if result is None:
            self.status_var.set('Transferring %d/%d: %s' % (i + 1, total, os.path.basename(path)))
            self.queue.set(path, 'status', 'copying…')
            self.queue.see(path)
        else:
            text = result.status.value + (': ' + result.message if result.message else '')
            self.queue.set(path, 'status', ('✓ ' if result.status.ok else '✗ ') + text)

    def cancel_transfer(self):
        if self.cancel:
            self.cancel.set()
            self.status_var.set('Cancelling after the current book…')

    def on_close(self):
        if not self.busy:
            self.root.destroy()
        elif messagebox.askyesno('book2pad', 'A transfer is in progress. Stop after the '
                                 'current book and quit?'):
            self.quit_when_done = True
            self.cancel_transfer()

    def on_done(self, summary, error):
        self.set_busy(False)
        if self.quit_when_done:
            self.root.destroy()
            return
        if error:
            messagebox.showerror('book2pad', 'Transfer failed:\n%s' % error)
        else:
            # Drop successfully transferred and already-present books from the queue.
            for r in summary.results:
                if r.status.ok or r.status is Status.EXISTS:
                    self.queue.delete(r.path)
                    self.meta.pop(r.path, None)
            msg = '%s: %s.' % ('Cancelled' if summary.cancelled else 'Finished',
                               summary.describe())
            if summary.count(True):
                msg += '\n\nRestart iBooks on the iPad to see the new books.'
            messagebox.showinfo('book2pad', msg)
        self.connect(quiet=True)


def main(mount=None):
    root = tk.Tk()
    try:
        ttk.Style(root).theme_use('clam')
    except tk.TclError:
        pass
    App(root, mount)
    root.mainloop()


if __name__ == '__main__':
    main()
