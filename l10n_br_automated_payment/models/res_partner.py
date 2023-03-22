# © 2018 Danimar Ribeiro, Trustcode
# Part of Trustcode. See LICENSE file for full copyright and licensing details.

import re
import iugu
import requests
import json
from odoo import api, fields, models
from odoo.exceptions import UserError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    iugu_id = fields.Char(string="ID Iugu", size=60)

    def action_synchronize_iugu(self):
        for partner in self:
            token = self.env.company.iugu_api_token

            # iugu.config(token=token)

            # iugu_customer_api = iugu.Customer()
            commercial_part = partner.commercial_partner_id
            # TODO Validar telefone e passar
            vals = {
                'email': partner.email,
                'name': commercial_part.legal_name or commercial_part.name,
                'notes': commercial_part.comment or '',
                'cpf_cnpj': re.sub('[^0-9]', '', commercial_part.cnpj_cpf or ''),
                'zip_code': re.sub('[^0-9]', '', commercial_part.zip or ''),
                'number': commercial_part.street_number,
                'street': commercial_part.street_name,
                'city': commercial_part.city_id.name,
                'state': commercial_part.state_id.code,
                'district': commercial_part.district or '',
                'complement': commercial_part.street2 or '',
            }
            if not partner.iugu_id:
                data = requests.post(
                    url=('https://api.iugu.com/v1/customers?api_token=%s' % token),
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    data=json.dumps(vals),
                )
                if not data.ok:
                    error = data.json()["error"]
                    if isinstance(error, str):
                        msg = "\n".join(
                            ["A integração com IUGU retornou os seguintes erros"] +
                            [data['errors']])

                    elif isinstance(error, dict):
                        msg = "\n".join(
                            ["A integração com IUGU retornou os seguintes erros"] +
                            ["Field: %s %s" % (x[0], x[1][0])
                             for x in error.items()])

                    raise UserError(msg)
                partner.iugu_id = data['id']
            else:
                data = requests.post(
                    url=('https://api.iugu.com/v1/customers/%s?api_token=%s' % (partner.iugu_id, token)),
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    data=json.dumps(vals),
                )
                if not data.ok:
                    error = data.json()["error"]
                    if isinstance(error, str):
                        msg = "\n".join(
                            ["A integração com IUGU retornou os seguintes erros"] +
                            [data['errors']])

                    elif isinstance(error, dict):
                        msg = "\n".join(
                            ["A integração com IUGU retornou os seguintes erros"] +
                            ["Field: %s %s" % (x[0], x[1][0])
                             for x in error.items()])

                    raise UserError(msg)
