import frappe
from erpnext.controllers.taxes_and_totals import calculate_taxes_and_totals
from ..api.onecpq_quote_item import *
from ..api.site_info import *
#DEV API Key = dd017c3d9d14afe:2aba5089f049917

@frappe.whitelist()
def delete_links(doc, method = None):
    sql = f"""select name from tabBtbCartItemLink where parent='{doc}'"""
    for item in frappe.db.sql(sql, as_dict=1): 
            frappe.delete_doc("BtbCartItemLink",item.name) == None
    return

@frappe.whitelist()
def get_cart_item_links(quote_name: str):
    sql = f"""select name from tabBtbCartItemLink where entity='{quote_name}'"""
    items = frappe.db.sql(sql, as_dict=1)
    return items

@frappe.whitelist()
def get_cart_items(quote_name: str):
    sql = f"""select * from tabBtbCartItem tbci where cart in (select parent  from tabBtbCartLink tbcl where entity ='{quote_name}') and valid = 1 
and name not in ( select parent from tabBtbCartItemLink tbcil where entity = '{quote_name}')
order by tbci.idx"""
    items = frappe.db.sql(sql, as_dict=1)
    return items

@frappe.whitelist()
def get_items(quote_name: str):
    sql = f"""
        select name from `tabQuotation Item` tqi   where tqi.parent ='{quote_name}' and tqi.custom_cart_item is null
    """
    items = frappe.db.sql(sql, as_dict=1)
    return items

@frappe.whitelist()
def before_save_cart(doc, method = None):
    print('get_config allow_cpq before_save_cart',get_config('allow_cpq') )
    if(get_config('allow_cpq')==None or get_config('allow_cpq') == 0): return
    if(doc.discount != None and (doc.discount <-100 or doc.discount > 30)):frappe.throw('Discount % not in the approved limit.')
    if(doc.unit_price == 0): doc.valid = 0

@frappe.whitelist()
def proceed_cart_item_link(doc, method = None):
    print('get_config allow_cpq proceed_cart_item_link',get_config('allow_cpq') )
    print('doc.unit_price : ',doc.unit_price)
    print('doc.valid : ',doc.valid)
    if(get_config('allow_cpq')==None or get_config('allow_cpq') == 0): return
    if(doc.unit_price == 0):
        sqlcil = f"""select name,entity from tabBtbCartItemLink where parent='{doc.name}'"""
        for item in frappe.db.sql(sqlcil, as_dict=1): 
            frappe.delete_doc("BtbCartItemLink",item.name) == None
        print('doc.valid after: ',doc.valid)
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
def lock_cart( doc_name,doc_status) :
    print('inside after quote save ',doc_status)
    lock = 1
    if (doc_status == 0) : lock = 0
    print('inside after quote save lock',lock)
    sql = f""" select parent from `tabBtbCartLink` cl join `tabBtbCart` c on cl.parent = c.name and c.locked !='{lock}' 
    where entity='{doc_name}'
    """
    print('inside after quote save sql',sql)
    items = frappe.db.sql(sql, as_dict=1)
    print('inside after quote save items',items)
    for item in items:
        cart = frappe.frappe.get_doc("BtbCart", item.parent)
        cart.locked = lock
        cart.db_update()


@frappe.whitelist()
def on_submit_quote(doc = None, method = None):
    if(get_config('allow_cpq')==None or get_config('allow_cpq') == 0): return
    if(doc.custom_customizable !=1): return
    if( validate_cart(doc.name)):frappe.throw('Please check OneCPQ all cart items synced.')
    if(doc.custom_customizable ==1) : lock_cart(doc.name,doc.docstatus)

def validate_cart(quote_name: str):
    sql = f""" select * from tabBtbCartItem tbci where cart in (select parent  from tabBtbCartLink tbcl where entity ='{quote_name}') and 
    ( valid = 0 or name not in ( select parent from tabBtbCartItemLink tbcil where entity = '{quote_name}'))"""
    items = frappe.db.sql(sql, as_dict=1)
    return len(items) >0

@frappe.whitelist()
def on_cancel_quote(doc = None, method = None):
    if(get_config('allow_cpq')==None or get_config('allow_cpq') == 0): return
    if(doc.custom_customizable ==1) : lock_cart(doc.name,doc.docstatus)

@frappe.whitelist()
def before_save_quote(doc = None, method = None):
    print('get_config allow_cpq before save quote',get_config('allow_cpq') )
    if(get_config('allow_cpq')==None or get_config('allow_cpq') == 0): return
    beforequote = getQuoteById(doc.name)
    if(beforequote == None): 
        doc.custom_cpq_amended=0
        if(doc.custom_customizable == 1 and doc.amended_from != None) :
            doc.items=[]
        return   
    if(doc is None): return
    if(beforequote.docstatus != doc.docstatus and doc.custom_customizable ==1) : lock_cart(doc.name,doc.docstatus)
    print('doc beforequote.docstatus : ',beforequote.docstatus)
    print('doc doc.docstatus : ',doc.docstatus)

    if(beforequote.docstatus != 0 and doc.custom_customizable ==1 and
       (beforequote.total_qty != doc.total_qty or beforequote.base_total != doc.base_total)):frappe.throw('You can only update the Quotation on Draft status.')

    if(beforequote != None and doc.custom_customizable != beforequote.custom_customizable): remove_quotation_items(doc)
    if(doc.custom_customizable == beforequote.custom_customizable and doc.custom_customizable ==0): return
    if(doc.custom_customizable == 1): 
        doc.apply_discount_on = 'Net Total'
        if(doc.additional_discount_percentage != doc.custom_cart_discount):
            doc.additional_discount_percentage = doc.custom_cart_discount
            if(doc.custom_cart_discount ==0):
                doc.discount_amount = 0
    doc.items = []
    syncItems = get_synced_items(doc.name)
    items = get_items(doc.name)
    frappe.log('doc before calc - items : ')
    frappe.log(items)
    print('doc before calc - sync items : ',syncItems)
    print('doc before calc - discount amount : ',doc.discount_amount)
    print('doc after calc - discount amount : ',doc.discount_amount)
    totalUnitPrice = 0
    totalLineDiscount = 0
    totalDiscountPercenatge = 0
    totalLineDiscountPercentage = 0
    if(doc.custom_customizable != 1): 
        for item in items: 
            doc.items.append(frappe.frappe.get_doc("Quotation Item", item.name))
    if(doc.custom_customizable == 1):
        for item in syncItems: 
            totalUnitPrice += (item.ciQty * item.unit_price)
            totalLineDiscount +=  (item.ciQty * ((item.unit_price) * item.ciDiscount/100))
            doc.items.append(frappe.frappe.get_doc("Quotation Item", item.name))
    calculate_taxes_and_totals(doc)
    if(beforequote.docstatus != 0 and  doc.custom_customizable ==1 and
       (beforequote.total_qty != doc.total_qty or beforequote.base_total != doc.base_total)):frappe.throw('You can only update on Draft status.')
    totalDiscount = totalLineDiscount + doc.discount_amount
    if(totalUnitPrice>0) : 
        totalDiscountPercenatge = (totalDiscount/totalUnitPrice) * 100
        totalLineDiscountPercentage = (totalLineDiscount/totalUnitPrice) * 100
    doc.custom_list_amount = totalUnitPrice
    doc.custom_discount = totalLineDiscountPercentage
    doc.custom_total_discount_amount = totalDiscount
    doc.custom_total_discount = totalDiscountPercenatge
    if(doc.custom_total_discount>32):frappe.throw('Total Discount % exceeds the approved limit.')
    print('doc after calc - items : ',doc.items)

@frappe.whitelist()
def amendCPQ(doc = None, method = None):
    quote_name = doc.name
    amended_from = doc.amended_from
    print('inside amendCPQ',quote_name)
    print('inside amendCPQ amended_from',amended_from)
    if(doc.amended_from == None or doc.custom_customizable ==0 or doc.custom_cpq_amended!=0): return
    cart_name = create_cart(quote_name)
    cartItems = get_synced_items(amended_from)
    print('inside amendCPQ cartItems',cartItems)
    # clonedItems=[]
    for item in cartItems:
        cartItem = frappe.frappe.get_doc("BtbCartItem", item.ciName)
        cartItem.name = None
        cartItem.cart = cart_name
        ciLinks =[]
        for cil in cartItem.cart_item_links:
            cil.entity = quote_name
            ciLinks.append(cil)
        cartItem.cart_item_links = ciLinks
        # cartItem.cart_item_links =[]
        cartItem.save()
    quot = frappe.frappe.get_doc("Quotation", quote_name)
    quot.custom_cpq_amended = 1
    quot.db_update()

def create_cart(quote_name: str):
    cartLink = frappe.new_doc("BtbCartLink")
    cartLink.entity_type = "Quotation"
    cartLink.entity = quote_name

    cart = frappe.new_doc("BtbCart")
    cart.append('cart_links', cartLink)
    cart.insert()
    return cart.name

@frappe.whitelist()
def remove_quotation_items(doc):
    # print('get_config allow_cpq remove_quotation_items',get_config('allow_cpq') )
    # if(get_config('allow_cpq')==None or get_config('allow_cpq') == 0): return
    quote_name = doc.name
    customizable = doc.custom_customizable
    print('inside remove quote_name :',quote_name,' customizable :',customizable)
    # beforequote = getQuoteById(doc.name)
    # if(beforequote == None): return
    # if(customizable == beforequote.custom_customizable): return
    # items = []
    cartItemLinks = []
    if(customizable == 1): 
        cartItems = get_cart_items(quote_name)
        for item in cartItems: 
            ci = populate_cart_item_links(quote_name, item)
            ci.save()
        # items = get_items(quote_name)
        # for item in items: 
            # frappe.delete_doc("Quotation Item",item.name) == None
    if(customizable == 0) : 
        cartItemLinks = get_cart_item_links(quote_name)
        for item in cartItemLinks: 
            frappe.delete_doc("BtbCartItemLink",item.name) == None
    print("inside remove quote_name end 102",quote_name)

def populate_cart_item_links(quote_name:str,item:any):
    ci = frappe.frappe.new_doc("BtbCartItemLink")
    ci.entity = quote_name
    ci.entity_type = "Quotation"
    ci.parent = item.name
    ci.parenttype = "BtbCartItem"
    ci.parentfield = "cart_item_links"
    return ci
@frappe.whitelist()
def on_trash(doc, method = None):
    print('deleting cart',method)