from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HelpdeskSLA(models.Model):
    _name = 'helpdesk.sla'
    _description = 'HelpDesk SLA Policy'
    _order = 'sequence, priority desc, id'

    name = fields.Char(string='SLA Policy Name', required=True, translate=True)
    sequence = fields.Integer(string='Sequence', default=10)
    description = fields.Text(string='Policy Description')
    active = fields.Boolean(string='Active', default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        index=True,
    )

    # Matching Rules
    priority = fields.Selection([
        ('0', 'Low'),
        ('1', 'Medium'),
        ('2', 'High'),
        ('3', 'Urgent'),
    ], string='Priority Filter', help="Leave empty to apply to all priorities.")
    team_ids = fields.Many2many(
        'helpdesk.team',
        'helpdesk_sla_team_rel',
        'sla_id',
        'team_id',
        string='Applicable Teams',
        help="Leave empty to apply to all support teams.",
    )
    ticket_type = fields.Selection([
        ('question', 'Question'),
        ('incident', 'Incident'),
        ('problem', 'Problem'),
        ('service_request', 'Service Request'),
        ('bug', 'Bug Report'),
    ], string='Ticket Type Filter')
    category_id = fields.Many2one('helpdesk.category', string='Category Filter')

    # Targets
    response_time_hours = fields.Float(
        string='First Response Target (Hours)',
        required=True,
        default=2.0,
        help="Maximum hours allowed to acknowledge / respond to the ticket.",
    )
    resolution_time_hours = fields.Float(
        string='Resolution Target (Hours)',
        required=True,
        default=24.0,
        help="Maximum hours allowed to resolve the ticket.",
    )
    warning_threshold_pct = fields.Float(
        string='Warning Threshold (%)',
        default=80.0,
        help="Percentage of SLA time elapsed before status turns to 'Warning'.",
    )

    # Escalation Rules
    auto_escalate = fields.Boolean(
        string='Auto-Escalate on Breach',
        default=True,
        help="Automatically notify/escalate to the Team Leader or designated escalation manager when breached.",
    )
    escalate_user_id = fields.Many2one(
        'res.users',
        string='Escalation Contact',
        domain="[('share', '=', False)]",
        help="Optional fallback escalation contact if the ticket's team has no leader.",
    )

    # Analytics
    ticket_count = fields.Integer(string='Total Tickets', compute='_compute_sla_stats')
    breached_count = fields.Integer(string='Breached Tickets', compute='_compute_sla_stats')
    compliance_rate = fields.Float(string='Compliance Rate (%)', compute='_compute_sla_stats', digits=(16, 1))

    @api.constrains('response_time_hours', 'resolution_time_hours', 'warning_threshold_pct')
    def _check_positive_targets(self):
        for rec in self:
            if rec.response_time_hours <= 0 or rec.resolution_time_hours <= 0:
                raise ValidationError("SLA response and resolution target hours must be strictly greater than zero.")
            if rec.response_time_hours > rec.resolution_time_hours:
                raise ValidationError("First Response Target cannot exceed Resolution Target.")
            if not (10.0 <= rec.warning_threshold_pct <= 99.0):
                raise ValidationError("Warning Threshold (%) must be between 10% and 99%.")

    def _compute_sla_stats(self):
        Ticket = self.env['helpdesk.ticket']
        all_tickets = Ticket.search([('sla_id', 'in', self.ids), ('state', '!=', 'cancelled')])
        by_sla = {sid: [] for sid in self.ids}
        for t in all_tickets:
            by_sla[t.sla_id.id].append(t)

        for rec in self:
            t_list = by_sla.get(rec.id, [])
            rec.ticket_count = len(t_list)
            breached = sum(1 for t in t_list if t.sla_status == 'breached')
            rec.breached_count = breached
            rec.compliance_rate = round(((len(t_list) - breached) / len(t_list)) * 100.0, 1) if t_list else 100.0

    def matches_ticket(self, ticket):
        """Return True if this SLA policy applies to the given ticket."""
        self.ensure_one()
        if self.company_id and ticket.company_id and self.company_id != ticket.company_id:
            return False
        if self.priority and ticket.priority != self.priority:
            return False
        if self.team_ids and ticket.team_id not in self.team_ids:
            return False
        if self.ticket_type and ticket.ticket_type != self.ticket_type:
            return False
        if self.category_id and ticket.category_id != self.category_id:
            return False
        return True

    def action_view_tickets(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'{self.name} – Tickets',
            'res_model': 'helpdesk.ticket',
            'view_mode': 'kanban,list,form',
            'domain': [('sla_id', '=', self.id)],
        }
