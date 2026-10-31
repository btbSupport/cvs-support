import frappe
import json
from frappe.utils import flt
from typing import Dict, List
import pandas as pd
from erpnext.controllers.taxes_and_totals import calculate_taxes_and_totals
from decimal import Decimal
from frappe.model.naming import make_autoname
from onecpq_connect.api.permission import require_onecpq_role
fti_cache ={}
# file names of the documents the Output Documents buttons generate
GENERATED_FILE_PREFIXES = ("BOQ_", "Quote_", "Production Sheet_")

def populate_cart_item_model( quote_name,conversion_rate):
    syncedItems = get_items(quote_name,conversion_rate)
    if(len(syncedItems)==0): return None
    cartItems = get_grouped_items(syncedItems)
    populate_featuretype_items(cartItems)
    return populate_cart_models(cartItems)

def populate_cart_item_model_by_cart_items( cart_item_names: List[str], conversion_rate = 1):
    """Same as populate_cart_item_model, but driven by an explicit list of cart
    items instead of everything linked to one quotation. Used by the OPR BOQ,
    where the cart items are reached one line at a time."""
    syncedItems = get_items_by_cart_items(cart_item_names, conversion_rate)
    if(len(syncedItems)==0): return None
    cartItems = get_grouped_items(syncedItems)
    populate_featuretype_items(cartItems)
    return populate_cart_models(cartItems)

def get_items_by_cart_items( cart_item_names: List[str], conversion_rate: float) -> List[Dict[str, any]]:
    if(not cart_item_names): return []
    placeholders = ", ".join(["%s"] * len(cart_item_names))
    sql = f""" select tbc.name,tbc.Unit_Price / %s AS Unit_Price,tbc.discount , tbc.idx, tbc.Quantity, tbc.Title,
        i.Name itemName, i.item_code, tbf.Field, tbf.label ,
        tbcif.value cif_value,tbfti.value fti_value,tbfti.`object` obj_value,tbft.object_type obj_type,tbft.data_text_field
    from tabBtbCartItem tbc
    join `tabItem` i on tbc.item  = i.name and tbc.name in ({placeholders})
    join tabBtbCartItemFeature tbcif on tbcif.parent = tbc.name
    join tabBtbFeature tbf  on tbf.name = tbcif.feature
    left join tabBtbFeatureTypeItem tbfti on tbcif.value = tbfti.name
    left join tabBtbFeatureType tbft on tbft.name = tbfti.feature_type
    order by tbc.idx
    """
    items = frappe.db.sql(sql, tuple([conversion_rate] + list(cart_item_names)), as_dict=1)
    return items

def get_grouped_items(items):
    df = pd.DataFrame(json.loads(json.dumps(items)))
    df["idx"] = pd.to_numeric(df["idx"], errors="coerce")
    df = df.sort_values("idx", kind="stable", na_position="last")
    res = df.groupby(["name","Unit_Price","discount","idx","Quantity","Title","itemName","item_code"], group_keys=False, sort=False, dropna=False)
    return res
@frappe.whitelist()
def get_items( quote_name: str,conversion_rate:float) -> List[Dict[str, any]]:
    sql = """ select tbc.name,tbc.Unit_Price / %(conversion_rate)s AS Unit_Price,tbc.discount , tbc.idx, tbc.Quantity, tbc.Title,
        i.Name itemName, i.item_code, tbf.Field, tbf.label ,
        tbcif.value cif_value,tbfti.value fti_value,tbfti.`object` obj_value,tbft.object_type obj_type,tbft.data_text_field 
    from tabBtbCartItem tbc
    join `tabItem` i on tbc.item  = i.name and   tbc.name in (
    select parent from tabBtbCartItemLink tbcil where entity = %(quote_name)s
    )
    join tabBtbCartItemFeature tbcif on tbcif.parent = tbc.name
    join tabBtbFeature tbf  on tbf.name = tbcif.feature 
    left join tabBtbFeatureTypeItem tbfti on tbcif.value = tbfti.name
    left join tabBtbFeatureType tbft on tbft.name = tbfti.feature_type
    order by tbc.idx
    """
    items = frappe.db.sql(sql, {"quote_name": quote_name, "conversion_rate": flt(conversion_rate) or 1}, as_dict=1)
    return items

def populate_featuretype_items( cartItems):
    for group_name, df_group in cartItems:
        ftis =  {}
        for row_index, row in df_group.iterrows():
            if(row.obj_type != None and row.obj_type != ""):
                key = str(row.obj_type)+'-'+str(row.data_text_field)+'-'+str(row.cif_value)
                if( key not in ftis.keys()):ftis[key] = []
                if( row.obj_value not in fti_cache.keys()):
                    if(row.obj_value not in ftis[key]) : ftis[key].append(row.obj_value)
        for key in ftis.keys():
            # print("check ",key)
            if(key == None): continue
            fti = ftis.get(key)
            obj = key.split("-")
            if(obj[0] !='') : get_featuretype_items(obj[0],obj[1],fti,obj[2])

def populate_cart_models( cartItems: Dict[str,any]) -> List[Dict[str, Dict]]:
    output =[]
    # print('fti_cache : ',fti_cache)
    for group_name, df_group in cartItems:
        item =  {}
        for row_index, row in df_group.iterrows():
            if(item == {}):
                # item =  {
                # "cartProductName": {"value": row.itemName},
                # "cartProductCode": {"value": row.item_code},
                # "qty": {"value":  round(Decimal(str(row.Quantity)),0)},
                # "unitPrice": {"value": round(Decimal(str(row.Unit_Price)),2)},
                # "beforeDiscount": {"value":   round(Decimal(str(row.Quantity * row.Unit_Price)),2)},
                # "rate": {"value":  round(Decimal(str(row.Unit_Price*(1-(row.discount/100)))),2)},
                # "amount": {"value":  round(Decimal(str(row.Unit_Price*(1-(row.discount/100))*row.Quantity)),2)},
                # "seq": {"value": row.Sequence},
                # "cartTitle": {"value": row.Title},
                # }
                item =  {
                # row["name"], not row.name - on a pandas row .name is the index label
                "cartItemId": {"value": row["name"]},
                "cartProductName": {"value": row.itemName},
                "cartProductCode": {"value": row.item_code},
                "qty": {"value":   f"{row.Quantity:,.2f}"},
                "cartQty": {"value":   row.Quantity},
                "unitPrice": {"value": f"{row.Unit_Price:,.2f}"},
                "beforeDiscount": {"value":   f"{(row.Quantity * row.Unit_Price):,.2f}"},
                "rate": {"value":  f"{(row.Unit_Price*(1-(row.discount/100))):,.2f}"},
                "cartAmount": {"value": (row.Unit_Price*(1-(row.discount/100))*row.Quantity)},
                "amount": {"value": f"{(row.Unit_Price*(1-(row.discount/100))*row.Quantity):,.2f}"},
                "seq": {"value": row.idx},
                "cartTitle": {"value": row.Title},
                }
            value = row.cif_value
            if(row.fti_value != None and row.fti_value != ""):value = row.fti_value
            if(row.obj_type != None and row.obj_type != ""):value = fti_cache.get(row.cif_value)
            item[row.Field]={"label": row.label, "value": value}
        output.append(item)
    return output  
def get_featuretype_items( tabName:str, data_text_field:str, values: List[str],fti:str):
    placeholders = ", ".join(["%s"] * len(values))
    sql = f"""
    select * from `tab{tabName}` where name IN  ({placeholders})
    """
    # frappe.log(sql)
    # result = frappe.db.sql(sql, as_dict=1)
    result = frappe.db.sql(sql, tuple(values), as_dict=True)
    for i in result:
        fti_cache[fti] = i[data_text_field]

@frappe.whitelist()
def get_synced_cart_items(quote_name: str):
    sql = """
        select cartItem.*,
GROUP_CONCAT(CASE WHEN field = 'modelItem' THEN item_code END) AS model_item_code,
GROUP_CONCAT(CASE WHEN field = 'modelItem' THEN stock_uom END) AS model_stock_uom,
GROUP_CONCAT(CASE WHEN field = 'tagRef' THEN cifValue END) AS tagRef,
GROUP_CONCAT(CASE WHEN field = 'notes' THEN cifValue END) AS notes ,
GROUP_CONCAT(CASE WHEN field = 'notesInput' THEN cifValue END) AS notesInput from  

    (SELECT i.item_code ciItemCode,i.stock_uom ciStockUom,ci.*
    from `tabBtbCartItemLink` cil 
        join tabBtbCartItem ci on ci.name=cil.parent 
         and  cil.entity = %(quote_name)s
    join `tabItem` i on i.name = ci.item) 
    
cartItem

 left join  (select i.item_code,i.stock_uom,tbf.field,tbcif.value cifValue,tbfti.value,tbcif.parent from tabBtbCartItemFeature tbcif  
    join tabBtbFeature tbf  on   tbf.name = tbcif.feature  and tbf.field in('modelItem','tagRef','notes','notesInput')
    left join tabBtbFeatureTypeItem tbfti on  tbfti.name = tbcif.value
    left join `tabItem` i on i.name = tbfti.`object`) 
    
config 

on cartItem.name = config.parent
group by cartItem.name
order by cartItem.idx

    """
    items = frappe.db.sql(sql, {"quote_name": quote_name}, as_dict=1)
    return items
    
# @frappe.whitelist()
# def get_synced_cart_items(quote_name: str):
#     sql = f"""
#         select tbci.*,i.item_name, i.item_code,sequence,i.stock_uom,i.description  from `tabBtbCartItemLink` tqi 
#         join tabBtbCartItem tbci on tbci.name=tqi.parent  
# 		join `tabItem` i on tbci.item = i.name
#         where tqi.entity ='{quote_name}'
# order by tbci.idx
#     """
#     items = frappe.db.sql(sql, as_dict=1)
#     return items

@frappe.whitelist()
def get_synced_items(quote_name: str):
    sql = """
        select tqi.*,tbci.idx,tbci.unit_price,tbci.discount ciDiscount,tbci.quantity ciQty,tbci.name ciName  from `tabQuotation Item` tqi 
        join tabBtbCartItem tbci on tbci.name=tqi.custom_cart_item  where tqi.parent = %(quote_name)s
order by tbci.idx, tbci.creation
    """
    items = frappe.db.sql(sql, {"quote_name": quote_name}, as_dict=1)
    return items

@frappe.whitelist()
def getQuoteById( quote_name):
    sql = """
		select *  from `tabQuotation` tqi where name = %(quote_name)s
	"""
    items = frappe.db.sql(sql, {"quote_name": quote_name}, as_dict=1)
    if(len(items) >0) : return items[0]
    return None


@frappe.whitelist()
def applyDiscount( quote_name: str,discount:float):
    require_onecpq_role()
    settings = frappe.get_doc("Cvs Settings")
    cart_item_minimum_discount = settings.get("cart_item_minimum_discount")
    cart_item_maximum_discount = settings.get("cart_item_maximum_discount")
    if(discount != None and (discount < cart_item_minimum_discount or discount > cart_item_maximum_discount)):frappe.throw('Can Apply discount between '+str(cart_item_minimum_discount)+' to '+str(cart_item_maximum_discount))
    
    cartItems = get_cart_items(quote_name)
    # print(cartItems)
    for item in cartItems:
        item = frappe.frappe.get_doc("BtbCartItem", item.name)
        item.discount = discount
        item.db_update()
    sync_all(quote_name)
    # items = get_synced_items(quote_name)
    # doc = frappe.frappe.get_doc("Quotation", quote_name)
    # doc.save()
    # totalUnitPrice = 0
    # totalLineDiscount = 0
    # totalDiscountPercenatge = 0
    # totalLineDiscountPercentage = 0
    # for item in items: 
    #     totalUnitPrice += (item.ciQty * item.unit_price)
    #     totalLineDiscount +=  (item.ciQty * ((item.unit_price) * item.ciDiscount/100))
    # totalDiscount = totalLineDiscount + doc.discount_amount
    # if(totalUnitPrice>0) : 
    #     totalDiscountPercenatge = (totalDiscount/totalUnitPrice) * 100
    #     totalLineDiscountPercentage = (totalLineDiscount/totalUnitPrice) * 100
    # doc.custom_list_amount = totalUnitPrice
    # doc.custom_discount = totalLineDiscountPercentage
    # doc.custom_total_discount_amount = totalDiscount
    # doc.custom_total_discount = totalDiscountPercenatge
    # calculate_taxes_and_totals(doc)

# @frappe.whitelist()
# def lock_cart( quote_name: str, lock:bool) :
#     sql = f""" select parent from `tabBtbCartLink` cl join `tabBtbCart` c on cl.parent = c.name and c.locked !='{lock}' 
#     where entity='{quote_name}'
#     """
#     items = frappe.db.sql(sql, as_dict=1)
#     for item in items:
#         cart = frappe.frappe.get_doc("BtbCart", item.parent)
#         cart.locked = lock
#         cart.save()

@frappe.whitelist()
def get_cart_items( quote_name: str) :
    sql = """ select name,discount
    from tabBtbCartItem tbc where tbc.cart in (
    select parent from `tabBtbCartLink` where entity = %(quote_name)s
    )
    order by tbc.idx
    
    """
    items = frappe.db.sql(sql, {"quote_name": quote_name}, as_dict=1)
    return items

# @frappe.whitelist()
# def amendCPQ(quote_name: str,amended_from: str):
#     print('inside amendCPQ',quote_name)
#     print('inside amendCPQ amended_from',amended_from)
#     cart_name = create_cart(quote_name)
#     cartItems = get_synced_items(amended_from)
#     print('inside amendCPQ cartItems',cartItems)
#     # clonedItems=[]
#     seq = 1
#     for item in cartItems:
#         cartItem = frappe.frappe.get_doc("BtbCartItem", item.ciName)
#         cartItem.name = None
#         cartItem.cart = cart_name
#         cartItem.idx = seq
#         seq +=1
#         ciLinks =[]
#         for cil in cartItem.cart_item_links:
#             cil.entity = quote_name
#             ciLinks.append(cil)
#         cartItem.cart_item_links = ciLinks
#         # cartItem.cart_item_links =[]
#         cartItem.save()
#     quot = frappe.frappe.get_doc("Quotation", quote_name)
#     quot.custom_cpq_amended = 1
#     quot.db_update()

@frappe.whitelist()
def amendCPQ(quote_name: str,amended_from: str):
    require_onecpq_role()
    print('inside amendCPQ',quote_name)
    print('inside amendCPQ amended_from',amended_from)
    # it rebuilds quote_name's cart from amended_from's, so it needs both
    frappe.has_permission("Quotation", "write", quote_name, throw=True)
    frappe.has_permission("Quotation", "read", amended_from, throw=True)
    cartsql = """select parent from tabBtbCartLink tbcl where entity = %(quote_name)s"""
    avl_cart = frappe.db.sql(cartsql, {"quote_name": quote_name}, as_dict=1)
    if(len(avl_cart)>0):return avl_cart[0].parent
    cart_name = create_cart(quote_name)
    copy_cart_to_quote(get_synced_items(amended_from), quote_name, cart_name)
    # drop only generated outputs copied from the source; user uploads (drawings, POs) stay
    attachments = frappe.get_all("File", filters={"attached_to_doctype": "Quotation", "attached_to_name": quote_name}, fields=["name", "file_name"])
    for file in attachments:
        if((file.file_name or "").startswith(GENERATED_FILE_PREFIXES)):
            frappe.delete_doc("File", file.name, force=1, ignore_permissions=True)
    frappe.db.set_value("Quotation", quote_name, "custom_cpq_amended", 1, update_modified=False)
    print('inside amendCPQ amended')
    return 'Cart Amended'


# Columns a copy gets fresh values for instead of the source's
COPY_FRESH_NULLS = ("_user_tags", "_comments", "_assign", "_liked_by")
COPY_CHUNK = 500

def copy_cart_to_quote(source_lines, quote_name: str, cart_name: str):
    """Copies the source quote's cart items (with their features and links) into
    cart_name, numbered 1..n in the source's line order, and copies the source's
    quote lines onto quote_name pointing at the copies.

    Done with INSERT ... SELECT, one statement per table and chunk: loading every
    cart item (~150 feature rows each) and quote line as a document took ~16,000
    queries and 10-17 s for 50 items. Copies get random names; their child rows and
    lines get a random prefix plus a row number, which is unique by construction
    (a bulk insert can't retry a clashing name the way doc.insert() does)."""
    user, now = frappe.session.user, frappe.utils.now()
    new_cart_item = {}
    cart_items = []   # (source cart item, copy, seq)
    lines = []        # (source line, copy of its cart item, seq)
    for line in source_lines:
        if(line.ciName not in new_cart_item):
            name = make_autoname("hash", "BtbCartItem")
            while name in new_cart_item.values(): name = make_autoname("hash", "BtbCartItem")
            new_cart_item[line.ciName] = name
            cart_items.append((line.ciName, name, len(cart_items) + 1))
        lines.append((line.name, new_cart_item[line.ciName], len(lines) + 1))

    stamp = {"creation": ("%s", [now]), "modified": ("%s", [now]), "owner": ("%s", [user]), "modified_by": ("%s", [user])}
    for chunk in chunked(cart_items):
        insert_copies("BtbCartItem", chunk, "src.name = m.src", {
            "name": ("m.dst", []), "cart": ("%s", [cart_name]), "idx": ("m.seq", []), "sequence": ("m.seq", []), **stamp})
        for df in frappe.get_meta("BtbCartItem").get_table_fields():
            child_overrides = {"name": ("concat(%s, row_number() over (order by m.seq, src.idx))", [frappe.generate_hash(length=8)]),
                               "parent": ("m.dst", []), **stamp}
            if(df.options == "BtbCartItemLink"): child_overrides["entity"] = ("%s", [quote_name])
            insert_copies(df.options, chunk, "src.parent = m.src and src.parenttype = 'BtbCartItem' and src.parentfield = %s",
                          child_overrides, [df.fieldname])
    for chunk in chunked(lines):
        insert_copies("Quotation Item", chunk, "src.name = m.src", {
            "name": ("concat(%s, row_number() over (order by m.seq))", [frappe.generate_hash(length=8)]),
            "parent": ("%s", [quote_name]), "idx": ("m.seq", []), "custom_cart_item": ("m.dst", []), "docstatus": ("0", []), **stamp})

def chunked(rows):
    for i in range(0, len(rows), COPY_CHUNK):
        yield rows[i:i + COPY_CHUNK]

def insert_copies(doctype: str, mapping, join_on: str, overrides: dict, join_params = None):
    """INSERT INTO tab<doctype> SELECT every column of the source rows matched through
    mapping [(src, dst, seq)], with overrides {column: (sql expression, params)}."""
    columns = frappe.db.get_table_columns(doctype)
    exprs, params = [], []
    for col in columns:
        if(col in overrides):
            expr, values = overrides[col]
        elif(col in COPY_FRESH_NULLS):
            expr, values = "null", []
        else:
            expr, values = f"src.`{col}`", []
        exprs.append(expr); params += values
    derived = " union all ".join(["select %s src, %s dst, %s seq"] * len(mapping))
    params += [v for row in mapping for v in row] + list(join_params or [])
    frappe.db.sql(f"""insert into `tab{doctype}` ({", ".join(f"`{c}`" for c in columns)})
        select {", ".join(exprs)} from `tab{doctype}` src join ({derived}) m on {join_on}""", params)

def create_cart(quote_name: str):
   
    cartLink = frappe.new_doc("BtbCartLink")
    cartLink.entity_type = "Quotation"
    cartLink.entity = quote_name
    cart = frappe.new_doc("BtbCart")
    cart.append('cart_links', cartLink)
    cart.insert()
    return cart.name

@frappe.whitelist()
def sync_all(quote_name, method = None):
    require_onecpq_role()
    cartsql = """select parent from tabBtbCartLink tbcl where entity = %(quote_name)s"""
    carts = frappe.db.sql(cartsql, {"quote_name": quote_name}, as_dict=1)
    if(len(carts) == 0): frappe.throw(frappe._("This quotation has no OneCPQ cart yet. Open the OneCPQ cart and add items first."))
    cart = carts[0].parent
    sql = """ select tbc.name
    from tabBtbCartItem tbc where tbc.valid = 1 and tbc.cart = %(cart)s and tbc.name not in (
    select parent from tabBtbCartItemLink tbcil where entity = %(quote_name)s
    )"""
    # qitems = []
    # sql = f"""
	# 	select name,conversion_rate  from `tabQuotation` tqi where name ='{quote_name}'
	# """
    # qt= frappe.db.sql(sql, as_dict=1)[0]
    for item in frappe.db.sql(sql, {"cart": cart, "quote_name": quote_name}, as_dict=1): 
        ci = populate_cart_item_links(quote_name, item)
        ci.db_insert()
    # cartItems = get_all_cart_items(cart)
    # for item in cartItems: 
    #     quoteItem = frappe.frappe.new_doc("Quotation Item")
    #     quoteItem = populate_quotation_item(quoteItem, ci, qt)
    #     quoteItem.db_insert()
    #     qitems.append(quoteItem)
    quote = frappe.frappe.get_doc("Quotation", quote_name)
    # quote.items = qitems
    # calculate_taxes_and_totals(quote)
    quote.save()

def get_all_cart_items(name:str):
	sql = """
		select ci.name, item, price_list, list_price, unit_price, quantity, discount,
			i.item_name, i.item_code,ci.idx,i.stock_uom,ci.idx,i.description
		from `tabBtbCartItem` ci
		join `tabItem` i on ci.item = i.name
		where ci.cart = %(name)s
	"""
	return frappe.db.sql(sql, {"name": name}, as_dict=1)

def populate_cart_item_links(quote_name:str,item:any):
    ci = frappe.frappe.new_doc("BtbCartItemLink")
    ci.entity = quote_name
    ci.entity_type = "Quotation"
    ci.parent = item.name
    ci.parenttype = "BtbCartItem"
    ci.parentfield = "cart_item_links"
    return ci

def populate_quotation_item(doc, cartItem, qt):
    doc.parenttype = 'Quotation'
    doc.parent = qt.name
    doc.parentfield= "items"
    doc.uom = cartItem.stock_uom
    doc.conversion_factor = 1
    doc.item_code = cartItem.item
    doc.item_name = cartItem.item_name
    doc.qty = cartItem.quantity
    doc.base_price_list_rate = cartItem.list_price
    doc.price_list_rate = cartItem.list_price / qt.conversion_rate
    doc.base_rate = cartItem.unit_price -  (cartItem.discount * cartItem.unit_price/100)
    doc.rate = doc.base_rate / qt.conversion_rate
    doc.base_amount = cartItem.quantity * doc.base_rate
    doc.amount = doc.base_amount / qt.conversion_rate
    doc.idx = cartItem.idx
    doc.description = cartItem.title
    doc.custom_cart_item = cartItem.name
    if(cartItem.custom_configurable == 1):
        if(cartItem.model_item_code):doc.item_code = cartItem.model_item_code
        if(cartItem.model_stock_uom):doc.uom = cartItem.model_stock_uom
        if('tagRef' in cartItem) : doc.tag_ref = cartItem.tagRef
        if('item' in cartItem):
            if(cartItem.item == 'ULRD' or cartItem.item == 'SIL' or cartItem.item == 'VCDA'): 
                if('notesInput' in cartItem) : doc.notes = cartItem.notesInput
        elif('notes' in cartItem) : doc.notes = cartItem.notes
    return doc

@frappe.whitelist()
def get_linked_carts_for_quotation(quotation):
    carts = frappe.db.sql("""
        SELECT DISTINCT parent
        FROM `tabBtbCartLink`
        WHERE entity = %s
        AND entity_type = 'Quotation'
    """, quotation, as_dict=True)

    return carts