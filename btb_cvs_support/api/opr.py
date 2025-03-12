import frappe
#DEV API Key = dd017c3d9d14afe:2aba5089f049917
@frappe.whitelist()
def get_pending_quantities(sales_order_number: str, opr_name: str):
    items = get_items(sales_order_number)
    ordered_items = get_ordered_items(sales_order_number, opr_name)
    output = []
    for item in items:
        detail = item["so_detail"]
        ordered_qty = 0
        if(detail in ordered_items):
            ordered_qty = ordered_items[detail] 
        if(item["qty"] == ordered_qty):
            continue
        output.append({"so_detail": detail, "description": item["description"], "item_code": item["item_code"], "uom": item["uom"],
                       "rate": item["rate"], "quantity": item["qty"] - ordered_qty,
                       "custom_manufactured_item": item["custom_manufactured_item"]})
    return output

def get_items(sales_order_number: str):
    sql = f"""
        select soi.name so_detail, soi.description, soi.item_code, soi.rate, soi.uom, qty,
            i.custom_manufactured_item
        from `tabSales Order Item` soi
        join `tabItem` i on soi.item_code = i.item_code
        where soi.parent = '{sales_order_number}'
        
    """
    return frappe.db.sql(sql, as_dict=1)

def get_ordered_items(sales_order_number: str, opr_name: str):
    sql = f"""
        Select qt.so_detail, sum(qt.quantity) qty
        from `tabQuantities Table` qt
        join `tabOrder Processing Request` opr on qt.parent = opr.name
        where opr.sales_order = '{sales_order_number}'
        and opr.name != '{opr_name}'
        group by qt.so_detail
        
        union all
        
        select acc.so_detail, sum(acc.quantity)
        from `tabAccessories` acc
        join `tabOrder Processing Request` opr on acc.parent = opr.name
        where opr.sales_order = '{sales_order_number}'
        and opr.name != '{opr_name}'
        group by acc.so_detail
    """
    items = frappe.db.sql(sql, as_dict=1)
    output = {}
    for item in items:
        print(item)
        output[item["so_detail"]] = item["qty"]
    return output