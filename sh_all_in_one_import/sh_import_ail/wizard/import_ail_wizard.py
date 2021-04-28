# -*- coding: utf-8 -*-
# Part of Softhealer Technologies.

from odoo import api, fields, models, _
from datetime import datetime
from odoo.exceptions import UserError, AccessError
import csv
import base64
import io as StringIO
import xlrd
from odoo.tools import ustr

class import_ail_wizard(models.TransientModel):
    _name="import.ail.wizard"
    _description = "import invoice line wizard"          

    import_type = fields.Selection([
        ('csv','CSV File'),
        ('excel','Excel File')
        ],default="csv",string="Import File Type",required=True)
    file = fields.Binary(string="File",required=True)   
    product_by = fields.Selection([
        ('name','Name'),
        ('int_ref','Internal Reference'),
        ('barcode','Barcode')
        ],default="name", string = "Product By", required = True) 

    @api.multi
    def show_success_msg(self,counter,skipped_line_no):
        
        #to close the current active wizard        
        action = self.env.ref('sh_all_in_one_import.sh_import_ail_action').read()[0]
        action = {'type': 'ir.actions.act_window_close'} 
        
        #open the new success message box    
        view = self.env.ref('sh_message.sh_message_wizard')
        view_id = view and view.id or False                                   
        context = dict(self._context or {})
        dic_msg = str(counter) + " Records imported successfully"
        if skipped_line_no:
            dic_msg = dic_msg + "\nNote:"
        for k,v in skipped_line_no.items():
            dic_msg = dic_msg + "\nRow No " + k + " " + v + " "
        context['message'] = dic_msg            
        
        return {
            'name': 'Success',
            'type': 'ir.actions.act_window',
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'sh.message.wizard',
            'views': [(view.id, 'form')],
            'view_id': view.id,
            'target': 'new',
            'context': context,
            }   

    
    @api.multi
    def import_ail_apply(self):
        ail_obj = self.env['account.invoice.line']
        #perform import lead
        if self and self.file and self.env.context.get('sh_inv_id',False):
            #For CSV
            if self.import_type == 'csv':
                counter = 1
                skipped_line_no = {}
                active_inv = False
                try:
                    file = str(base64.decodestring(self.file).decode('utf-8'))
                    myreader = csv.reader(file.splitlines())
                    skip_header=True
                     
                    for row in myreader:
                        try:
                            if skip_header:
                                skip_header=False
                                counter = counter + 1
                                continue

                            if row[0] != '': 
                                vals={}
                                
                                field_nm = 'name'
                                if self.product_by == 'name':
                                    field_nm = 'name'
                                elif self.product_by == 'int_ref':
                                    field_nm = 'default_code'
                                elif self.product_by == 'barcode':
                                    field_nm = 'barcode'
                                
                                search_product = self.env['product.product'].search([(field_nm,'=',row[0])], limit = 1)
                                active_inv = self.env['account.invoice'].search([('id','=',self.env.context.get('sh_inv_id'))], limit = 1)                                
                                if search_product and active_inv:
                                    vals.update({'product_id' : search_product.id})
                                    
                                    if row[1] != '':
                                        vals.update({'name' : row[1] })
                                    else:
                                       
                                        if active_inv and active_inv.partner_id:
                                            if active_inv.partner_id.lang:
                                                product = search_product.with_context(lang=active_inv.partner_id.lang)
                                            else:
                                                product = search_product

                                            name = product.partner_ref
                                        if active_inv.type in ('in_invoice', 'in_refund'):
                                            if product.description_purchase:
                                                name += '\n' + product.description_purchase
                                        else:
                                            if product.description_sale:
                                                name += '\n' + product.description_sale                                          
                                        vals.update({'name' : name})
                                            
                                    accounts = search_product.product_tmpl_id.get_product_accounts(active_inv.fiscal_position_id)
                                    account = False
                                    if active_inv.type in ('out_invoice', 'out_refund'):
                                        account =  accounts['income']
                                    else:
                                        account = accounts['expense']        
                                    if account == False:
                                        skipped_line_no[str(counter)]= " - Account not found. " 
                                        counter = counter + 1
                                        continue                                        
                                    else:
                                        vals.update({'account_id' : account.id})
                                            
                                        
                                    if row[2] != '':
                                        vals.update({'quantity' : row[2] })
                                    else:
                                        vals.update({'quantity' : 1 })
                                    
                                    if row[3] in (None,""):
                                        if active_inv.type in ('in_invoice', 'in_refund') and search_product.uom_po_id:
                                            vals.update({'uom_id' : search_product.uom_po_id.id })
                                        elif search_product.uom_id:
                                            vals.update({'uom_id' : search_product.uom_id.id })                                       
                                    else:
                                        search_uom = self.env['uom.uom'].search([('name','=',row[3] )], limit = 1) 
                                        if search_uom:
                                            vals.update({'uom_id' : search_uom.id })
                                        else:
                                            skipped_line_no[str(counter)]= " - Unit of Measure not found. " 
                                            counter = counter + 1
                                            continue
                                    
                                    if row[4] in (None,""):
                                        if active_inv.type in ('in_invoice', 'in_refund'):
                                            vals.update({'price_unit' : search_product.standard_price })
                                        else:
                                            vals.update({'price_unit' : search_product.lst_price })
                                    else:
                                        vals.update({'price_unit' : row[4] })
                                        
                                    if row[5].strip() in (None,""):
                                        if active_inv.type in ('in_invoice', 'in_refund') and search_product.supplier_taxes_id :
                                            vals.update({'invoice_line_tax_ids' : [(6, 0, search_product.supplier_taxes_id.ids)]})
                                        elif active_inv.type in ('out_invoice', 'out_refund') and search_product.taxes_id:
                                            vals.update({'invoice_line_tax_ids' : [(6, 0, search_product.taxes_id.ids)]})
                                            
                                    else:
                                        taxes_list = []
                                        some_taxes_not_found = False
                                        for x in row[5].split(','):
                                            x = x.strip()
                                            if x != '':
                                                search_tax = self.env['account.tax'].search([('name','=',x)], limit = 1)
                                                if search_tax:
                                                    taxes_list.append(search_tax.id)
                                                else:
                                                    some_taxes_not_found = True
                                                    skipped_line_no[str(counter)]= " - Taxes " + x +  " not found. "                                                 
                                                    break  
                                        if some_taxes_not_found:
                                            counter = counter + 1
                                            continue
                                        else:
                                            vals.update({'invoice_line_tax_ids' : [(6, 0, taxes_list)]})
                                        
                                else:
                                    skipped_line_no[str(counter)]= " - Product not found. " 
                                    counter = counter + 1 
                                    continue
                                
                                vals.update({'invoice_id' : self.env.context.get('sh_inv_id')})
                                created_ail = ail_obj.create(vals)      
                                counter = counter + 1
                            
                            else:
                                skipped_line_no[str(counter)] = " - Product is empty. "  
                                counter = counter + 1      
                        
                        except Exception as e:
                            skipped_line_no[str(counter)] = " - Value is not valid " + ustr(e)   
                            counter = counter + 1 
                            continue          
                             
#                     calculate taxes
                    if active_inv:
                        active_inv._onchange_partner_id()
                        active_inv._onchange_invoice_line_ids()
                except Exception as e:
                    raise UserError(_("Sorry, Your csv file does not match with our format" + ustr(e) ))
                 
                if counter > 1:
                    completed_records = (counter - len(skipped_line_no)) - 2
                    res = self.show_success_msg(completed_records, skipped_line_no)
                    return res
 
             
            #For Excel
            if self.import_type == 'excel':
                counter = 1
                skipped_line_no = {}   
                active_inv = False                               
                try:
                    wb = xlrd.open_workbook(file_contents=base64.decodestring(self.file))
                    sheet = wb.sheet_by_index(0)     
                    skip_header = True    
                    for row in range(sheet.nrows):
                        try:
                            if skip_header:
                                skip_header = False
                                counter = counter + 1
                                continue
                            
                            if sheet.cell(row,0).value != '': 
                                vals={}
                                
                                field_nm = 'name'
                                if self.product_by == 'name':
                                    field_nm = 'name'
                                elif self.product_by == 'int_ref':
                                    field_nm = 'default_code'
                                elif self.product_by == 'barcode':
                                    field_nm = 'barcode'
                                
                                search_product = self.env['product.product'].search([(field_nm,'=',sheet.cell(row,0).value )], limit = 1)
                                active_inv = self.env['account.invoice'].search([('id','=',self.env.context.get('sh_inv_id'))], limit = 1)                                
                                if search_product and active_inv:
                                    vals.update({'product_id' : search_product.id})
                                    
                                    if sheet.cell(row,1).value != '':
                                        vals.update({'name' : sheet.cell(row,1).value })
                                    else:
                                       
                                        if active_inv and active_inv.partner_id:
                                            if active_inv.partner_id.lang:
                                                product = search_product.with_context(lang=active_inv.partner_id.lang)
                                            else:
                                                product = search_product

                                            name = product.partner_ref
                                        if active_inv.type in ('in_invoice', 'in_refund'):
                                            if product.description_purchase:
                                                name += '\n' + product.description_purchase
                                        else:
                                            if product.description_sale:
                                                name += '\n' + product.description_sale                                          
                                        vals.update({'name' : name})
                                            
                                    accounts = search_product.product_tmpl_id.get_product_accounts(active_inv.fiscal_position_id)
                                    account = False
                                    if active_inv.type in ('out_invoice', 'out_refund'):
                                        account =  accounts['income']
                                    else:
                                        account = accounts['expense']        
                                    if account == False:
                                        skipped_line_no[str(counter)]= " - Account not found. " 
                                        counter = counter + 1
                                        continue                                        
                                    else:
                                        vals.update({'account_id' : account.id})
                                            
                                        
                                    if sheet.cell(row,2).value != '':
                                        vals.update({'quantity' : sheet.cell(row,2).value })
                                    else:
                                        vals.update({'quantity' : 1 })
                                    
                                    if sheet.cell(row,3).value in (None,""):
                                        if active_inv.type in ('in_invoice', 'in_refund') and search_product.uom_po_id:
                                            vals.update({'uom_id' : search_product.uom_po_id.id })
                                        elif search_product.uom_id:
                                            vals.update({'uom_id' : search_product.uom_id.id })                                       
                                    else:
                                        search_uom = self.env['uom.uom'].search([('name','=', sheet.cell(row,3).value )], limit = 1) 
                                        if search_uom:
                                            vals.update({'uom_id' : search_uom.id })
                                        else:
                                            skipped_line_no[str(counter)]= " - Unit of Measure not found. " 
                                            counter = counter + 1
                                            continue
                                    
                                    if sheet.cell(row,4).value in (None,""):
                                        if active_inv.type in ('in_invoice', 'in_refund'):
                                            vals.update({'price_unit' : search_product.standard_price })
                                        else:
                                            vals.update({'price_unit' : search_product.lst_price })
                                    else:
                                        vals.update({'price_unit' : sheet.cell(row,4).value })
                                        
                                    if sheet.cell(row,5).value.strip() in (None,""):
                                        if active_inv.type in ('in_invoice', 'in_refund') and search_product.supplier_taxes_id :
                                            vals.update({'invoice_line_tax_ids' : [(6, 0, search_product.supplier_taxes_id.ids)]})
                                        elif active_inv.type in ('out_invoice', 'out_refund') and search_product.taxes_id:
                                            vals.update({'invoice_line_tax_ids' : [(6, 0, search_product.taxes_id.ids)]})
                                            
                                    else:
                                        taxes_list = []
                                        some_taxes_not_found = False
                                        for x in sheet.cell(row,5).value.split(','):
                                            x = x.strip()
                                            if x != '':
                                                search_tax = self.env['account.tax'].search([('name','=',x)], limit = 1)
                                                if search_tax:
                                                    taxes_list.append(search_tax.id)
                                                else:
                                                    some_taxes_not_found = True
                                                    skipped_line_no[str(counter)]= " - Taxes " + x +  " not found. "                                                 
                                                    break  
                                        if some_taxes_not_found:
                                            counter = counter + 1
                                            continue
                                        else:
                                            vals.update({'invoice_line_tax_ids' : [(6, 0, taxes_list)]})
                                        
                                else:
                                    skipped_line_no[str(counter)]= " - Product not found. " 
                                    counter = counter + 1 
                                    continue
                                
                                vals.update({'invoice_id' : self.env.context.get('sh_inv_id')})
                                created_ail = ail_obj.create(vals)      
                                counter = counter + 1
                            
                            else:
                                skipped_line_no[str(counter)] = " - Product is empty. "  
                                counter = counter + 1      
                        
                        except Exception as e:
                            skipped_line_no[str(counter)] = " - Value is not valid " + ustr(e)   
                            counter = counter + 1 
                            continue          
                             
#                     calculate taxes
                    if active_inv:
                        active_inv._onchange_partner_id()
                        active_inv._onchange_invoice_line_ids()
                except Exception as e:
                    raise UserError(_("Sorry, Your excel file does not match with our format" + ustr(e) ))
                 
                if counter > 1:
                    completed_records = (counter - len(skipped_line_no)) - 2
                    res = self.show_success_msg(completed_records, skipped_line_no)
                    return res