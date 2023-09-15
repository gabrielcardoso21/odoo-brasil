# © 2019 Danimar Ribeiro
# Part of OdooNext. See LICENSE file for full copyright and licensing details.

import re
import iugu
import requests
import json
from datetime import date
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo import api, SUPERUSER_ID, _
from odoo import registry as registry_get


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _get_default_policy(self):
        if self.env.context.get('default_type', '') == 'out_invoice':
            return 'directly'
        if self.env.context.get('default_type', '') == 'in_invoice':
            return 'manually'

    l10n_br_edoc_policy = fields.Selection(
        selection=[('directly', 'Emitir agora'),
         ('after_payment', 'Emitir após pagamento'),
         ('manually', 'Manualmente')], string="Nota Eletrônica", default=_get_default_policy)

    @api.depends('line_ids')
    def _compute_receivables(self):
        for move in self:
            move.receivable_move_line_ids = move.line_ids.filtered(
                lambda m: m.account_id.user_type_id.type == 'receivable'
            ).sorted(key=lambda m: m.date_maturity)

    @api.depends('line_ids')
    def _compute_payables(self):
        for move in self:
            move.payable_move_line_ids = move.line_ids.filtered(
                lambda m: m.account_id.user_type_id.type == 'payable')

    receivable_move_line_ids = fields.Many2many(
        'account.move.line', string='Receivable Move Lines',
        compute='_compute_receivables')

    payable_move_line_ids = fields.Many2many(
        'account.move.line', string='Payable Move Lines',
        compute='_compute_payables')

    payment_journal_id = fields.Many2one(
        'account.journal', string='Meio de pagamento')

    def validate_data_iugu(self):
        errors = []
        for invoice in self:
            if not invoice.payment_journal_id.receive_by_iugu:
                continue
            partner = invoice.partner_id.commercial_partner_id
            if not self.env.company.iugu_api_token:
                errors.append('Configure o token de API')
            if partner.is_company and not partner.legal_name:
                errors.append('Destinatário - Razão Social')
            if not partner.street:
                errors.append('Destinatário / Endereço - Rua')
            if not partner.street_number:
                errors.append('Destinatário / Endereço - Número')
            if not partner.zip or len(re.sub(r"\D", "", partner.zip)) != 8:
                errors.append('Destinatário / Endereço - CEP')
            if not partner.state_id:
                errors.append(u'Destinatário / Endereço - Estado')
            if not partner.city_id and not partner.city:
                errors.append(u'Destinatário / Endereço - Município')
            if not partner.country_id:
                errors.append(u'Destinatário / Endereço - País')
        if len(errors) > 0:
            msg = "\n".join(
                ["Por favor corrija os erros antes de prosseguir"] + errors)
            raise ValidationError(msg)

    def send_information_to_iugu(self):
        if not self.payment_journal_id.receive_by_iugu:
            return

        base_url = (
            self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        )
        token = self.env.company.iugu_api_token
        # iugu.config(token=token)
        # iugu_invoice_api = iugu.Invoice()

        for moveline in self.financial_move_line_ids:
            self.partner_id.action_synchronize_iugu()

            iugu_p = self.env['payment.acquirer'].search([('provider', '=', 'iugu')])
            transaction = self.env['payment.transaction'].create({
                'acquirer_id': iugu_p.id,
                'amount': moveline.amount_residual,
                'currency_id': moveline.move_id.currency_id.id,
                'partner_id': moveline.partner_id.id,
                'type': 'server2server',
                'date_maturity': moveline.date_maturity,
                'origin_move_line_id': moveline.id,
                'invoice_ids': [(6, 0, self.ids)]
            })

            vals = {
                'email': self.partner_id.email,
                'due_date': moveline.date_maturity.strftime('%Y-%m-%d'),
                'ensure_workday_due_date': True,
                'items': [{
                    'description': 'Fatura Ref: %s' % moveline.name,
                    'quantity': 1,
                    'price_cents': int(moveline.amount_residual * 100),
                }],
                'return_url': '%s/my/invoices/%s' % (base_url, self.id),
                'notification_url': '%s/iugu/webhook?id=%s' % (base_url, self.id),
                'fines': True,
                'late_payment_fine': 2,
                'per_day_interest': True,
                'customer_id': self.partner_id.iugu_id,
                'early_payment_discount': False,
                'order_id': transaction.reference,
            }
            # data = iugu_invoice_api.create(vals)
            data = requests.post(
                url=('https://api.iugu.com/v1/invoices?api_token=%s' % token),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                data=json.dumps(vals),
            )
            if not data.ok:
                jump = False
                error = data.json()["errors"]
                if isinstance(error, str):
                    if 'invoice_id' in error:
                        vals['order_id'] += '-1'
                        data = requests.post(
                            url=('https://api.iugu.com/v1/invoices?api_token=%s' % token),
                            headers={
                                "Content-Type": "application/json",
                                "Accept": "application/json",
                            },
                            data=json.dumps(vals),
                        )
                        jump = True
                    else:
                        raise UserError('Erro na criação de invoice no IUGU:\n%s' % error)

                if not jump:
                    msg = "\n".join(
                        ["A criação de invoice no IUGU retornou os seguintes erros"] +
                        ["Field: %s %s" % (x[0], x[1][0])
                            for x in error.items()])
                    raise UserError(msg)

            transaction.write({
                'acquirer_reference': data.json()['id'],
                'transaction_url': data.json()['secure_url'],
            })
            moveline.write({
                'iugu_id': data.json()['id'],
                'iugu_secure_payment_url': data.json()['secure_url'],
                'iugu_digitable_line': data.json()['bank_slip']['digitable_line'],
                'iugu_barcode_url': data.json()['bank_slip']['barcode'],
            })

    def generate_payment_transactions(self):
        for item in self:
            item.send_information_to_iugu()

    def action_post(self):
        self.validate_data_iugu()
        result = super(AccountMove, self).action_post()
        self.generate_payment_transactions()
        return result


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    iugu_status = fields.Char(string="Status Iugu", default='pending', copy=False)
    iugu_id = fields.Char(string="ID Iugu", size=60, copy=False)
    iugu_secure_payment_url = fields.Char(string="URL de Pagamento", size=500, copy=False)
    iugu_digitable_line = fields.Char(string="Linha Digitável", size=100, copy=False)
    iugu_barcode_url = fields.Char(string="Código de barras", size=100, copy=False)

    def _create_bank_tax_move(self, fees_amount):
        bank_taxes = fees_amount or 0

        ref = 'Taxa: %s' % self.name
        journal = self.move_id.payment_journal_id
        currency = journal.currency_id or journal.company_id.currency_id

        move = self.env['account.move'].create({
            'name': '/',
            'journal_id': journal.id,
            'company_id': journal.company_id.id,
            'date': date.today(),
            'ref': ref,
            'currency_id': currency.id,
            'move_type': 'entry',
        })
        aml_obj = self.env['account.move.line'].with_context(
            check_move_validity=False)
        credit_aml_dict = {
            'name': ref,
            'move_id': move.id,
            'partner_id': self.partner_id.id,
            'debit': 0.0,
            'credit': bank_taxes,
            'account_id': journal.payment_debit_account_id.id,
        }
        debit_aml_dict = {
            'name': ref,
            'move_id': move.id,
            'partner_id': self.partner_id.id,
            'debit': bank_taxes,
            'credit': 0.0,
            'account_id': journal.company_id.l10n_br_bankfee_account_id.id,
        }
        aml_obj.create(credit_aml_dict)
        aml_obj.create(debit_aml_dict)
        move.post()
        return move

    def action_mark_paid_iugu(self, iugu_data):
        self.ensure_one()
        ref = 'Fatura Ref: %s' % self.name

        journal = self.move_id.payment_journal_id
        currency = journal.currency_id or journal.company_id.currency_id

        payment = self.env['account.payment'].sudo().create({
            'bank_reference': self.iugu_id,
            'communication': ref,
            'journal_id': journal.id,
            'company_id': journal.company_id.id,
            'currency_id': currency.id,
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'amount': self.amount_residual,
            'payment_date': date.today(),
            'payment_method_id': journal.inbound_payment_method_ids[0].id,
            'invoice_ids': [(4, self.move_id.id, None)]
        })
        payment.post()

        self._create_bank_tax_move(iugu_data)

    def action_notify_due_payment(self):
        if self.invoice_id:
            self.invoice_id.message_post(
                body='Notificação do IUGU: Fatura atrasada')

    def action_verify_iugu_payment(self):
        if self.iugu_id:
            token = self.env.company.iugu_api_token
            # iugu.config(token=token)
            # iugu_invoice_api = iugu.Invoice()

            # data = iugu_invoice_api.search(self.iugu_id)
            data = requests.post(
                url=('https://api.iugu.com/v1/invoices/%s?api_token=%s' % (self.iugu_id, token)),
                headers={
                    "Accept": "application/json",
                },
            )
            if not data.ok:
                raise UserError("A busca de invoice no IUGU retornou os seguintes erros\n%s" % data.json()["errors"])
            if data.json().get('status', '') == 'paid' and not self.reconciled:
                self.iugu_status = data.json()['status']
                self.action_mark_paid_iugu(data.json())
            else:
                self.iugu_status = data.json()['status']
        else:
            raise UserError('Esta parcela não foi enviada ao IUGU')

    def open_wizard_change_date(self):
        return({
            'name': 'Alterar data de vencimento',
            'type': 'ir.actions.act_window',
            'res_model': 'wizard.change.iugu.invoice',
            'view_type': 'form',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_move_line_id': self.id,
            }
        })
