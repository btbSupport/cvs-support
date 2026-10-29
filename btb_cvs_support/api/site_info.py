import frappe


def get_config(confName: str):
    """A site config value (site_config.json, falling back to common_site_config.json), or None.

    Server-side only: it used to be callable from the browser, which let any logged-in
    user read secrets such as db_password. frappe.conf is already loaded and cached
    per request, so this no longer reads the file from disk on every call.
    """
    return frappe.conf.get(confName)
