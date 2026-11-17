import re
from datetime import datetime, time, timedelta
import pytz

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


TICKET_STATES = [
    ('new', 'New'),
    ('open', 'Open'),
    ('in_progress', 'In Progress'),
    ('pending_customer', 'Pending Customer'),
    ('pending_internal', 'Pending Internal'),
    ('resolved', 'Resolved'),
    ('closed', 'Closed'),
    ('cancelled', 'Cancelled'),
]

PRIORITY_SELECTION = [
    ('0', 'Low'),
    ('1', 'Medium'),
    ('2', 'High'),
    ('3', 'Urgent'),
]

TICKET_TYPE_SELECTION = [
    ('question', 'Question'),
    ('incident', 'Incident'),
    ('problem', 'Problem'),
    ('service_request', 'Service Request'),
    ('bug', 'Bug Report'),
]

SOURCE_SELECTION = [
    ('email', 'Email'),
    ('portal', 'Customer Portal'),
    ('phone', 'Phone'),
    ('web', 'Website'),
    ('internal', 'Internal'),
    ('api', 'API'),
]

ALLOWED_TRANSITIONS = {
    'new': {'open', 'in_progress', 'pending_customer', 'pending_internal', 'resolved', 'cancelled'},
    'open': {'in_progress', 'pending_customer', 'pending_internal', 'resolved', 'cancelled'},
    'in_progress': {'open', 'pending_customer', 'pending_internal', 'resolved', 'cancelled'},
    'pending_customer': {'open', 'in_progress', 'pending_internal', 'resolved', 'cancelled'},
    'pending_internal': {'open', 'in_progress', 'pending_customer', 'resolved', 'cancelled'},
    'resolved': {'open', 'in_progress', 'closed'},
    'closed': {'open', 'in_progress'},
    'cancelled': {'open'},
}


class HelpdeskTicket(models.Model):
    _name = 'helpdesk.ticket'
    _description = 'HelpDesk Support Ticket'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _order = 'priority desc, is_overdue desc, id desc'
    _rec_name = 'name'
    _rec_names_search = ['name', 'subject', 'customer_email']

    # ------------------------------------------------------------------
    # Core Identification & Content
    # ------------------------------------------------------------------
    name = fields.Char(
        string='Ticket Number',
        readonly=True,
        copy=False,
        default=lambda self: _('New'),
        index=True,
    )
    subject = fields.Char(string='Subject', required=True, tracking=True, index=True)
    description = fields.Html(string='Description', sanitize_style=True)

    # ------------------------------------------------------------------
    # Customer Details
    # ------------------------------------------------------------------
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        tracking=True,
        index=True,
    )
    customer_email = fields.Char(
        string='Customer Email',
        compute='_compute_customer_contact',
        store=True,
        readonly=False,
        tracking=True,
    )
    customer_phone = fields.Char(
        string='Customer Phone',
        compute='_compute_customer_contact',
        store=True,
        readonly=False,
    )
    partner_ticket_count = fields.Integer(
        string='Customer Total Tickets',
        related='partner_id.helpdesk_ticket_count',
    )

    # ------------------------------------------------------------------
    # Assignment & Categorization
    # ------------------------------------------------------------------
    team_id = fields.Many2one(
        'helpdesk.team',
        string='Assigned Team',
        tracking=True,
        index=True,
    )
    team_member_ids = fields.Many2many(
        'res.users',
        related='team_id.member_ids',
        string='Available Team Members',
    )
    user_id = fields.Many2one(
        'res.users',
        string='Assigned Agent',
        tracking=True,
        index=True,
        domain="[('share', '=', False)]",
    )
    priority = fields.Selection(
        PRIORITY_SELECTION,
        string='Priority',
        default='1',
        required=True,
        tracking=True,
        index=True,
    )
    ticket_type = fields.Selection(
        TICKET_TYPE_SELECTION,
        string='Ticket Type',
        default='question',
        required=True,
        tracking=True,
    )
    category_id = fields.Many2one(
        'helpdesk.category',
        string='Category',
        tracking=True,
        index=True,
    )
    tag_ids = fields.Many2many(
        'helpdesk.tag',
        'helpdesk_ticket_tag_rel',
        'ticket_id',
        'tag_id',
        string='Tags',
    )
    source = fields.Selection(
        SOURCE_SELECTION,
        string='Source',
        default='internal',
        required=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
        index=True,
    )

    # ------------------------------------------------------------------
    # Workflow & Dates
    # ------------------------------------------------------------------
    state = fields.Selection(
        TICKET_STATES,
        string='Status',
        default='new',
        required=True,
        tracking=True,
        index=True,
        group_expand='_group_expand_state',
    )
    kanban_state = fields.Selection([
        ('normal', 'In Progress'),
        ('done', 'Ready for Next Stage'),
        ('blocked', 'Blocked'),
    ], string='Kanban State', default='normal', tracking=True)
    color = fields.Integer(string='Color Index')

    deadline = fields.Datetime(string='Target Deadline', tracking=True)
    first_response_date = fields.Datetime(string='First Response Date', readonly=True, copy=False)
    resolution_date = fields.Datetime(string='Resolution Date', readonly=True, copy=False, tracking=True)
    closing_date = fields.Datetime(string='Closing Date', readonly=True, copy=False, tracking=True)
    reopen_count = fields.Integer(string='Reopen Count', default=0, readonly=True, copy=False)

    response_hours = fields.Float(
        string='Response Time (Hours)',
        compute='_compute_durations',
        store=True,
        digits=(16, 2),
    )
    resolution_hours = fields.Float(
        string='Resolution Time (Hours)',
        compute='_compute_durations',
        store=True,
        digits=(16, 2),
    )

    # ------------------------------------------------------------------
    # SLA Management
    # ------------------------------------------------------------------
    sla_id = fields.Many2one(
        'helpdesk.sla',
        string='SLA Policy',
        tracking=True,
        copy=False,
    )
    sla_response_deadline = fields.Datetime(
        string='SLA Response Deadline',
        compute='_compute_sla_deadlines',
        store=True,
        readonly=False,
        copy=False,
    )
    sla_deadline = fields.Datetime(
        string='SLA Resolution Deadline',
        compute='_compute_sla_deadlines',
        store=True,
        readonly=False,
        copy=False,
    )
    sla_response_status = fields.Selection([
        ('na', 'No SLA'),
        ('on_track', 'On Track'),
        ('warning', 'Warning'),
        ('breached', 'Breached'),
        ('completed', 'Met'),
    ], string='Response SLA Status', compute='_compute_sla_statuses', store=True)
    sla_status = fields.Selection([
        ('na', 'No SLA'),
        ('on_track', 'On Track'),
        ('warning', 'Warning'),
        ('breached', 'Breached'),
        ('completed', 'Completed'),
    ], string='Resolution SLA Status', compute='_compute_sla_statuses', store=True, index=True)

    is_overdue = fields.Boolean(
        string='Is Overdue',
        compute='_compute_sla_statuses',
        store=True,
        index=True,
    )
    is_escalated = fields.Boolean(string='Escalated', default=False, copy=False, tracking=True)
    reminder_sent = fields.Boolean(string='Overdue Reminder Sent', default=False, copy=False)

    # ------------------------------------------------------------------
    # Notes, Resolution & Attachments
    # ------------------------------------------------------------------
    internal_notes = fields.Text(
        string='Internal Notes',
        groups='helpdeskpro.group_helpdesk_user',
        help="Private notes visible only to internal support staff. Never exposed on the portal.",
    )
    resolution_summary = fields.Text(string='Resolution Summary', tracking=True)
    attachment_ids = fields.One2many(
        'ir.attachment',
        'res_id',
        domain=[('res_model', '=', 'helpdesk.ticket')],
        string='Attachments',
    )
    attachment_count = fields.Integer(string='Attachments Count', compute='_compute_attachment_count')

    # ------------------------------------------------------------------
    # Duplicate Detection & Ticket Merge
    # ------------------------------------------------------------------
    duplicate_ticket_ids = fields.Many2many(
        'helpdesk.ticket',
        compute='_compute_duplicate_tickets',
        string='Potential Duplicate Tickets',
    )
    duplicate_count = fields.Integer(
        string='Duplicates',
        compute='_compute_duplicate_tickets',
    )
    merged_into_id = fields.Many2one(
        'helpdesk.ticket',
        string='Merged Into Ticket',
        readonly=True,
        copy=False,
    )

    # ------------------------------------------------------------------
    # Customer Satisfaction (CSAT)
    # ------------------------------------------------------------------
    csat_rating = fields.Selection([
        ('1', '1 - Very Dissatisfied'),
        ('2', '2 - Dissatisfied'),
        ('3', '3 - Neutral'),
        ('4', '4 - Satisfied'),
        ('5', '5 - Very Satisfied'),
    ], string='Customer Rating', tracking=True, copy=False)
    csat_score = fields.Integer(
        string='CSAT Score',
        compute='_compute_csat_score',
        store=True,
        aggregator='avg',
    )
    csat_comment = fields.Text(string='Customer Feedback', copy=False)
    csat_date = fields.Datetime(string='Rated On', readonly=True, copy=False)

    # ------------------------------------------------------------------
    # Group expand
    # ------------------------------------------------------------------
    def _group_expand_state(self, states, domain, order=None):
        return [key for key, _val in TICKET_STATES]

    # ------------------------------------------------------------------
    # Portal URL
    # ------------------------------------------------------------------
    def _compute_access_url(self):
        super()._compute_access_url()
        for ticket in self:
            ticket.access_url = f'/my/tickets/{ticket.id}'

    # ------------------------------------------------------------------
    # Computed Fields (Strictly separated stored vs non-stored)
    # ------------------------------------------------------------------
    @api.depends('partner_id', 'partner_id.email', 'partner_id.phone')
    def _compute_customer_contact(self):
        for rec in self:
            if rec.partner_id:
                if not rec.customer_email or rec.partner_id.email:
                    rec.customer_email = rec.partner_id.email or rec.customer_email
                if not rec.customer_phone or rec.partner_id.phone:
                    rec.customer_phone = rec.partner_id.phone or rec.customer_phone

    @api.depends('create_date', 'first_response_date', 'resolution_date')
    def _compute_durations(self):
        for rec in self:
            base_dt = rec.create_date or fields.Datetime.now()
            if rec.first_response_date and base_dt:
                diff_resp = (rec.first_response_date - base_dt).total_seconds() / 3600.0
                rec.response_hours = round(max(diff_resp, 0.0), 2)
            else:
                rec.response_hours = 0.0

            if rec.resolution_date and base_dt:
                diff_res = (rec.resolution_date - base_dt).total_seconds() / 3600.0
                rec.resolution_hours = round(max(diff_res, 0.0), 2)
            else:
                rec.resolution_hours = 0.0

    @api.depends('sla_id', 'create_date')
    def _compute_sla_deadlines(self):
        for rec in self:
            if rec.sla_id:
                start_dt = rec.create_date or fields.Datetime.now()
                rec.sla_response_deadline = start_dt + timedelta(hours=rec.sla_id.response_time_hours)
                rec.sla_deadline = start_dt + timedelta(hours=rec.sla_id.resolution_time_hours)
            else:
                rec.sla_response_deadline = False
                rec.sla_deadline = False

    @api.depends(
        'sla_id',
        'sla_response_deadline',
        'sla_deadline',
        'deadline',
        'first_response_date',
        'resolution_date',
        'state',
    )
    def _compute_sla_statuses(self):
        now = fields.Datetime.now()
        done_states = ('resolved', 'closed')
        inactive_states = ('resolved', 'closed', 'cancelled')

        for rec in self:
            # 1. Overdue computation
            if rec.state in inactive_states:
                rec.is_overdue = False
            else:
                overdue_manual = bool(rec.deadline and rec.deadline < now)
                overdue_sla = bool(rec.sla_deadline and rec.sla_deadline < now)
                rec.is_overdue = overdue_manual or overdue_sla

            if not rec.sla_id:
                rec.sla_response_status = 'na'
                rec.sla_status = 'na'
                continue

            start_dt = rec.create_date or now
            warn_ratio = (rec.sla_id.warning_threshold_pct or 80.0) / 100.0

            # 2. First Response SLA Status
            if rec.sla_response_deadline:
                check_resp_dt = rec.first_response_date or now
                if rec.first_response_date:
                    rec.sla_response_status = (
                        'completed' if rec.first_response_date <= rec.sla_response_deadline else 'breached'
                    )
                elif rec.state == 'cancelled':
                    rec.sla_response_status = 'na'
                elif check_resp_dt > rec.sla_response_deadline:
                    rec.sla_response_status = 'breached'
                else:
                    total_sec = max((rec.sla_response_deadline - start_dt).total_seconds(), 1.0)
                    elapsed_sec = max((now - start_dt).total_seconds(), 0.0)
                    rec.sla_response_status = 'warning' if (elapsed_sec / total_sec) >= warn_ratio else 'on_track'
            else:
                rec.sla_response_status = 'na'

            # 3. Resolution SLA Status
            if rec.sla_deadline:
                if rec.state == 'cancelled':
                    rec.sla_status = 'na'
                elif rec.state in done_states:
                    end_dt = rec.resolution_date or rec.closing_date or now
                    rec.sla_status = 'completed' if end_dt <= rec.sla_deadline else 'breached'
                elif now > rec.sla_deadline:
                    rec.sla_status = 'breached'
                else:
                    total_sec = max((rec.sla_deadline - start_dt).total_seconds(), 1.0)
                    elapsed_sec = max((now - start_dt).total_seconds(), 0.0)
                    rec.sla_status = 'warning' if (elapsed_sec / total_sec) >= warn_ratio else 'on_track'
            else:
                rec.sla_status = 'na'

    @api.depends('csat_rating')
    def _compute_csat_score(self):
        for rec in self:
            rec.csat_score = int(rec.csat_rating) if rec.csat_rating else 0

    def _compute_attachment_count(self):
        Attachment = self.env['ir.attachment'].sudo()
        counts = {
            res_id: cnt
            for res_id, cnt in Attachment._read_group(
                [('res_model', '=', 'helpdesk.ticket'), ('res_id', 'in', self.ids)],
                ['res_id'],
                ['__count'],
            )
        }
        for rec in self:
            rec.attachment_count = counts.get(rec.id, 0)

    @api.depends('partner_id', 'customer_email', 'subject')
    def _compute_duplicate_tickets(self):
        for rec in self:
            if not rec.subject or not (rec.partner_id or rec.customer_email):
                rec.duplicate_ticket_ids = self.env['helpdesk.ticket']
                rec.duplicate_count = 0
                continue

            words = [w for w in re.findall(r'\w+', rec.subject.lower()) if len(w) >= 4]
            domain = [
                ('id', '!=', rec._origin.id or 0),
                ('state', '!=', 'cancelled'),
            ]
            if rec.partner_id:
                domain.append(('partner_id', '=', rec.partner_id.id))
            elif rec.customer_email:
                domain.append(('customer_email', '=ilike', rec.customer_email))

            candidates = self.env['helpdesk.ticket'].search(domain, limit=20)
            if words:
                matches = candidates.filtered(
                    lambda c: any(w in (c.subject or '').lower() for w in words)
                )
            else:
                matches = candidates.filtered(
                    lambda c: (c.subject or '').strip().lower() == rec.subject.strip().lower()
                )
            rec.duplicate_ticket_ids = matches
            rec.duplicate_count = len(matches)

    # ------------------------------------------------------------------
    # Onchanges & Smart Defaults
    # ------------------------------------------------------------------
    @api.onchange('category_id')
    def _onchange_category_id(self):
        if self.category_id and self.category_id.default_team_id and not self.team_id:
            self.team_id = self.category_id.default_team_id

    @api.onchange('team_id')
    def _onchange_team_id(self):
        if self.team_id and self.user_id and self.team_id.member_ids:
            if self.user_id not in self.team_id.member_ids and self.user_id != self.team_id.leader_id:
                self.user_id = False

    # ------------------------------------------------------------------
    # SLA & Auto-Categorization Helpers
    # ------------------------------------------------------------------
    def _find_matching_sla(self):
        """Return the most specific highest-priority active SLA policy matching this ticket."""
        self.ensure_one()
        policies = self.env['helpdesk.sla'].search([
            ('active', '=', True),
            '|', ('company_id', '=', False), ('company_id', '=', self.company_id.id),
        ], order='sequence asc, priority desc, id asc')
        matched = [p for p in policies if p.matches_ticket(self)]
        if not matched:
            return self.env['helpdesk.sla']

        def _specificity(pol):
            score = 0
            if pol.team_ids:
                score += 4
            if pol.category_id:
                score += 2
            if pol.ticket_type:
                score += 2
            if pol.priority:
                score += 1
            return (pol.sequence, -score, pol.id)

        matched.sort(key=_specificity)
        return matched[0]

    def _auto_categorize_vals(self, vals):
        """Smart keyword / rule-based categorization if category is not provided."""
        if vals.get('category_id'):
            return
        text = f"{vals.get('subject') or ''} {vals.get('description') or ''}".lower()
        if not text.strip():
            return
        categories = self.env['helpdesk.category'].sudo().search([('active', '=', True)])
        best_cat = None
        best_score = 0
        for cat in categories:
            if not cat.ai_keywords:
                continue
            keywords = [k.strip().lower() for k in cat.ai_keywords.split(',') if k.strip()]
            score = sum(1 for kw in keywords if kw in text)
            if score > best_score:
                best_score = score
                best_cat = cat
        if best_cat:
            vals['category_id'] = best_cat.id
            if not vals.get('team_id') and best_cat.default_team_id:
                vals['team_id'] = best_cat.default_team_id.id

    # ------------------------------------------------------------------
    # ORM Overrides (create / write)
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('helpdesk.ticket') or _('New')

            # Smart auto-categorization when category is omitted
            self._auto_categorize_vals(vals)

            # Default team from category if not set
            if not vals.get('team_id') and vals.get('category_id'):
                cat = self.env['helpdesk.category'].browse(vals['category_id'])
                if cat.default_team_id:
                    vals['team_id'] = cat.default_team_id.id

            # Automatic balanced agent assignment if team uses 'balanced' mode and no agent specified
            if vals.get('team_id') and not vals.get('user_id'):
                team = self.env['helpdesk.team'].browse(vals['team_id'])
                if team.assignment_method == 'balanced':
                    agent = team.get_least_loaded_agent()
                    if agent:
                        vals['user_id'] = agent.id
                        if vals.get('state', 'new') == 'new':
                            vals['state'] = 'open'

        records = super().create(vals_list)

        for rec in records:
            # Apply matching SLA policy if not explicitly set
            if not rec.sla_id:
                matched_sla = rec._find_matching_sla()
                if matched_sla:
                    rec.sla_id = matched_sla.id

            # Subscribe customer & assigned agent
            partners_to_subscribe = []
            if rec.partner_id:
                partners_to_subscribe.append(rec.partner_id.id)
            if rec.user_id and rec.user_id.partner_id:
                partners_to_subscribe.append(rec.user_id.partner_id.id)
            if partners_to_subscribe:
                rec.message_subscribe(partner_ids=list(set(partners_to_subscribe)))

            # Send creation notification email template if customer email is present
            if rec.customer_email and not self.env.context.get('skip_helpdesk_mail'):
                rec._send_ticket_mail('helpdeskpro.mail_template_ticket_created')
            if rec.user_id and not self.env.context.get('skip_helpdesk_mail'):
                rec._send_ticket_mail('helpdeskpro.mail_template_ticket_assigned')

        return records

    def write(self, vals):
        # Validate state transitions and record timestamps
        if 'state' in vals:
            target_state = vals['state']
            now = fields.Datetime.now()
            for rec in self:
                if rec.state == target_state:
                    continue
                allowed = ALLOWED_TRANSITIONS.get(rec.state, set())
                if target_state not in allowed and not self.env.context.get('force_ticket_state'):
                    state_labels = dict(TICKET_STATES)
                    raise ValidationError(_(
                        "Invalid status transition for ticket %(ticket)s: cannot move directly from '%(from_s)s' to '%(to_s)s'.",
                        ticket=rec.name,
                        from_s=state_labels.get(rec.state, rec.state),
                        to_s=state_labels.get(target_state, target_state),
                    ))

        # Track per-record timestamp updates on state or agent change
        now = fields.Datetime.now()
        old_states = {rec.id: rec.state for rec in self}
        old_users = {rec.id: rec.user_id.id for rec in self}

        res = super().write(vals)

        for rec in self:
            prev_state = old_states.get(rec.id)
            prev_user = old_users.get(rec.id)
            updates = {}

            if 'state' in vals and rec.state != prev_state:
                if rec.state in ('open', 'in_progress', 'resolved') and not rec.first_response_date:
                    updates['first_response_date'] = now
                if rec.state == 'resolved' and not rec.resolution_date:
                    updates['resolution_date'] = now
                if rec.state == 'closed' and not rec.closing_date:
                    updates['closing_date'] = now
                    if not rec.resolution_date:
                        updates['resolution_date'] = now
                if prev_state in ('resolved', 'closed') and rec.state in ('open', 'in_progress'):
                    updates['reopen_count'] = rec.reopen_count + 1
                    updates['resolution_date'] = False
                    updates['closing_date'] = False

            # Re-evaluate SLA if priority or team changed while still active
            if ('priority' in vals or 'team_id' in vals) and rec.state in ('new', 'open', 'in_progress'):
                matched_sla = rec._find_matching_sla()
                if matched_sla and matched_sla != rec.sla_id:
                    updates['sla_id'] = matched_sla.id

            if updates:
                super(HelpdeskTicket, rec).write(updates)

            # Subscribe newly assigned agent & notify
            if 'user_id' in vals and rec.user_id and rec.user_id.id != prev_user:
                if rec.user_id.partner_id:
                    rec.message_subscribe(partner_ids=[rec.user_id.partner_id.id])
                if not self.env.context.get('skip_helpdesk_mail'):
                    rec._send_ticket_mail('helpdeskpro.mail_template_ticket_assigned')

            # Notify customer on resolution
            if 'state' in vals and rec.state == 'resolved' and prev_state != 'resolved':
                if not self.env.context.get('skip_helpdesk_mail'):
                    rec._send_ticket_mail('helpdeskpro.mail_template_ticket_resolved')

        return res

    def _send_ticket_mail(self, template_xmlid):
        """Safely render and queue email from template without failing transaction if mail server is unconfigured."""
        self.ensure_one()
        template = self.env.ref(template_xmlid, raise_if_not_found=False)
        if template:
            try:
                template.sudo().send_mail(self.id, force_send=False)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Workflow Action Methods
    # ------------------------------------------------------------------
    def action_assign_to_me(self):
        for rec in self:
            vals = {'user_id': self.env.user.id}
            if rec.state == 'new':
                vals['state'] = 'open'
            rec.write(vals)

    def action_auto_assign(self):
        for rec in self:
            if not rec.team_id:
                raise UserError(_("Please select an Assigned Team before auto-assigning."))
            agent = rec.team_id.get_least_loaded_agent()
            if not agent:
                raise UserError(_("No active agents found in team '%s'.", rec.team_id.name))
            vals = {'user_id': agent.id}
            if rec.state == 'new':
                vals['state'] = 'open'
            rec.write(vals)

    def action_ai_categorize(self):
        """Run smart rule-based / optional AI categorization on the ticket."""
        for rec in self:
            vals = {
                'subject': rec.subject,
                'description': rec.description,
            }
            rec._auto_categorize_vals(vals)
            if vals.get('category_id'):
                update_vals = {'category_id': vals['category_id']}
                if vals.get('team_id') and not rec.team_id:
                    update_vals['team_id'] = vals['team_id']
                rec.write(update_vals)
                cat = self.env['helpdesk.category'].browse(vals['category_id'])
                rec.message_post(
                    body=_("Smart Classifier categorized this ticket as <b>%s</b>.", cat.name),
                    subtype_xmlid='mail.mt_note',
                )
            else:
                raise UserError(_("Could not determine a more specific category from the subject and description."))

    def action_open(self):
        self.write({'state': 'open'})

    def action_start_progress(self):
        for rec in self:
            vals = {'state': 'in_progress'}
            if not rec.user_id and not self.env.user.share:
                vals['user_id'] = self.env.user.id
            rec.write(vals)

    def action_pending_customer(self):
        self.write({'state': 'pending_customer'})

    def action_pending_internal(self):
        self.write({'state': 'pending_internal'})

    def action_resolve(self):
        if len(self) == 1 and not self.resolution_summary and not self.env.context.get('direct_resolve'):
            return {
                'name': _('Resolve Support Ticket'),
                'type': 'ir.actions.act_window',
                'res_model': 'helpdesk.ticket.close.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_ticket_id': self.id,
                    'default_target_state': 'resolved',
                },
            }
        self.write({'state': 'resolved'})

    def action_close(self):
        if len(self) == 1 and not self.resolution_summary and not self.env.context.get('direct_close'):
            return {
                'name': _('Close Support Ticket'),
                'type': 'ir.actions.act_window',
                'res_model': 'helpdesk.ticket.close.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_ticket_id': self.id,
                    'default_target_state': 'closed',
                },
            }
        self.write({'state': 'closed'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_reopen(self):
        for rec in self:
            if rec.state not in ('resolved', 'closed', 'cancelled'):
                raise UserError(_("Only Resolved, Closed, or Cancelled tickets can be reopened."))
            rec.write({'state': 'open'})
            rec.message_post(
                body=_("Ticket reopened by %s.", self.env.user.name),
                subtype_xmlid='mail.mt_note',
            )

    def action_open_merge_wizard(self):
        self.ensure_one()
        default_ids = (self | self.duplicate_ticket_ids).ids
        return {
            'name': _('Merge Duplicate Tickets'),
            'type': 'ir.actions.act_window',
            'res_model': 'helpdesk.ticket.merge.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_target_ticket_id': self.id,
                'default_ticket_ids': [(6, 0, default_ids)],
            },
        }

    def action_view_duplicates(self):
        self.ensure_one()
        return {
            'name': _('Potential Duplicate Tickets'),
            'type': 'ir.actions.act_window',
            'res_model': 'helpdesk.ticket',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.duplicate_ticket_ids.ids)],
        }

    def action_view_attachments(self):
        self.ensure_one()
        return {
            'name': _('Ticket Attachments'),
            'type': 'ir.actions.act_window',
            'res_model': 'ir.attachment',
            'view_mode': 'kanban,list,form',
            'domain': [('res_model', '=', 'helpdesk.ticket'), ('res_id', '=', self.id)],
            'context': {
                'default_res_model': 'helpdesk.ticket',
                'default_res_id': self.id,
            },
        }

    # ------------------------------------------------------------------
    # Scheduled Actions (Cron) – Idempotent & Safe Against Repeat Runs
    # ------------------------------------------------------------------
    @api.model
    def _cron_evaluate_sla_and_escalate(self):
        """Periodic cron: recompute SLA statuses and escalate newly breached active tickets."""
        active_states = ['new', 'open', 'in_progress', 'pending_customer', 'pending_internal']
        active_tickets = self.search([
            ('state', 'in', active_states),
            '|', ('sla_id', '!=', False), ('deadline', '!=', False),
        ])
        active_tickets._compute_sla_statuses()

        breached_to_escalate = active_tickets.filtered(
            lambda t: t.sla_status == 'breached' and not t.is_escalated and t.sla_id.auto_escalate
        )
        for ticket in breached_to_escalate:
            escalate_user = ticket.team_id.leader_id or ticket.sla_id.escalate_user_id
            vals = {'is_escalated': True}
            if ticket.priority in ('0', '1', '2'):
                vals['priority'] = '3'  # Elevate to Urgent on SLA breach
            ticket.write(vals)

            msg = _(
                "<b>SLA BREACH ESCALATION:</b> Ticket <b>%(name)s</b> has exceeded its SLA resolution deadline (%(deadline)s).",
                name=ticket.name,
                deadline=ticket.sla_deadline,
            )
            if escalate_user:
                msg += _(" Escalated to <b>%s</b>.", escalate_user.name)
                if escalate_user.partner_id:
                    ticket.message_subscribe(partner_ids=[escalate_user.partner_id.id])
                ticket.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=escalate_user.id,
                    summary=_('SLA Breached: %s', ticket.name),
                    note=msg,
                )
            ticket.message_post(body=msg, subtype_xmlid='mail.mt_note')

    @api.model
    def _cron_send_overdue_reminders(self):
        """Daily cron: send internal reminders for overdue tickets (idempotent via reminder_sent)."""
        now = fields.Datetime.now()
        active_states = ['new', 'open', 'in_progress', 'pending_customer', 'pending_internal']
        overdue_tickets = self.search([
            ('state', 'in', active_states),
            ('reminder_sent', '=', False),
            '|',
            '&', ('deadline', '!=', False), ('deadline', '<', now),
            '&', ('sla_deadline', '!=', False), ('sla_deadline', '<', now),
        ])
        for ticket in overdue_tickets:
            ticket.reminder_sent = True
            target_user = ticket.user_id or ticket.team_id.leader_id
            ticket.message_post(
                body=_(
                    "<b>Overdue Ticket Reminder:</b> This ticket is past its target deadline. "
                    "Assigned agent: <b>%s</b>.",
                    target_user.name if target_user else _('Unassigned'),
                ),
                subtype_xmlid='mail.mt_note',
            )
            if target_user and not self.env.context.get('skip_helpdesk_mail'):
                ticket._send_ticket_mail('helpdeskpro.mail_template_ticket_overdue')

    # ------------------------------------------------------------------
    # Dashboard Analytics RPC (Dynamic, Filterable by Date Range & Team)
    # ------------------------------------------------------------------
    @api.model
    def get_dashboard_data(self, date_range='30d', team_id=None):
        """Return all dynamic KPIs, chart datasets, and tables for the OWL Dashboard."""
        now = fields.Datetime.now()
        today = fields.Date.context_today(self)

        base_domain = [('company_id', 'in', self.env.companies.ids)]
        if team_id:
            try:
                base_domain.append(('team_id', '=', int(team_id)))
            except (TypeError, ValueError):
                pass

        date_from = None
        if date_range == 'today':
            date_from = datetime.combine(today, time.min)
        elif date_range == '7d':
            date_from = datetime.combine(today - timedelta(days=6), time.min)
        elif date_range == '30d':
            date_from = datetime.combine(today - timedelta(days=29), time.min)
        elif date_range == '90d':
            date_from = datetime.combine(today - timedelta(days=89), time.min)
        elif date_range == 'month':
            date_from = datetime.combine(today.replace(day=1), time.min)

        filtered_domain = list(base_domain)
        if date_from:
            filtered_domain.append(('create_date', '>=', date_from))

        tickets = self.search(filtered_domain)
        active_states = ('new', 'open', 'in_progress', 'pending_customer', 'pending_internal')
        done_states = ('resolved', 'closed')

        # 1. KPIs
        total_count = len(tickets)
        new_count = sum(1 for t in tickets if t.state == 'new')
        open_count = sum(1 for t in tickets if t.state == 'open')
        in_progress_count = sum(1 for t in tickets if t.state == 'in_progress')
        pending_count = sum(1 for t in tickets if t.state in ('pending_customer', 'pending_internal'))
        resolved_count = sum(1 for t in tickets if t.state == 'resolved')
        closed_count = sum(1 for t in tickets if t.state == 'closed')
        overdue_count = sum(1 for t in tickets if t.is_overdue)
        unassigned_count = sum(1 for t in tickets if t.state in active_states and not t.user_id)

        resolved_tickets = [t for t in tickets if t.state in done_states and t.resolution_hours > 0]
        avg_resolution_hours = (
            round(sum(t.resolution_hours for t in resolved_tickets) / len(resolved_tickets), 1)
            if resolved_tickets else 0.0
        )

        sla_tickets = [t for t in tickets if t.sla_id and t.state != 'cancelled']
        sla_breached = sum(1 for t in sla_tickets if t.sla_status == 'breached')
        sla_compliance_rate = (
            round(((len(sla_tickets) - sla_breached) / len(sla_tickets)) * 100.0, 1)
            if sla_tickets else 100.0
        )

        csat_tickets = [t for t in tickets if t.csat_score > 0]
        csat_avg = (
            round(sum(t.csat_score for t in csat_tickets) / len(csat_tickets), 2)
            if csat_tickets else 0.0
        )

        # 2. Chart: Tickets by Status
        state_labels = dict(TICKET_STATES)
        state_counts = {k: 0 for k, _ in TICKET_STATES}
        for t in tickets:
            state_counts[t.state] = state_counts.get(t.state, 0) + 1
        by_status = [
            {'key': k, 'label': state_labels[k], 'count': state_counts[k]}
            for k, _ in TICKET_STATES if state_counts[k] > 0
        ]

        # 3. Chart: Tickets by Priority
        prio_labels = dict(PRIORITY_SELECTION)
        prio_counts = {k: 0 for k, _ in PRIORITY_SELECTION}
        for t in tickets:
            prio_counts[t.priority] = prio_counts.get(t.priority, 0) + 1
        by_priority = [
            {'key': k, 'label': prio_labels[k], 'count': prio_counts[k]}
            for k, _ in reversed(PRIORITY_SELECTION)
        ]

        # 4. Chart: Tickets by Team
        teams = self.env['helpdesk.team'].search([('company_id', 'in', self.env.companies.ids)])
        team_map = {tm.id: {'id': tm.id, 'name': tm.name, 'count': 0, 'resolved': 0} for tm in teams}
        for t in tickets:
            if t.team_id.id in team_map:
                team_map[t.team_id.id]['count'] += 1
                if t.state in done_states:
                    team_map[t.team_id.id]['resolved'] += 1
        by_team = sorted(team_map.values(), key=lambda x: x['count'], reverse=True)

        # 5. Charts: Created Over Time & Resolved Over Time (Last 7 days buckets)
        timeline_days = 14 if date_range in ('30d', '90d', 'all') else 7
        created_series = []
        resolved_series = []
        for i in range(timeline_days - 1, -1, -1):
            day_d = today - timedelta(days=i)
            d_start = datetime.combine(day_d, time.min)
            d_end = datetime.combine(day_d, time.max)
            c_cnt = sum(1 for t in tickets if t.create_date and d_start <= t.create_date <= d_end)
            r_cnt = sum(1 for t in tickets if t.resolution_date and d_start <= t.resolution_date <= d_end)
            lbl = day_d.strftime('%d %b')
            created_series.append({'label': lbl, 'count': c_cnt})
            resolved_series.append({'label': lbl, 'count': r_cnt})

        # 6. Top Support Agents Performance Table
        agent_stats = {}
        for t in tickets:
            if not t.user_id:
                continue
            uid = t.user_id.id
            if uid not in agent_stats:
                agent_stats[uid] = {
                    'id': uid,
                    'name': t.user_id.name,
                    'assigned': 0,
                    'open': 0,
                    'resolved': 0,
                    'res_hours_list': [],
                }
            agent_stats[uid]['assigned'] += 1
            if t.state in active_states:
                agent_stats[uid]['open'] += 1
            elif t.state in done_states:
                agent_stats[uid]['resolved'] += 1
                if t.resolution_hours > 0:
                    agent_stats[uid]['res_hours_list'].append(t.resolution_hours)

        agents_list = []
        for ag in agent_stats.values():
            hrs = ag.pop('res_hours_list')
            ag['avg_hours'] = round(sum(hrs) / len(hrs), 1) if hrs else 0.0
            agents_list.append(ag)
        agents_list.sort(key=lambda x: (x['resolved'], x['assigned']), reverse=True)

        # 7. Urgent / Overdue / SLA Warning Attention List
        urgent_tickets = self.search(
            filtered_domain + [
                ('state', 'in', list(active_states)),
                '|', '|',
                ('priority', 'in', ['2', '3']),
                ('is_overdue', '=', True),
                ('sla_status', 'in', ['warning', 'breached']),
            ],
            order='is_overdue desc, priority desc, id desc',
            limit=8,
        )
        attention_list = [{
            'id': t.id,
            'name': t.name,
            'subject': t.subject,
            'customer': t.partner_id.name or t.customer_email or _('Guest'),
            'team': t.team_id.name or _('Unassigned'),
            'agent': t.user_id.name or _('Unassigned'),
            'priority': t.priority,
            'priority_label': prio_labels.get(t.priority, ''),
            'state': t.state,
            'state_label': state_labels.get(t.state, ''),
            'sla_status': t.sla_status,
            'is_overdue': t.is_overdue,
        } for t in urgent_tickets]

        return {
            'kpis': {
                'total': total_count,
                'new': new_count,
                'open': open_count,
                'in_progress': in_progress_count,
                'pending': pending_count,
                'resolved': resolved_count,
                'closed': closed_count,
                'overdue': overdue_count,
                'unassigned': unassigned_count,
                'avg_resolution_hours': avg_resolution_hours,
                'sla_compliance_rate': sla_compliance_rate,
                'csat_avg': csat_avg,
            },
            'by_status': by_status,
            'by_priority': by_priority,
            'by_team': by_team,
            'created_series': created_series,
            'resolved_series': resolved_series,
            'agents': agents_list[:6],
            'attention': attention_list,
            'teams': [{'id': tm.id, 'name': tm.name} for tm in teams],
            'date_from': fields.Datetime.to_string(date_from) if date_from else False,
        }
