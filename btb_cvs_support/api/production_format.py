from datetime import datetime
import json
import re
from typing import Dict, List
import os
import frappe
import pandas as pd
import numpy as np
import csv
fti_cache ={}
subCategoryMap={}

class ProductInfo:
    def __init__( header="", total="", tableHeader="", detail=""):
        header = header
        total = total
        tableHeader = tableHeader
        detail = detail

class ProductNode:
    def __init__( productName="", items=""):
        productName = productName
        items = items

@frappe.whitelist()
def populate_cart_detail( quote_name:str):
    print('quote_name : ',quote_name)
    qt = getQuoteById(quote_name)
    output = {}
    productFamilyMap = populate_product_family_map()
    models = populateProductMap(quote_name)
    # base_path = os.path.dirname(__file__)  # Path to the current .py file
    # file_path = os.path.join(base_path, quote_name+'.xlsx')
    file_name = quote_name+'.xlsx'
    file_url = '/private/files/'+file_name
    file_path = frappe.utils.get_bench_path()+'/sites/'+frappe.utils.get_site_base_path()[2:]+file_url

    frappe.log('file_path : '+file_path)
    with pd.ExcelWriter(file_path,engine='xlsxwriter') as writer:
        for subCat, features in models.items():
            productCode = subCategoryMap.get(subCat)
            if productCode not in productFamilyMap:
                continue
            detail = productFamilyMap[productCode]
            keys = detail.get('detail').split(',')
            pn = ProductNode()
            pn.productName = f"{qt.customer_name}-{qt.name} - {subCat}"
            pn.items = []
            pn.items.append(populateHeader(qt, detail.get('header'), subCat))
            pn.items.append(populateTotal(detail.get('total').split(','), features))
            pn.items.append(detail.get('tableHeader').split(','))
            for det in populateDetail(keys, features):
                pn.items.append(det)
            output[subCat] = pn.__dict__
            df = pd.DataFrame(pn.items)
            # base_path = os.path.dirname(__file__)  # Path to the current .py file
            # csv_file_path = os.path.join(base_path, pn.productName+'.csv')
            # df.to_csv(csv_file_path,index=False,header=False)
            df.to_excel(writer,sheet_name=subCat,index=False,header=False)
            # with open(csv_file_path, mode='w', newline='') as file:
            #     # Create a csv.writer object
            #     writer = csv.writer(file)
            #     # Write data to the CSV file
            #     writer.writerows(pn.items)
    file_doc = frappe.new_doc("File")
    file_doc.file_name = file_name
    file_doc.folder = "Home"
    file_doc.is_private = 1
    file_doc.file_url = file_url
    file_doc.attached_to_doctype = "Quotation",
    file_doc.attached_to_name = quote_name

    # file_doc = frappe.get_doc("File", {"file_name": quote_name+'.xlsx'})
    # print('print file doc : ',file_doc)
    # file_doc.attached_to_doctype = "Quotation",
    # file_doc.attached_to_name = quote_name
    file_doc.save()
    return output

def populateHeader( qt, header, subCat):
    replacements = {
        '${compName}': qt['company'],
        '${project}': qt['project'],
        '${curUser}': 'Current User', 
        '${qNo}': qt['name'],
        '${subCat}': subCat,
        '${date}': datetime.now().strftime('%Y-%m-%d')
    }
    for key, value in replacements.items():
        if(value == None) : value =''
        header = header.replace(key, value)
    return header.split(',')

def populateTotal( keys, features):
    row = []
    for i, key in enumerate(keys):
        if i == 0 or key == '':
            row.append(key)
        else:
            row.append(str(getSUM(key, features)))
    return row

def getSUM( key, features):
    total = 0
    for ft in features:
        val = populateValue(ft, key)
        if val == '-':
            continue
        total += float(val)
    return total

def populateDetail( keys, features):
    output = []
    for i, ft in enumerate(features):
        row = [str(i + 1)]
        for key in keys:
            row.append(str(populateValue(ft, key)))
        output.append(row)
    return output

def populateValue( features, formula):
    if not formula.startswith(('MUL(', 'SUM(', 'SUB(', 'DIV(')):
        return getValue(features, formula)
    result = None
    for k in execFormula(formula):
        val = str(getValue(features, k))
        if val == '-':
            val = '0'
        val = float(val)
        if result is None:
            result = val
        else:
            if formula.startswith('MUL('):
                result *= val
            elif formula.startswith('SUM('):
                result += val
            elif formula.startswith('SUB('):
                result -= val
            elif formula.startswith('DIV('):
                result /= val
    return result

def execFormula( formulae):
    if formulae.startswith('MUL('):
        pattern = r'MUL\((.*)\)'
        splitstring = ' x '
    elif formulae.startswith('SUM('):
        pattern = r'SUM\((.*)\)'
        splitstring = r' \+ '
    elif formulae.startswith('SUB('):
        pattern = r'SUB\((.*)\)'
        splitstring = r' \- '
    elif formulae.startswith('DIV('):
        pattern = r'DIV\((.*)\)'
        splitstring = r' \/ '
    else:
        return []
    match = re.search(pattern, formulae)
    return match.group(1).split(splitstring) if match else []

def getValue( features, key):
    if key in features:
        return features[key]['value']
    return '-'

def populateProductMap(quote_name):
    output = {}
    models = populateCartItemModel(quote_name)
    for cartModel in models:
        productCode = getKey(cartModel, 'cartProductCode')
        subCategory = getKey(cartModel, 'subcategory')
        subCategoryMap[subCategory] = productCode
        if subCategory not in output:
            output[subCategory] = []
        output[subCategory].append(cartModel)
    return output

def getKey( features, key):
    keys = key.split(',')
    output = [str(features[k]['value']) for k in keys if k in features]
    return '-'.join(output)


def populate_product_family_map() -> Dict[str, 'ProductInfo']:
    base_path = os.path.dirname(__file__)  # Path to the current .py file
    file_path = os.path.join(base_path, 'productionsheet_format.JSON')
    # file_path = '../apps/btb_cvs_support/btb_cvs_support/api/productionsheet_format.JSON'
    with open(file_path, 'r') as f:
        setting_json = json.load(f)
    return json.loads(json.dumps(setting_json))

@frappe.whitelist()
def getQuoteById( quote_name):
    sql = f"""
		select *  from `tabQuotation` tqi where name ='{quote_name}'
	"""
    return frappe.db.sql(sql, as_dict=1)[0]

def populateCartItemModel( quote_name):
    cartItems = get_cart_items(quote_name)
    populate_featuretype_items(cartItems)
    return populate_cart_models(cartItems)

@frappe.whitelist()
def get_cart_items( quote_name: str) -> List[Dict[str, any]]:
    # print('inside get cart items')
    sql = f""" select tbc.name,tbc.Unit_Price,tbc.discount , tbc.Sequence, tbc.Quantity, tbc.Title,
        i.Name itemName, i.item_code, tbf.Field, tbf.label ,
        tbcif.value cif_value,tbfti.value fti_value,tbfti.`object` obj_value,tbft.object_type obj_type,tbft.data_text_field 
    from tabBtbCartItem tbc
    join `tabItem` i on tbc.item  = i.name and   tbc.name in (
    select custom_cart_item from `tabQuotation Item` where parent='{quote_name}'
    )
    join tabBtbCartItemFeature tbcif on tbcif.parent = tbc.name
    join tabBtbFeature tbf  on tbf.name = tbcif.feature 
    left join tabBtbFeatureTypeItem tbfti on tbcif.value = tbfti.name
    left join tabBtbFeatureType tbft on tbft.name = tbfti.feature_type
    """
    items = frappe.db.sql(sql, as_dict=1)

    # with open('sample_cart_item.csv') as sample_file:
    #     items = sample_file.read()
    # print('result cart items ',items)
    df = pd.DataFrame(json.loads(json.dumps(items)))
    
    # df = pd.read_csv('sample_cart_item.csv')
    res = df.groupby(["name","Unit_Price","discount","Sequence","Quantity","Title","itemName","item_code"], group_keys=False)
    # print(df.groupby(["name","Unit_Price","discount","Sequence","Quantity","Title","itemName","item_code"]))
    # print(items.get_group('CI30583'))
    return res

def populate_featuretype_items( cartItems):
    for group_name, df_group in cartItems:
        ftis =  {}
        for row_index, row in df_group.iterrows():
            if(row.obj_type != None):
                key = str(row.obj_type)+'-'+str(row.data_text_field)+'-'+str(row.cif_value)
                if( key not in ftis.keys()):ftis[key] = []
                if( row.obj_value not in fti_cache.keys()):ftis[key].append(row.obj_value)
        for key in ftis.keys():
            # print("check ",key)
            if(key == None): continue
            fti = ftis.get(key)
            obj = key.split("-")
            get_featuretype_items(obj[0],obj[1],fti,obj[2])

def populate_cart_models( cartItems: Dict[str,any]) -> List[Dict[str, Dict]]:
    output =[]
    # print('fti_cache : ',fti_cache)
    for group_name, df_group in cartItems:
        item =  {}
        for row_index, row in df_group.iterrows():
            if(item == {}):
                item =  {
                "cartProductName": {"value": row.itemName},
                "cartProductCode": {"value": row.item_code},
                "qty": {"value": row.Quantity},
                "unitPrice": {"value": row.Unit_Price},
                "beforeDiscount": {"value":  row.Quantity * row.Unit_Price },
                "rate": {"value": row.Unit_Price*(1-(row.discount/100))},
                "amount": {"value": row.Unit_Price*(1-(row.discount/100))*row.Quantity},
                "seq": {"value": row.Sequence}
                }
            value = row.cif_value
            if(row.fti_value != None):value = row.fti_value
            if(row.obj_type != None):value = fti_cache.get(row.cif_value)
            item[row.Field]={"label": row.label, "value": value}
        output.append(item)
    return output  

def get_featuretype_items( tabName:str, data_text_field:str, values: List[str],fti:str):
    sql = f"""
    select * from `tab{tabName}` where name in {'',''.join(values)}
    """
    result = frappe.db.sql(sql, as_dict=1)
    for i in result:
        fti_cache[fti] = i[data_text_field]

