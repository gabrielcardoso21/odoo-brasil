import logging
import requests
from odoo import models

_logger = logging.getLogger(__name__)

try:
    import iugu
except ImportError:
    _logger.exception("Não é possível importar iugu")


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def action_cancel(self):
        res = super(SaleOrder, self).action_cancel()
        for order in self:
            for transaction_id in order.transaction_ids:
                if (
                    transaction_id
                    and transaction_id.acquirer_id.provider == "iugu"
                ):
                    # iugu.config(token=transaction_id.acquirer_id.iugu_api_key)
                    # invoice_api = iugu.Invoice()
                    # invoice_api.cancel(transaction_id.acquirer_reference)
                    requests.put(
                        url=('https://api.iugu.com/v1/invoices/%s/cancel?api_token=%s'
                              % (transaction_id.acquirer_reference,
                                 transaction_id.acquirer_id.iugu_api_key)),
                        headers={
                            "Accept": "application/json",
                        },
                    )

        return res
