from odoo import api, fields, models, _


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    supertcg_scanner_device_count = fields.Integer(
        string='Scanner Devices',
        compute='_compute_scanner_device_count',
    )

    @api.depends('company_id')
    def _compute_scanner_device_count(self):
        for settings in self:
            settings.supertcg_scanner_device_count = self.env['supertcg.scanner.device'].search_count([
                '|', ('company_id', '=', settings.company_id.id), ('company_id', '=', False)
            ])

    def action_open_scanner_devices(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Scanner Devices'),
            'res_model': 'supertcg.scanner.device',
            'view_mode': 'list,form',
            'target': 'current',
        }
