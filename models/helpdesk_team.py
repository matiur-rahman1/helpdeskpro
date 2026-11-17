from odoo import api, fields, models


class HelpdeskTeam(models.Model):
    _name = 'helpdesk.team'
    _description = 'HelpDesk Support Team'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, name'

    name = fields.Char(string='Team Name', required=True, tracking=True, translate=True)
    sequence = fields.Integer(string='Sequence', default=10)
    code = fields.Char(string='Team Code', help="Short prefix code e.g. T1, BILL, DEV")
    leader_id = fields.Many2one('res.users', string='Team Leader', tracking=True,
                                domain="[('share', '=', False)]")
    member_ids = fields.Many2many(
        'res.users',
        'helpdesk_team_users_rel',
        'team_id',
        'user_id',
        string='Team Members',
        domain="[('share', '=', False)]",
    )
    email = fields.Char(string='Team EmailAlias / Contact')
    description = fields.Text(string='Description')
    active = fields.Boolean(string='Active', default=True, tracking=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        index=True,
    )
    color = fields.Integer(string='Color Index', default=1)

    assignment_method = fields.Selection([
        ('manual', 'Manual Assignment'),
        ('balanced', 'Automatic – Least Active Workload'),
    ], string='Assignment Mode', default='balanced', required=True, tracking=True,
       help="Balanced automatically assigns incoming tickets to the team member with the fewest active tickets.")

    ticket_ids = fields.One2many('helpdesk.ticket', 'team_id', string='Team Tickets')

    # Performance Statistics
    ticket_count = fields.Integer(string='Total Tickets', compute='_compute_team_stats')
    open_ticket_count = fields.Integer(string='Active Tickets', compute='_compute_team_stats')
    unassigned_ticket_count = fields.Integer(string='Unassigned', compute='_compute_team_stats')
    resolved_ticket_count = fields.Integer(string='Resolved / Closed', compute='_compute_team_stats')
    overdue_ticket_count = fields.Integer(string='Overdue Tickets', compute='_compute_team_stats')
    sla_breached_count = fields.Integer(string='SLA Breached', compute='_compute_team_stats')
    avg_resolution_hours = fields.Float(string='Avg Resolution (h)', compute='_compute_team_stats', digits=(16, 1))
    sla_compliance_rate = fields.Float(string='SLA Compliance (%)', compute='_compute_team_stats', digits=(16, 1))
    csat_avg = fields.Float(string='CSAT Avg (/5)', compute='_compute_team_stats', digits=(16, 2))
    member_count = fields.Integer(string='Agents', compute='_compute_member_count')

    @api.depends('member_ids')
    def _compute_member_count(self):
        for rec in self:
            rec.member_count = len(rec.member_ids)

    def _compute_team_stats(self):
        Ticket = self.env['helpdesk.ticket']
        active_states = ('new', 'open', 'in_progress', 'pending_customer', 'pending_internal')
        done_states = ('resolved', 'closed')
        now = fields.Datetime.now()

        all_tickets = Ticket.search([('team_id', 'in', self.ids), ('state', '!=', 'cancelled')])
        by_team = {tid: [] for tid in self.ids}
        for t in all_tickets:
            by_team[t.team_id.id].append(t)

        for rec in self:
            t_list = by_team.get(rec.id, [])
            rec.ticket_count = len(t_list)
            rec.open_ticket_count = sum(1 for t in t_list if t.state in active_states)
            rec.unassigned_ticket_count = sum(1 for t in t_list if t.state in active_states and not t.user_id)
            resolved_list = [t for t in t_list if t.state in done_states]
            rec.resolved_ticket_count = len(resolved_list)
            rec.overdue_ticket_count = sum(
                1 for t in t_list
                if t.state in active_states and (
                    (t.deadline and t.deadline < now) or (t.sla_deadline and t.sla_deadline < now)
                )
            )
            sla_tickets = [t for t in t_list if t.sla_id]
            breached = [t for t in sla_tickets if t.sla_status == 'breached']
            rec.sla_breached_count = len(breached)
            if sla_tickets:
                rec.sla_compliance_rate = round(
                    ((len(sla_tickets) - len(breached)) / len(sla_tickets)) * 100.0, 1
                )
            else:
                rec.sla_compliance_rate = 100.0

            res_hours = [t.resolution_hours for t in resolved_list if t.resolution_hours > 0]
            rec.avg_resolution_hours = round(sum(res_hours) / len(res_hours), 1) if res_hours else 0.0

            csat_scores = [t.csat_score for t in t_list if t.csat_score > 0]
            rec.csat_avg = round(sum(csat_scores) / len(csat_scores), 2) if csat_scores else 0.0

    def get_least_loaded_agent(self):
        """Return the active team member with the fewest open/in-progress tickets."""
        self.ensure_one()
        candidates = self.member_ids.filtered(lambda u: u.active)
        if not candidates and self.leader_id and self.leader_id.active:
            return self.leader_id
        if not candidates:
            return self.env['res.users']

        active_states = ['new', 'open', 'in_progress', 'pending_customer', 'pending_internal']
        workload = {u.id: 0 for u in candidates}
        grouped = self.env['helpdesk.ticket'].sudo()._read_group(
            [('user_id', 'in', candidates.ids), ('state', 'in', active_states)],
            ['user_id'],
            ['__count'],
        )
        for user, count in grouped:
            if user.id in workload:
                workload[user.id] = count

        best_user_id = min(candidates.ids, key=lambda uid: (workload.get(uid, 0), uid))
        return self.env['res.users'].browse(best_user_id)

    def action_view_tickets(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'{self.name} – Tickets',
            'res_model': 'helpdesk.ticket',
            'view_mode': 'kanban,list,form,pivot,graph',
            'domain': [('team_id', '=', self.id)],
            'context': {'default_team_id': self.id},
        }

    def action_view_open_tickets(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'{self.name} – Active Tickets',
            'res_model': 'helpdesk.ticket',
            'view_mode': 'kanban,list,form',
            'domain': [
                ('team_id', '=', self.id),
                ('state', 'in', ['new', 'open', 'in_progress', 'pending_customer', 'pending_internal']),
            ],
            'context': {'default_team_id': self.id},
        }
