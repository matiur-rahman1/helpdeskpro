from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    helpdesk_ticket_ids = fields.One2many('helpdesk.ticket', 'partner_id', string='HelpDesk Tickets')
    helpdesk_ticket_count = fields.Integer(string='Total Tickets', compute='_compute_helpdesk_ticket_stats')
    helpdesk_open_ticket_count = fields.Integer(string='Open Tickets', compute='_compute_helpdesk_ticket_stats')
    helpdesk_resolved_ticket_count = fields.Integer(string='Resolved Tickets', compute='_compute_helpdesk_ticket_stats')

    def _compute_helpdesk_ticket_stats(self):
        Ticket = self.env['helpdesk.ticket']
        active_states = ('new', 'open', 'in_progress', 'pending_customer', 'pending_internal')
        done_states = ('resolved', 'closed')

        all_tickets = Ticket.search([('partner_id', 'in', self.ids), ('state', '!=', 'cancelled')])
        by_partner = {pid: [] for pid in self.ids}
        for t in all_tickets:
            by_partner[t.partner_id.id].append(t)

        for partner in self:
            t_list = by_partner.get(partner.id, [])
            partner.helpdesk_ticket_count = len(t_list)
            partner.helpdesk_open_ticket_count = sum(1 for t in t_list if t.state in active_states)
            partner.helpdesk_resolved_ticket_count = sum(1 for t in t_list if t.state in done_states)

    def action_view_helpdesk_tickets(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Support Tickets – {self.name}',
            'res_model': 'helpdesk.ticket',
            'view_mode': 'kanban,list,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {
                'default_partner_id': self.id,
                'default_customer_email': self.email,
                'default_customer_phone': self.phone,
            },
        }
