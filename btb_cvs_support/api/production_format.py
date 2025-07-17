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
    file_name = 'Production Sheet_'+quote_name+'.xlsx'
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
            for det in populateHeader(qt, detail.get('header'), subCat):
                pn.items.append(det.split('\t'))
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
    header = header.replace(',', '\t')
    for key, value in replacements.items():
        if(value == None) : value =''
        header = header.replace(key, value)
    return header.split('\n')

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
    if(key =='damperType'):
        if(str(features['modelNo']['value']).startswith('FDD')): return 'Dynamic'
        return 'Static'
    if(key =='frameType'):
        modelNo = features['modelNo']['value']
        if( str(modelNo).endswith('-I')): return 'Slim Line'
        return 'Double T'
    if(key =='modelNoSplit'):
        output = ''
        if('modelName' in features):
            output += features['modelName']['value'].split(' ')[0]
        return output
    if(key =='fuseLinkConcat') :
        output = ''
        if('storOrDtorOption' in features):
            output += features['storOrDtorOption']['value']
        if('linkTemperature' in features):
            output += ' '+features['linkTemperature']['value']
        return output
    if(key =='fusibleLinkTempConcat') :
        output = ''
        if('fusibleLinkTemp' in features):
            output += features['fusibleLinkTemp']['value']
        if('linkType' in features):
            output += features['linkType']['value']
        return output
    if(key =='microSwitch') :
        output = ''
        noOfSections = 0
        qty = 0
        if('noofSections' in features):
            noOfSections = Decimal(features['noofSections']['value'])
        if('limitSwitchRequired' in features and features['noofSections']['value'] == 'Yes'):
            qty = Decimal(features['qty']['value'])
        return str((noOfSections*qty))
    if(key =='4Inch' or key =='5Inch' or key =='6Inch' or key =='7Inch' or key =='TotalBlades'):
        output = 0
        if(key =='TotalBlades' or ('bladeInch1' in features and features['bladeInch1'] != None and features['bladeInch1']['value'] != None and features['bladeInch1']['value']+'Inch' == key)):
            output += Decimal(features['noOfBladesPerSection1']['value'])
        
        if(key =='TotalBlades' or ('bladeInch2' in features and features['bladeInch2'] != None and features['bladeInch2']['value'] != None and features['bladeInch2']['value']+'Inch' == key)):
            output += Decimal(features['noOfBladesPerSection2']['value'])
        return output
    if(key =='actModelConcat1') :
        output = ''
        if('actModel1' in features and features['actModel1'] != None and features['actModel1']['value'] != None ):
             output += features['actModel1']['value']
        if('actuatorTorqueSize' in features and 'actModel2' in features  and features['actModel2'] != None and features['actModel2']['value'] != None and features['actuatorTorqueSize']['value'] != 'Optimize'):
             output += ' '+features['actModel2']['value']
        return output
    if(key =='actModelConcat2') :
        output = ''
        if('actModel2' in features and 'actuatorTorqueSize' in features and features['actModel2'] != None and features['actModel2']['value'] != None and features['actuatorTorqueSize']['value'] == 'Optimize'):
            output += features['actModel2']['value']
        return output
    if(key =='bladeLengthMeter' and 'bladeLength' in features)  :      
            return (Decimal(features['bladeLength']['value']))/1000
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
