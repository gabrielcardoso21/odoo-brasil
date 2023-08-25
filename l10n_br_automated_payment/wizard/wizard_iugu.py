# © 2020 Danimar Ribeiro, Trustcode
# Part of Trustcode. See LICENSE file for full copyright and licensing details.

import iugu
import requests
import json
from odoo import api, fields, models
from odoo.exceptions import UserError


class WizardChangeIuguInvoice(models.TransientModel):
    _name = 'wizard.change.iugu.invoice'
    _description = 'Modificar parcelamento boleto'

    payment_due = fields.Boolean(string="Pagamento Atrasado?")
    date_change = fields.Date(string='Alterar Vencimento')
    move_line_id = fields.Many2one('account.move.line', readonly=1)

    def action_change_invoice_iugu(self):
        if self.move_line_id.reconciled:
            raise UserError('O pagamento já está reconciliado')
        if self.date_change:

            token = self.env.company.iugu_api_token
            # iugu.config(token=token)
            # iugu_invoice_api = iugu.Invoice()

            vals = {
                'due_date': self.date_change.strftime('%Y-%m-%d'),
                'email': self.move_line_id.move_id.partner_id.email,
            }
            data = requests.post(
                url=('https://api.iugu.com/v1/invoices/%s/duplicate?api_token=%s' % (self.move_line_id.iugu_id, token)),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                data=json.dumps(vals),
            )
            if not data.ok:
                msg = "\n".join(
                    ["A geração de segunda via no IUGU retornou os seguintes erros"] +
                    ["%s" % data.json()['errors']])
                raise UserError(msg)
            data = data.json()
            self.move_line_id.write({
                'date_maturity': self.date_change,
                'iugu_id': data['id'],
                'iugu_secure_payment_url': data['secure_url'],
                'iugu_digitable_line': data['bank_slip']['digitable_line'],
                'iugu_barcode_url': data['bank_slip']['barcode'],
            })
            self.env['payment.transaction'].search([('origin_move_line_id', '=', self.move_line_id.id)]).write({
                'transaction_url': data['secure_url'],
                'date_maturity': self.date_change,
            })
