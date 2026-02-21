"""Export functionality for Lugna Rummet."""

import csv
import io
import json
from datetime import datetime

import gettext
_ = gettext.gettext

from lugnarummet import __version__

APP_LABEL = _("Calming Room")
AUTHOR = "Daniel Nylander"
WEBSITE = "www.autismappar.se"

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, GLib


def sessions_to_csv(sessions):
    """Export calming sessions as CSV."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([_("Date"), _("Type"), _("Duration (min)"), _("Stress before"), _("Stress after")])
    for s in sessions:
        writer.writerow([
            s.get("date", ""),
            s.get("type", ""),
            s.get("duration", 0),
            s.get("stress_before", ""),
            s.get("stress_after", ""),
        ])
    writer.writerow([])
    writer.writerow([f"{APP_LABEL} v{__version__} — {WEBSITE}"])
    return output.getvalue()


def sessions_to_json(sessions):
    """Export calming sessions as JSON."""
    data = {
        "sessions": sessions,
        "_exported_by": f"{APP_LABEL} v{__version__}",
        "_author": AUTHOR,
        "_website": WEBSITE,
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


def export_sessions_pdf(sessions, output_path):
    """Export calming sessions as PDF."""
    try:
        import cairo
    except ImportError:
        try:
            import cairocffi as cairo
        except ImportError:
            return False

    width, height = 595, 842
    surface = cairo.PDFSurface(output_path, width, height)
    ctx = cairo.Context(surface)

    ctx.set_font_size(24)
    ctx.move_to(40, 50)
    ctx.show_text(_("Calming Sessions"))

    ctx.set_font_size(12)
    ctx.move_to(40, 75)
    ctx.show_text(datetime.now().strftime("%Y-%m-%d"))

    y = 110
    ctx.set_font_size(13)
    ctx.set_source_rgb(0.3, 0.3, 0.3)
    ctx.move_to(40, y)
    ctx.show_text(_("Date"))
    ctx.move_to(160, y)
    ctx.show_text(_("Type"))
    ctx.move_to(340, y)
    ctx.show_text(_("Duration"))
    ctx.move_to(430, y)
    ctx.show_text(_("Stress"))

    y += 10
    ctx.set_line_width(0.5)
    ctx.move_to(40, y)
    ctx.line_to(width - 40, y)
    ctx.stroke()

    ctx.set_source_rgb(0, 0, 0)
    ctx.set_font_size(11)

    for s in sessions:
        y += 22
        if y > height - 40:
            surface.show_page()
            y = 40
        ctx.move_to(40, y)
        ctx.show_text(s.get("date", ""))
        ctx.move_to(160, y)
        ctx.show_text(s.get("type", ""))
        ctx.move_to(340, y)
        ctx.show_text(str(s.get("duration", "")) + " min")
        ctx.move_to(430, y)
        before = s.get("stress_before", "")
        after = s.get("stress_after", "")
        if before and after:
            ctx.show_text(f"{before} → {after}")

    # Footer
    ctx.set_font_size(9)
    ctx.set_source_rgb(0.5, 0.5, 0.5)
    footer = f"{APP_LABEL} v{__version__} — {WEBSITE} — {datetime.now().strftime('%Y-%m-%d')}"
    ctx.move_to(40, height - 20)
    ctx.show_text(footer)

    surface.finish()
    return True


def show_export_dialog(window, sessions, status_callback=None):
    """Show export dialog."""
    dialog = Adw.AlertDialog.new(
        _("Export Calming Sessions"),
        _("Choose export format:")
    )

    dialog.add_response("cancel", _("Cancel"))
    dialog.add_response("csv", _("CSV"))
    dialog.add_response("json", _("JSON"))
    dialog.add_response("pdf", _("PDF"))
    dialog.set_default_response("csv")
    dialog.set_close_response("cancel")

    dialog.connect("response", _on_export_response, window, sessions, status_callback)
    dialog.present(window)


def _on_export_response(dialog, response, window, sessions, status_callback):
    if response == "cancel":
        return
    if response == "csv":
        _save_text(window, sessions, "csv", sessions_to_csv, status_callback)
    elif response == "json":
        _save_text(window, sessions, "json", sessions_to_json, status_callback)
    elif response == "pdf":
        _save_pdf(window, sessions, status_callback)


def _save_text(window, sessions, ext, converter, status_callback):
    dialog = Gtk.FileDialog.new()
    dialog.set_title(_("Save Export"))
    dialog.set_initial_name(f"lugnarummet_{datetime.now().strftime('%Y-%m-%d')}.{ext}")
    dialog.save(window, None, _on_text_done, sessions, converter, ext, status_callback)


def _on_text_done(dialog, result, sessions, converter, ext, status_callback):
    try:
        gfile = dialog.save_finish(result)
    except GLib.Error:
        return
    try:
        with open(gfile.get_path(), "w") as f:
            f.write(converter(sessions))
        if status_callback:
            status_callback(_("Exported %s") % ext.upper())
    except Exception as e:
        if status_callback:
            status_callback(_("Export error: %s") % str(e))


def _save_pdf(window, sessions, status_callback):
    dialog = Gtk.FileDialog.new()
    dialog.set_title(_("Save PDF"))
    dialog.set_initial_name(f"lugnarummet_{datetime.now().strftime('%Y-%m-%d')}.pdf")
    dialog.save(window, None, _on_pdf_done, sessions, status_callback)


def _on_pdf_done(dialog, result, sessions, status_callback):
    try:
        gfile = dialog.save_finish(result)
    except GLib.Error:
        return
    try:
        success = export_sessions_pdf(sessions, gfile.get_path())
        if success and status_callback:
            status_callback(_("PDF exported"))
        elif not success and status_callback:
            status_callback(_("PDF export requires cairo."))
    except Exception as e:
        if status_callback:
            status_callback(_("Export error: %s") % str(e))
