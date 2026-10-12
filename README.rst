README for book2pad
===================

book2pad transfers books (PDF or EPUB) from a Linux machine to an iPad's
iBooks library. Jailbreaking is not needed. It comes with a simple graphical
interface and a command-line mode for scripting.

Requirements
------------

* Python 3.8+ with Tkinter (for the GUI). On Arch: ``pacman -S tk``;
  on Debian/Ubuntu: ``apt install python3-tk``.
* `ifuse <https://libimobiledevice.org>`_ to mount the iPad.
* Optional: ``pypdf`` to read titles and authors from PDF metadata.
  EPUB metadata is read without any extra libraries.

Install
-------

::

    pip install .          # or: pip install '.[pdf]'

You can also run it straight from a checkout with ``python3 -m book2pad``.

Library layout
--------------

Use one folder per genre, as in `your_library <your_library>`_. The parent
folder of each book becomes its genre. Titles and authors come from the
book's metadata; when that is missing, files named ``title-author.ext`` are
parsed instead.

GUI
---

Run ``book2pad`` (or ``book2pad-gui``) with no arguments.

1. Enter the iPad's mount point and press **Connect**. If it isn't mounted,
   press **Mount (ifuse)** to mount it at that path.
2. On the **To transfer** tab, use **Add files…** / **Add folder…** to queue
   books. Double-click a row (or select several and press **Edit…**) to
   change the title, author or genre before transferring.
3. Press **Transfer to iPad**. Progress shows per book; **Cancel** stops after
   the current one and keeps what has been transferred.
4. The **On iPad** tab lists books in the iBooks library; select some and
   press **Delete from iPad** to remove them.

Restart iBooks on the iPad afterwards to see the changes.

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

Comments and bug reports
------------------------
Project page is on https://github.com/rk700/book2pad

You can also send email to the author: `Ruikai Liu`_

.. _Ruikai Liu: lrk700@gmail.com
