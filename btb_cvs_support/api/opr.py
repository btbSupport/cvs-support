import frappe
#DEV API Key = dd017c3d9d14afe:2aba5089f049917
@frappe.whitelist()
def get_pending_quantities(sales_order_number: str, opr_name: str):
    items = get_items(sales_order_number)
    ordered_items = get_ordered_items(sales_order_number, opr_name)
    output = []
    for item in items:
        code = item["item_code"]
        ordered_qty = 0
        if(code in ordered_items):
            ordered_qty = ordered_items[code] 
        if(item["qty"] == ordered_qty):
            continue
        output.append({"item_code": code, "description": item["description"], "uom": item["uom"],
                       "rate": item["rate"], "quantity": item["qty"] - ordered_qty,
                       "custom_manufactured_item": item["custom_manufactured_item"]})
    return output

def get_items(sales_order_number: str):
    sql = f"""
        select i.item_code, i.description, soi.rate, soi.uom, sum(qty) qty,
            i.custom_manufactured_item
        from `tabSales Order Item` soi
        join tabItem i on soi.item_code = i.item_code
        where soi.parent = '{sales_order_number}'
        group by i.item_code, i.description, soi.rate, soi.uom
    """
    return frappe.db.sql(sql, as_dict=1)

def get_ordered_items(sales_order_number: str, opr_name: str):
    sql = f"""
        Select qt.item_code, sum(qt.quantity) qty
        from `tabQuantities Table` qt
        join `tabOrder Processing Request` opr on qt.parent = opr.name
        where opr.sales_order = '{sales_order_number}'
        and opr.name != '{opr_name}'
        group by qt.item_code
        
        union all
        
        select acc.item, sum(acc.quantity)
        from `tabAccessories` acc
        join `tabOrder Processing Request` opr on acc.parent = opr.name
        where opr.sales_order = '{sales_order_number}'
        and opr.name != '{opr_name}'
        group by acc.item
    """
    items = frappe.db.sql(sql, as_dict=1)
    output = {}
    for item in items:
        print(item)
        output[item["item_code"]] = item["qty"]
    return output