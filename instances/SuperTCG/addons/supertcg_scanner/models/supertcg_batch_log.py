from odoo import api, fields, models


# HARDCODE-ISSUE-5: _rec_name defaults to 'name' but this model has no name field.
class SuperTCGBatchLog(models.Model):
    _name = 'supertcg.batch.log'
    _description = 'SuperTCG Batch Processing Log'
    _order = 'create_date desc, id desc'
    _rec_name = 'message'

    batch_id = fields.Many2one(
        'supertcg.batch',
        string='Batch',
        required=True,
        ondelete='cascade',
        index=True,
    )
    level = fields.Selection(
        selection=[
            ('info', 'Info'),
            ('warning', 'Warning'),
            ('error', 'Error'),
            ('success', 'Success'),
        ],
        string='Level',
        default='info',
        required=True,
    )
    stage = fields.Char(
        string='Stage',
        help='e.g., printer_lookup, zpl_generation, iot_send',
    )
    message = fields.Text(
        string='Message',
        required=True,
    )
    create_date = fields.Datetime(
        string='Timestamp',
    )
