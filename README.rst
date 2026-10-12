README for book2pad
===================

book2pad transfers books (PDF or EPUB) from a Linux machine to an iPad's
iBooks library. Jailbreaking is not needed. It comes with a simple graphical
interface and a command-line mode for scripting.

Requirements
------------

* Python 3.8+ with Tkinter for the GUI.
* `ifuse <https://libimobiledevice.org>`_ to mount the iPad.
* Optional: ``pypdf`` to read titles and authors from PDF metadata
  (EPUB metadata needs nothing extra; otherwise the filename is used).

Arch / CachyOS::

    sudo pacman -S python tk ifuse          # optional: python-pypdf

Debian / Ubuntu::

    sudo apt install python3 python3-tk ifuse   # optional: python3-pypdf

Launching
---------

**From the checkout, no install needed**::

    git clone -b gui-redesign https://github.com/keebsxd/book2pad.git
    cd book2pad
    ./launch.py                 # opens the GUI
    ./launch.py -d ~/ipad -b ~/books -v    # command line

**Installed as commands** (``book2pad`` and ``book2pad-gui``). Use pipx,
since distributions like Arch block ``pip install`` into the system Python::

    pipx install .              # or: pipx install '.[pdf]'
    book2pad-gui

**Application menu entry** (after installing with pipx)::

    cp book2pad.desktop ~/.local/share/applications/

Compatibility
-------------

book2pad writes books into ``Books/Purchases`` and registers them in
``Purchases.plist``, the method upstream tested on iOS 8.3 and 9.1. Newer
iOS versions may manage the Books library differently and might not pick up
books added this way, so try it with one book first.

Library layout
--------------

Use one folder per genre, as in `your_library <your_library>`_. The parent
folder of each book becomes its genre. Titles and authors come from the
book's metadata; when that is missing, files named ``title-author.ext`` are
parsed instead.

GUI
---

Run ``./launch.py`` (or ``book2pad-gui``) with no arguments.

1. Plug in and unlock the iPad, and tap **Trust** if asked. The mount point
   defaults to ``~/ipad``; press **Mount (ifuse)** to mount the iPad there
   (or enter the path of an existing mount and press **Connect**).
2. On the **To transfer** tab, use **Add files…** / **Add folder…** to queue
   books. Double-click a row (or select several and press **Edit…**) to
   change the title, author or genre before transferring.
3. Press **Transfer to iPad**. Progress shows per book; **Cancel** stops after
   the current one and keeps what has been transferred.
4. The **On iPad** tab lists books in the iBooks library; select some and
   press **Delete from iPad** to remove them.

Restart iBooks on the iPad afterwards to see the changes, and press
**Unmount** before unplugging. Closing the window during a transfer
finishes the current book and saves the library first.

Command line
------------

::

    ifuse /media
    book2pad -d /media -b ~/doc/
    book2pad -d /media -b ~/doc/file.pdf ~/doc/others -v

``-d`` is the iPad mount point (default: the current directory), ``-b`` the
books or folders to transfer, and ``-v`` reports every book.

Books already on the iPad with the same content and metadata are skipped;
changed files are replaced, and if only the metadata changed the library
entry is updated without copying the file again.

Tests
-----

::

    python3 -m unittest discover -s tests -v

Comments and bug reports
------------------------
Project page is on https://github.com/rk700/book2pad

You can also send email to the author: `Ruikai Liu`_

.. _Ruikai Liu: lrk700@gmail.com
