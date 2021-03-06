# -*- coding: utf-8 -*-
########################################################################
#
# @authors: Andres Calle, TRESCloud Cia Ltda.
# Copyright (C) 2013  Ecuadorenlinea.net
#
#This program is free software: you can redistribute it and/or modify
#it under the terms of the GNU General Public License as published by
#the Free Software Foundation, either version 3 of the License, or
#(at your option) any later version.
#
# This module is GPLv3 or newer and incompatible
# with OpenERP SA "AGPL + Private Use License"!
#
#This program is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#GNU General Public License for more details.
#
#You should have received a copy of the GNU General Public License
#along with this program.  If not, see http://www.gnu.org/licenses.
########################################################################

import re
import time
import netsvc
from datetime import date, datetime, timedelta

from osv import fields, osv
from tools import config
from tools.translate import _


class sale_shop(osv.osv):
    _inherit = 'sale.shop'
    _columns = {
                'number':fields.char('SRI Number', size=3, help='This number is assigned by the SRI'),
                'printer_point_ids':fields.one2many('sri.printer.point', 'shop_id', 'Printer Points',),
                'user_ids':fields.many2many('res.users', 'rel_user_shop', 'shop_id', 'user_id', 'Users'),
                'sales_journal_id':fields.many2one('account.journal', 'Sales Journal', domain=[('type','=','sale')]), 
                'purchases_journal_id':fields.many2one('account.journal', 'Purchases Journal', domain=[('type','=','purchase')]), 
               # 'liquidation_journal_id':fields.many2one('account.journal', 'Liquidation of Purchases Journal', domain=[('type','=','purchase'),('liquidation','=',True)]),
                'credit_note_purchase_journal_id':fields.many2one('account.journal', 'Credit Note Purchases Journal', domain=[('type','=','purchase_refund')]),           
                'credit_note_sale_journal_id':fields.many2one('account.journal', 'Credit Note Sales Journal', domain=[('type','=','sale_refund')]),
                #'address_id':fields.many2one('res.partner.address', 'Address', ),
                'establishment_address':fields.related('warehouse_id','partner_id',type='many2one',relation='res.partner',string='Establishment Address',help='The address of the property, used for tax purposes as generating electronic documents'),
                'rows_sale_order': fields.integer('Rows sale order', required = True, help='This value limits the number of editable rows in a tree view.')  
    }
    
    _defaults = {
        'number': '001',
        'rows_sale_order': 20
    }

    def _number_unique(self, cr, uid, ids, context=None):
        """
        Verifica que el número de tienda no pueda repetirse.
        """
        def f(obj):
            #verificamos que no exista OTRO elemento con un numero
            #de sri igual al que tenemos
            return not self.search(cr, uid, [('id', '!=', obj.id), ('number', '=', obj.number)], context=context)
        #devolvemos False si alguno de los elementos tiene su numero repetido
        #en base a otro elemento.
        return all(f(obj) for obj in self.browse(cr, uid, ids, context=context))

    _constraints = [(_number_unique, 'El número de SRI de tienda debe ser único', ['number'])]


#    def _check_number(self,cr,uid,ids,context=None):
#        for n in self.browse(cr, uid, ids):
#            if not n.number:
#                return True
#            a=0
#            b= True
#            while (a<len(n.number)):
#                if(n.number[a]>='0' and n.number[a]<='9'):
#                    a=a+1
#                else:
#                    b=False
#                    break
#            return b
#
#    _constraints = [(_check_number,_('This field is only for numbers'), ['number'])]
#    
    
sale_shop()


class sri_printer_point(osv.osv):
    _name = 'sri.printer.point'
    _inherit = 'trait.context.for.fields'
    _auto = True

    def _get_prefix(self, cr, uid, ids, name, arg, context=None):
        """
        generates the appropiate printer point prefix
        """
        return {obj.id: "%s-%s-" % (obj.shop_id.number, obj.name) if obj.shop_id else ""
                for obj in self.browse(cr, uid, ids, context)}

    _columns = {
        'name': fields.char('Printer Point', size=3, required=True, help='This number is assigned by the SRI'),
        'shop_id': fields.many2one('sale.shop', 'Shop'),
        'invoice_sequence_id': fields.many2one('ir.sequence', string='Customer Invoices sequential', required=False,
                                               help='If specified, will be used by the printer point to specify '
                                                    'the next number for the invoices',
                                               domain=[('code', '=', 'sri.printer.point')]),
        'refund_sequence_id': fields.many2one('ir.sequence', string='Customer Refunds sequential', required=False,
                                              help='If specified, will be used by the printer point to specify '
                                                   'the next number for the credit notes',
                                              domain=[('code', '=', 'sri.printer.point')]),
        'debit_note_sequence_id': fields.many2one('ir.sequence', string='Debit Notes sequential', required=False,
                                                  help='If specified, will be used by the printer point to specify'
                                                       ' the next number for the debit notes',
                                                  domain=[('code', '=', 'sri.printer.point')]),
        'withhold_sequence_id': fields.many2one('ir.sequence', string='Withholds sequential', required=False,
                                                help='If specified, will be used by the printer point to specify '
                                                     'the next number for the withholds',
                                                domain=[('code', '=', 'sri.printer.point')]),
        'waybill_sequence_id': fields.many2one('ir.sequence', string='Waybills sequential', required=False,
                                               help='If specified, will be used by the printer point to specify '
                                                    'the next number for the waybills',
                                               domain=[('code', '=', 'sri.printer.point')]),
        'prefix': fields.function(_get_prefix, method=True, store=False, string="Printer Prefix", type="char", size=8),
        'company_id': fields.related('shop_id', 'company_id', type="many2one", relation="res.company", string="Company",
                                     store=False)
    }

    def get_next_sequence_number(self, cr, uid, printer_id, document_type, number, context=None):
        """
        For a specific type of document, the current printer tries to get
          the next number from the sequence. if no sequence exists, we must
          return the same input number or current printer's prefix. If the
          number is well-formatted and for the current printer point, we must
          return such number - respecting it.
        """

        #we must normalize the number. perhaps it is valid except for spaces
        number = (number or '').strip()

        #we must get the actual printer, and check whether the current number
        #is valid for that printer. by failing in either of them, we return
        #the (normalized) number.
        if isinstance(printer_id, (int, long)):
            printer_id = self.browse(cr, uid, printer_id, context=None)

        if not printer_id or re.match('^\d{3}-\d{3}-\d{9}$', number) and number.startswith(printer_id.prefix):
            return number

        #we get the sequence (its id). If there's no sequence for the given
        #document type, then we must return either the original number (which
        #was normalized) or the printer prefix.
        sequence_id = {
            'invoice': printer_id.invoice_sequence_id,
            'refund': printer_id.refund_sequence_id,
            'debit': printer_id.debit_note_sequence_id,
            'withhold': printer_id.withhold_sequence_id,
            'waybill': printer_id.waybill_sequence_id,
        }.get(document_type, False)

        sequence_id = sequence_id.id if sequence_id else False

        if not sequence_id:
            return number or printer_id.prefix

        #now we have the sequence to query the values from. we should try to
        #generate the number
        return self.pool.get('ir.sequence').next_by_id(cr, uid, sequence_id, context)

    def _verify_repeated_sequences(self, cr, uid, ids, context=None):
        """
        This constraint checks whether the specified sequences are in use by other printer points.

        The logic comes as follows:
            * We collect the assigned sequences, and check whether values are not repeated.
              * It is an error to have repeated values among the sequence fields in the same object.
            * We check that the specified sequence values are not used in any other object. For
              that, we check for each object whether any of its sequence fields has a sequence IN the
              generated list from the current sequence, and has a distinct id (i.e. we're not including
              the current instance in the same criteria).
              * It is an error to find another object which shares either of the sequences in either of
                the fields.
        """

        for instance in self.browse(cr, uid, ids, context=None):
            values = [p and p.id for p in [
                instance.invoice_sequence_id,
                instance.refund_sequence_id,
                instance.debit_note_sequence_id,
                instance.withhold_sequence_id,
                instance.waybill_sequence_id
            ] if p]

            if values:
                #We evaluate this because we set at least one of
                #such fields to an existent ir.sequence reference.

                if len(values) != len(set(values)):
                    #If the length of the list is not the same as the length of a set
                    #with the same elements, it means that the list has REPEATED elements.
                    #
                    #We must get pissed off if that's the case.
                    return False
                found = self.search(cr, uid, ['&', ('id', '!=', instance.id),
                                              '|', ('invoice_sequence_id', 'in', values),
                                              '|', ('refund_sequence_id', 'in', values),
                                              '|', ('debit_note_sequence_id', 'in', values),
                                              '|', ('withhold_sequence_id', 'in', values),
                                                   ('waybill_sequence_id', 'in', values)], context=None)
                if found:
                    #We found an ID which is distinct to the current instance's ID AND
                    #also it has at least one sequence field with value among the values of
                    #the same fields in the current instance.
                    #
                    #We must get pissed off if that's the case.
                    return False
        return True
    
    def name_get(self,cr,uid,ids, context=None):
        if not context:
            context = {}
        res = []
        shop_id=False
        for r in self.read(cr,uid,ids,['name','shop_id'], context):
            name = r['name']
            if r['shop_id']:
                shop_id = r['shop_id'][0] or False
                name_shop = None
                if shop_id:
                    name_shop = self.pool.get('sale.shop').browse(cr, uid, shop_id, context).number
                if name_shop:
                    name_shop+="-"+name
                res.append((r['id'], name_shop))
        return res
    
    def unlink(self, cr, uid, ids, context=None):
        """
        Ademas de eliminar las secuencias de factura asociadas, elimina el
          propio objeto PERO verificando los constraints de restrict (esos
          constraints son de base de datos).
        """
        for obj in self.browse(cr, uid, ids, context=context):
            if obj.invoice_sequence_id:
                obj.invoice_sequence_id.unlink()
        try:
            return super(sri_printer_point, self).unlink(cr, uid, ids, context=context)
        except:
            raise osv.except_osv('Error!', u'No se puede eliminar un punto de impresión en uso. Verifique facturas,'
                                           u' usuarios, retenciones, y guías de remisión que hagan uso de dicho punto'
                                           u' de impresión')

    def copy(self, cr, uid, id, default=None, context=None):
        """
        Infiere el próximo número para usar para el printer point.
        """
        browsed_this = self.browse(cr, uid, id, context=context)
        if browsed_this.shop_id:
            #inspecciono todas las impresoras en el mismo shop_id que esta
            searched_ids = self.search(cr, uid, [('shop_id', '=', browsed_this.shop_id.id)], context=context)
            #obtengo todos los numeros de impresora utilizados, los convierto a enteros y los ordeno sin repetir
            numbers = sorted({int(browsed_each.name or '0') for browsed_each in self.browse(cr, uid, searched_ids, context=context)})
            #creo el proximo numero de impresora buscando el "hueco" en el que lo pueda meter, o bien
            #al final, si es que no se usaron los 999 puntos para la tienda
            next_print_number = 1
            for number in numbers:
                #si el numero coincide con el actual
                #    vamos al proximo numero. si llegamos a 1000 tiramos error.
                #sino, rompemos el ciclo y nos quedamos con next_print_number como el que tenemos que usar
                if next_print_number == number:
                    next_print_number += 1
                    if next_print_number == 1000:
                        raise osv.except_osv('Error!', 'No se puede copiar el punto de impresión: no se pueden crear'
                                                       ' más puntos de impresión para la misma tienda.')
                else:
                    break
            #el numero con el que nos quedamos lo convertimos a un formato "000"
            default = default or {}
            default['name'] = str(next_print_number).zfill(3)
            default['invoice_sequence_id'] = False
            default['refund_sequence_id'] = False
            default['debit_note_sequence_id'] = False
            default['withhold_sequence_id'] = False
            default['waybill_sequence_id'] = False
        return super(sri_printer_point, self).copy(cr, uid, id, default, context=context)

    _constraints = (
        (_verify_repeated_sequences,
         'Error: Al menos uno de los secuenciales está repetido o en uso dentro de otro Punto de Impresión',
         ['invoice_sequence_id', 'refund_sequence_id', 'debit_note_sequence_id', 'withhold_sequence_id', 'waybill_sequence_id']),
    )
    
sri_printer_point()
# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4: