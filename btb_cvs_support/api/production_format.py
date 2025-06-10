from datetime import datetime
import json
import re
from typing import Dict
import os
import frappe
import pandas as pd
from .btb_quotation import *
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
    qt = getQuoteById(quote_name)
    output = {}
    productFamilyMap = populate_product_family_map()
    models = populateProductMap(quote_name)
    file_name = quote_name+'.xlsx'
    file_url = '/private/files/'+file_name
    file_path = frappe.utils.get_bench_path()+'/sites/'+frappe.utils.get_site_base_path()[2:]+file_url

    frappe.log('file_path : '+file_path)
    with pd.ExcelWriter(file_path) as writer:
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
            df.to_excel(writer,sheet_name=subCat,index=False,header=False)
    file_doc = frappe.new_doc("File")
    file_doc.file_name = file_name
    file_doc.folder = "Home"
    file_doc.is_private = 1
    file_doc.file_url = file_url
    file_doc.attached_to_doctype = "Quotation",
    file_doc.attached_to_name = quote_name
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
    models = populate_cart_item_model(quote_name)
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
    base_path = os.path.dirname(__file__)
    file_path = os.path.join(base_path, 'productionsheet_format.JSON')
    with open(file_path, 'r') as f:
        setting_json = json.load(f)
    return json.loads(json.dumps(setting_json))
