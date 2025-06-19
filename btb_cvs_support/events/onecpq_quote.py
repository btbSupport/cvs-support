import frappe
from erpnext.controllers.taxes_and_totals import calculate_taxes_and_totals
#DEV API Key = dd017c3d9d14afe:2aba5089f049917

@frappe.whitelist()
def get_synced_items(quote_name: str):
    sql = f"""
        select tqi.*,tbci.idx   from `tabQuotation Item` tqi join tabBtbCartItem tbci on tbci.name=tqi.custom_cart_item  where tqi.parent ='{quote_name}'
order by tbci.idx
    """
    items = frappe.db.sql(sql, as_dict=1)
    return items
@frappe.whitelist()
def get_cart_item_links(quote_name: str):
    sql = f"""select name from tabBtbCartItemLink where entity='{quote_name}'"""
    items = frappe.db.sql(sql, as_dict=1)
    return items

@frappe.whitelist()
def get_cart_items(quote_name: str):
    sql = f"""select * from tabBtbCartItem tbci where cart in (select parent  from tabBtbCartLink tbcl where entity ='{quote_name}') and valid = 1 
and name not in (select custom_cart_item from `tabQuotation Item` tqi where tqi.parent ='{quote_name}'  and custom_cart_item is not null)"""
    items = frappe.db.sql(sql, as_dict=1)
    return items

@frappe.whitelist()
def get_items(quote_name: str):
    sql = f"""
        select name from `tabQuotation Item` tqi   where tqi.parent ='{quote_name}' and tqi.custom_cart_item is null
    """
    items = frappe.db.sql(sql, as_dict=1)
    return items

def proceed_cart_item_link(doc, method = None):
    print('inside proceed_cart_item_link , doc.valid', doc.valid )
    if(doc.unit_price == 0 and doc.valid == 1):
        sqlcil = f"""select name,entity from tabBtbCartItemLink where parent='{doc.name}'"""
        for item in frappe.db.sql(sqlcil, as_dict=1): 
            frappe.delete_doc("BtbCartItemLink",item.name) == None
        return
    if(doc.valid == 1):
        sql = f"""select entity  from tabBtbCartLink tbcl where parent ='{doc.cart}'
        and entity not in (select entity from tabBtbCartItemLink where parent='{doc.name}')"""
        entityList = []
        for item in frappe.db.sql(sql, as_dict=1): 
            entityList.append(item.entity)
        for entity in entityList: 
            ci = populate_cart_item_links(entity, doc)
            ci.save()

@frappe.whitelist()
def before_save_quote(doc, method = None):
    if(doc.custom_customizable):
        doc.apply_discount_on = 'Net Total'
    if(doc.custom_customizable and doc.additional_discount_percentage != doc.custom_cart_discount):
        doc.additional_discount_percentage = doc.custom_cart_discount
        calculate_taxes_and_totals(doc)

@frappe.whitelist()
def remove_quotation_items(doc, method = None):
    quote_name = doc.name
    customizable = doc.custom_customizable
    print('inside remove quote_name :',quote_name,' customizable :',customizable)
    items = []
    cartItemLinks = []
    if(customizable == 1): 
        cartItems = get_cart_items(quote_name)
        for item in cartItems: 
            ci = populate_cart_item_links(quote_name, item)
            ci.save()
        items = get_items(quote_name)
        for item in items: 
            frappe.delete_doc("Quotation Item",item.name) == None
    if(customizable == 0) : 
        cartItemLinks = get_cart_item_links(quote_name)
        for item in cartItemLinks: 
            frappe.delete_doc("BtbCartItemLink",item.name) == None
    quoteOld = frappe.frappe.get_doc("Quotation", quote_name)
    quote = frappe.frappe.get_doc("Quotation", quote_name)
    calculate_taxes_and_totals(quote)
    if(quote.total != quoteOld.total): quote.save()

def populate_cart_item_links(quote_name:str,item:any):
    ci = frappe.frappe.new_doc("BtbCartItemLink")
    ci.entity = quote_name
    ci.entity_type = "Quotation"
    ci.parent = item.name
    ci.parenttype = "BtbCartItem"
    ci.parentfield = "cart_item_links"
    return ci

   
    

    