import frappe
import json
from frappe.utils import get_site_name

def get_site_config():
    # frappe.log(f"Error: frappe.local.request.header in {frappe.local.site}")
    site_name = frappe.local.site
    print(f"site_name {site_name}")
    site_config_path = "../sites/"+site_name+"/site_config.json"
    try:
        with open(site_config_path, 'r') as f:
            site_config = json.load(f)
        return site_config
    except FileNotFoundError:
        print(f"Error: Site config file not found at {site_config_path}")
        frappe.log(f"Error: Site config file not found at {site_config_path}")
        return None
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON in {site_config_path}")
        frappe.log(f"Error: Invalid JSON in {site_config_path}")
        return None
    
@frappe.whitelist()
def get_config(confName:str):
    site_config = get_site_config()
    frappe.log(site_config)
    if(confName in site_config) : 
        return site_config.get(confName)
    return None