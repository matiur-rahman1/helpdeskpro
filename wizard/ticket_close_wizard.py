from odoo import api, fields, models, _
from odoo.exceptions import UserError


class HelpdeskTicketCloseWizard(models.TransientModel):
    _name = 'helpdesk.ticket.close.wizard'
    _description = 'Resolve or Close Ticket Wizard'

    ticket_id = fields.Many2one('helpdesk.ticket', string='Ticket', required=True, ondelete='cascade')
    target_state = fields.Selection([
        ('resolved', 'Resolved'),
        ('closed', 'Closed'),
    ], string='Target Status', default='resolved', required=True)
    resolution_summary = fields.Text(string='Resolution Summary', required=True)
    notify_customer = fields.Boolean(string='Notify Customer by Email', default=True)
    create_kb_article = fields.Boolean(
        string='Publish Solution to Knowledge Base',
        default=False,
        help="Automatically create a Knowledge Base article from this resolution.",
    )
    kb_category_id = fields.Many2one('helpdesk.knowledge.category', string='Knowledge Category')
    kb_title = fields.Char(string='Knowledge Article Title')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        ticket_id = res.get('ticket_id') or self.env.context.get('active_id')
        if ticket_id:
            ticket = self.env['helpdesk.ticket'].browse(ticket_id)
            res['ticket_id'] = ticket.id
            if ticket.resolution_summary:
                res['resolution_summary'] = ticket.resolution_summary
            res['kb_title'] = f"How to resolve: {ticket.subject}"
            kb_cat = self.env['helpdesk.knowledge.category'].search([], limit=1)
            if kb_cat:
                res['kb_category_id'] = kb_cat.id
        return res

    def action_confirm(self):
        self.ensure_one()
        ticket = self.ticket_id
        vals = {
            'resolution_summary': self.resolution_summary,
            'state': self.target_state,
        }
        ctx = dict(self.env.context, direct_resolve=True, direct_close=True)
        if not self.notify_customer:
            ctx['skip_helpdesk_mail'] = True

        ticket.with_context(ctx).write(vals)
        ticket.message_post(
            body=_(
                "<b>Ticket %(state)s</b><br/><b>Resolution Summary:</b><br/>%(summary)s",
                state=dict(self._fields['target_state'].selection).get(self.target_state),
                summary=self.resolution_summary,
            ),
            subtype_xmlid='mail.mt_comment' if self.notify_customer else 'mail.mt_note',
        )

        if self.create_kb_article and self.kb_category_id:
            article = self.env['helpdesk.knowledge.article'].create({
                'name': self.kb_title or ticket.subject,
                'category_id': self.kb_category_id.id,
                'ticket_category_id': ticket.category_id.id,
                'summary': self.resolution_summary[:200],
                'content': f"<h3>Problem</h3><p>{ticket.description or ticket.subject}</p>"
                           f"<h3>Resolution</h3><p>{self.resolution_summary}</p>",
                'is_published': True,
            })
            ticket.message_post(
                body=_("Created Knowledge Base Article: <b>%s</b>", article.name),
                subtype_xmlid='mail.mt_note',
            )
        return {'type': 'ir.actions.act_window_close'}


class HelpdeskTicketMergeWizard(models.TransientModel):
    _name = 'helpdesk.ticket.merge.wizard'
    _description = 'Merge Duplicate Support Tickets'

    target_ticket_id = fields.Many2one(
        'helpdesk.ticket',
        string='Primary Destination Ticket',
        required=True,
        help="All selected duplicate tickets will be merged into this primary ticket.",
    )
    ticket_ids = fields.Many2many(
        'helpdesk.ticket',
        string='Tickets to Merge',
        required=True,
    )
    merge_reason = fields.Char(
        string='Merge Note',
        default='Duplicate issue reported by the same customer.',
    )

    def action_merge_tickets(self):
        self.ensure_one()
        target = self.target_ticket_id
        sources = self.ticket_ids - target
        if not sources:
            raise UserError(_("Please select at least one other ticket to merge into the destination ticket."))

        merged_refs = []
        combined_notes = []

        for src in sources:
            merged_refs.append(f"{src.name} ({src.subject})")
            if src.description:
                combined_notes.append(f"<hr/><h4>Merged from {src.name}: {src.subject}</h4>{src.description}")

            # Re-link attachments
            src.attachment_ids.sudo().write({'res_id': target.id})

            # Subscribe followers onto target
            if src.message_partner_ids:
                target.message_subscribe(partner_ids=src.message_partner_ids.ids)

            # Merge tags
            if src.tag_ids:
                target.tag_ids = [(4, tag.id) for tag in src.tag_ids]

            # Mark source ticket as cancelled and link merged_into_id
            src.with_context(force_ticket_state=True, skip_helpdesk_mail=True).write({
                'state': 'cancelled',
                'merged_into_id': target.id,
            })
            src.message_post(
                body=_("This ticket was merged into primary ticket <b>%s</b>. Reason: %s",
                       target.name, self.merge_reason or _('Duplicate')),
                subtype_xmlid='mail.mt_note',
            )

        if combined_notes:
            target.description = (target.description or '') + ''.join(combined_notes)

        target.message_post(
            body=_(
                "<b>Merged Tickets into %(target)s:</b> %(sources)s<br/><b>Note:</b> %(reason)s",
                target=target.name,
                sources=', '.join(merged_refs),
                reason=self.merge_reason or _('Duplicate ticket consolidation'),
            ),
            subtype_xmlid='mail.mt_note',
        )

        return {
            'type': 'ir.actions.act_window',
            'name': target.name,
            'res_model': 'helpdesk.ticket',
            'res_id': target.id,
            'view_mode': 'form',
            'target': 'current',
        }
