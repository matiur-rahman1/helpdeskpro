from odoo import api, fields, models


class HelpdeskCategory(models.Model):
    _name = 'helpdesk.category'
    _description = 'HelpDesk Ticket Category'
    _order = 'sequence, name'

    name = fields.Char(string='Category Name', required=True, translate=True)
    code = fields.Char(string='Code', help="Short identifier e.g. TECH, BILL, BUG")
    sequence = fields.Integer(string='Sequence', default=10)
    description = fields.Text(string='Description')
    default_team_id = fields.Many2one('helpdesk.team', string='Default Support Team')
    ai_keywords = fields.Char(
        string='Auto-Classification Keywords',
        help="Comma-separated keywords used by the smart auto-categorization engine "
             "(e.g. 'invoice, payment, refund, charge' for Billing)."
    )
    color = fields.Integer(string='Color Index', default=1)
    active = fields.Boolean(string='Active', default=True)
    ticket_count = fields.Integer(string='Tickets', compute='_compute_ticket_count')

    _sql_constraints = [
        ('name_uniq', 'unique (name)', 'Category name must be unique!'),
    ]

    def _compute_ticket_count(self):
        counts = {
            cat.id: cnt
            for cat, cnt in self.env['helpdesk.ticket']._read_group(
                [('category_id', 'in', self.ids)],
                ['category_id'],
                ['__count'],
            )
        }
        for rec in self:
            rec.ticket_count = counts.get(rec.id, 0)

    def action_view_tickets(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'{self.name} Tickets',
            'res_model': 'helpdesk.ticket',
            'view_mode': 'kanban,list,form',
            'domain': [('category_id', '=', self.id)],
            'context': {'default_category_id': self.id},
        }
