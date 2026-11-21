"""GTK host for the local desktop UI. Run with the distribution's Python and GI libraries."""

import os
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
try:
    gi.require_version("WebKit2", "4.1")
except ValueError:
    gi.require_version("WebKit2", "4.0")
from gi.repository import GLib, Gtk, WebKit2


def main(url):
    GLib.set_application_name("Odwołania2JSON")
    window = Gtk.Window(title="Odwołania2JSON")
    window.set_default_size(1280, 800)
    window.set_icon_from_file(str(Path(__file__).with_name("icon.png")))
    view = WebKit2.WebView()
    view.get_settings().set_javascript_can_access_clipboard(True)

    def save_download(download, filename):
        chooser = Gtk.FileChooserDialog(title="Zapisz plik", transient_for=window,
                                        action=Gtk.FileChooserAction.SAVE)
        chooser.add_buttons("Anuluj", Gtk.ResponseType.CANCEL, "Zapisz", Gtk.ResponseType.ACCEPT)
        chooser.set_current_name(Path(filename).name)
        chooser.set_do_overwrite_confirmation(True)
        if chooser.run() == Gtk.ResponseType.ACCEPT:
            download.set_allow_overwrite(True)
            download.set_destination(Path(chooser.get_filename()).as_uri())
        else:
            download.cancel()
        chooser.destroy()
        return True

    def new_window(_view, action):
        uri = action.get_request().get_uri()
        if uri.startswith(("http://", "https://")):
            Gtk.show_uri_on_window(window, uri, Gtk.get_current_event_time())
        return None

    view.connect("create", new_window)
    view.get_context().connect("download-started", lambda _, d: d.connect("decide-destination", save_download))
    def close_window(*_):
        window.hide()
        Gtk.main_quit()
        return True

    window.connect("delete-event", close_window)
    window.add(view)
    view.load_uri(url)
    window.show_all()
    Gtk.main()
    # This dedicated host owns one window. Avoid GI teardown of active WebKit processes.
    os._exit(0)


if __name__ == "__main__":
    main(sys.argv[1])
