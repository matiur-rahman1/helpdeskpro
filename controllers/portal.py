import base64
from urllib.parse import quote_plus

from odoo import fields, http, _
from odoo.exceptions import AccessError, MissingError
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager


class HelpdeskProPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'ticket_count' in counters:
            partner = request.env.user.partner_id
            values['ticket_count'] = request.env['helpdesk.ticket'].sudo().search_count([
                '|',
                ('partner_id', '=', partner.id),
                ('message_partner_ids', 'in', [partner.id]),
            ])
        return values

    def _get_portal_ticket_domain(self, filterby='all', search=''):
        partner = request.env.user.partner_id
        domain = [
            '|',
            ('partner_id', '=', partner.id),
            ('message_partner_ids', 'in', [partner.id]),
        ]
        if filterby == 'open':
            domain.append(('state', 'in', ['new', 'open', 'in_progress', 'pending_customer', 'pending_internal']))
        elif filterby == 'resolved':
            domain.append(('state', '=', 'resolved'))
        elif filterby == 'closed':
            domain.append(('state', 'in', ['closed', 'cancelled']))

        if search and search.strip():
            q = search.strip()
            domain += ['|', ('name', 'ilike', q), ('subject', 'ilike', q)]
        return domain

    def _get_owned_ticket_or_raise(self, ticket_id):
        """Strictly verify that the current user owns or is a follower of the ticket."""
        user = request.env.user
        partner = user.partner_id
        ticket = request.env['helpdesk.ticket'].sudo().browse(ticket_id).exists()
        if not ticket:
            raise MissingError(_("This ticket does not exist."))
        if user.has_group('helpdeskpro.group_helpdesk_manager'):
            return ticket
        if ticket.partner_id != partner and partner not in ticket.message_partner_ids:
            raise AccessError(_("You do not have permission to access this support ticket."))
        return ticket

    # ------------------------------------------------------------------
    # 1. Portal My Tickets List
    # ------------------------------------------------------------------
    @http.route(['/my/tickets', '/my/tickets/page/<int:page>'], type='http', auth='user', website=True)
    def portal_my_tickets(self, page=1, filterby='all', search='', **kw):
        Ticket = request.env['helpdesk.ticket'].sudo()
        domain = self._get_portal_ticket_domain(filterby=filterby, search=search)
        total = Ticket.search_count(domain)
        pager = portal_pager(
            url='/my/tickets',
            url_args={'filterby': filterby, 'search': search},
            total=total,
            page=page,
            step=15,
        )
        tickets = Ticket.search(domain, order='id desc', limit=15, offset=pager['offset'])
        return request.render('helpdeskpro.portal_my_tickets', {
            'tickets': tickets,
            'page_name': 'helpdesk_tickets',
            'pager': pager,
            'default_url': '/my/tickets',
            'filterby': filterby,
            'search': search,
            'success': kw.get('success'),
            'error': kw.get('error'),
        })

    # ------------------------------------------------------------------
    # 2. Portal Create New Ticket
    # ------------------------------------------------------------------
    @http.route(['/my/tickets/new'], type='http', auth='user', website=True)
    def portal_new_ticket(self, **kw):
        categories = request.env['helpdesk.category'].sudo().search([('active', '=', True)])
        faqs = request.env['helpdesk.knowledge.article'].sudo().search([
            ('is_published', '=', True),
            ('is_faq', '=', True),
        ], limit=5)
        return request.render('helpdeskpro.portal_create_ticket', {
            'categories': categories,
            'faqs': faqs,
            'page_name': 'helpdesk_new_ticket',
            'error': kw.get('error'),
        })

    @http.route(['/my/tickets/submit'], type='http', auth='user', website=True, methods=['POST'], csrf=True)
    def portal_submit_ticket(self, **post):
        subject = (post.get('subject') or '').strip()
        description = (post.get('description') or '').strip()
        if not subject or not description:
            return request.redirect('/my/tickets/new?error=' + quote_plus('Please enter both a Subject and Description.'))

        partner = request.env.user.partner_id
        priority = post.get('priority') if post.get('priority') in ('0', '1', '2', '3') else '1'
        ticket_type = post.get('ticket_type') or 'question'
        category_id = False
        if post.get('category_id'):
            try:
                category_id = int(post.get('category_id'))
            except (TypeError, ValueError):
                category_id = False

        vals = {
            'subject': subject,
            'description': f"<p>{description}</p>",
            'partner_id': partner.id,
            'customer_email': partner.email or request.env.user.login,
            'customer_phone': partner.phone,
            'priority': priority,
            'ticket_type': ticket_type,
            'category_id': category_id,
            'source': 'portal',
        }
        ticket = request.env['helpdesk.ticket'].sudo().create(vals)

        # Handle uploaded file attachment if provided
        uploaded_file = request.httprequest.files.get('attachment')
        if uploaded_file and uploaded_file.filename:
            file_bytes = uploaded_file.read()
            if file_bytes:
                request.env['ir.attachment'].sudo().create({
                    'name': uploaded_file.filename,
                    'datas': base64.b64encode(file_bytes),
                    'res_model': 'helpdesk.ticket',
                    'res_id': ticket.id,
                    'type': 'binary',
                })

        return request.redirect(f'/my/tickets/{ticket.id}?success=1')

    # ------------------------------------------------------------------
    # 3. Portal Ticket Detail, Public Reply, Attachment Download & CSAT
    # ------------------------------------------------------------------
    @http.route(['/my/tickets/<int:ticket_id>'], type='http', auth='user', website=True)
    def portal_ticket_detail(self, ticket_id, **kw):
        try:
            ticket = self._get_owned_ticket_or_raise(ticket_id)
        except (AccessError, MissingError):
            return request.redirect('/my/tickets?error=' + quote_plus('Ticket not found or access denied.'))

        # Strictly filter messages: ONLY public comments (mail.mt_comment) and not internal
        mt_comment = request.env.ref('mail.mt_comment')
        public_messages = ticket.message_ids.filtered(
            lambda m: m.subtype_id == mt_comment and not m.is_internal and m.body
        )
        attachments = request.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'helpdesk.ticket'),
            ('res_id', '=', ticket.id),
        ])

        return request.render('helpdeskpro.portal_ticket_detail', {
            'ticket': ticket,
            'public_messages': public_messages,
            'attachments': attachments,
            'page_name': 'helpdesk_ticket_detail',
            'success': kw.get('success'),
            'error': kw.get('error'),
        })

    @http.route(['/my/tickets/<int:ticket_id>/reply'], type='http', auth='user', website=True, methods=['POST'], csrf=True)
    def portal_ticket_reply(self, ticket_id, **post):
        try:
            ticket = self._get_owned_ticket_or_raise(ticket_id)
        except (AccessError, MissingError):
            return request.redirect('/my/tickets?error=' + quote_plus('Access denied.'))

        message_body = (post.get('message') or '').strip()
        uploaded_file = request.httprequest.files.get('attachment')

        if not message_body and not (uploaded_file and uploaded_file.filename):
            return request.redirect(f'/my/tickets/{ticket.id}?error=' + quote_plus('Please enter a message or attach a file.'))

        attachment_ids = []
        if uploaded_file and uploaded_file.filename:
            file_bytes = uploaded_file.read()
            if file_bytes:
                att = request.env['ir.attachment'].sudo().create({
                    'name': uploaded_file.filename,
                    'datas': base64.b64encode(file_bytes),
                    'res_model': 'helpdesk.ticket',
                    'res_id': ticket.id,
                    'type': 'binary',
                })
                attachment_ids.append(att.id)

        ticket.message_post(
            body=message_body or _('Attached file: %s', uploaded_file.filename),
            author_id=request.env.user.partner_id.id,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
            attachment_ids=attachment_ids,
        )

        if ticket.state == 'pending_customer':
            ticket.write({'state': 'in_progress'})

        return request.redirect(f'/my/tickets/{ticket.id}?success=reply')

    @http.route(['/my/tickets/<int:ticket_id>/reopen'], type='http', auth='user', website=True, methods=['POST'], csrf=True)
    def portal_ticket_reopen(self, ticket_id, **post):
        try:
            ticket = self._get_owned_ticket_or_raise(ticket_id)
        except (AccessError, MissingError):
            return request.redirect('/my/tickets?error=' + quote_plus('Access denied.'))

        if ticket.state in ('resolved', 'closed'):
            reason = (post.get('reason') or '').strip()
            ticket.write({'state': 'open'})
            ticket.message_post(
                body=_("Customer reopened this ticket from the portal.%s", f" Reason: {reason}" if reason else ""),
                author_id=request.env.user.partner_id.id,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )
        return request.redirect(f'/my/tickets/{ticket.id}?success=reopened')

    @http.route(['/my/tickets/<int:ticket_id>/rate'], type='http', auth='user', website=True, methods=['POST'], csrf=True)
    def portal_ticket_rate(self, ticket_id, **post):
        try:
            ticket = self._get_owned_ticket_or_raise(ticket_id)
        except (AccessError, MissingError):
            return request.redirect('/my/tickets?error=' + quote_plus('Access denied.'))

        rating = post.get('csat_rating')
        if rating in ('1', '2', '3', '4', '5'):
            comment = (post.get('csat_comment') or '').strip()
            ticket.write({
                'csat_rating': rating,
                'csat_comment': comment,
                'csat_date': fields.Datetime.now(),
            })
            ticket.message_post(
                body=_("Customer rated support: <b>%s / 5</b>.%s", rating, f" Feedback: {comment}" if comment else ""),
                author_id=request.env.user.partner_id.id,
                subtype_xmlid='mail.mt_note',
            )
        return request.redirect(f'/my/tickets/{ticket.id}?success=rated')

    @http.route(['/my/tickets/<int:ticket_id>/attachment/<int:attachment_id>'], type='http', auth='user', website=True)
    def portal_ticket_attachment_download(self, ticket_id, attachment_id, **kw):
        try:
            ticket = self._get_owned_ticket_or_raise(ticket_id)
        except (AccessError, MissingError):
            return request.redirect('/my/tickets?error=' + quote_plus('Access denied.'))

        att = request.env['ir.attachment'].sudo().search([
            ('id', '=', attachment_id),
            ('res_model', '=', 'helpdesk.ticket'),
            ('res_id', '=', ticket.id),
        ], limit=1)
        if not att:
            return request.redirect(f'/my/tickets/{ticket.id}?error=' + quote_plus('Attachment not found.'))

        raw = base64.b64decode(att.datas or b'')
        return request.make_response(raw, headers=[
            ('Content-Type', att.mimetype or 'application/octet-stream'),
            ('Content-Length', len(raw)),
            ('Content-Disposition', f'attachment; filename="{att.name}"'),
        ])

    # ------------------------------------------------------------------
    # 4. Knowledge Base & Smart Article Suggestion Endpoints
    # ------------------------------------------------------------------
    @http.route(['/helpdesk/kb/suggest'], type='json', auth='user', website=True)
    def kb_suggest_articles(self, query='', category_id=None):
        Article = request.env['helpdesk.knowledge.article'].sudo()
        return Article.search_suggested_articles(query=query, category_id=category_id, limit=5)

    @http.route(['/helpdesk/knowledge'], type='http', auth='public', website=True)
    def helpdesk_knowledge_home(self, search='', category_id=None, **kw):
        Category = request.env['helpdesk.knowledge.category'].sudo()
        Article = request.env['helpdesk.knowledge.article'].sudo()

        domain = [('is_published', '=', True), ('active', '=', True)]
        selected_cat = None
        if category_id:
            try:
                selected_cat = Category.browse(int(category_id)).exists()
                if selected_cat:
                    domain.append(('category_id', '=', selected_cat.id))
            except (TypeError, ValueError):
                pass

        if search and search.strip():
            q = search.strip()
            domain += ['|', '|', ('name', 'ilike', q), ('summary', 'ilike', q), ('keywords', 'ilike', q)]

        articles = Article.search(domain, order='is_faq desc, sequence, id desc')
        categories = Category.search([('active', '=', True)])
        return request.render('helpdeskpro.portal_knowledge_home', {
            'categories': categories,
            'articles': articles,
            'selected_cat': selected_cat,
            'search': search,
        })

    @http.route(['/helpdesk/knowledge/<int:article_id>'], type='http', auth='public', website=True)
    def helpdesk_knowledge_article(self, article_id, **kw):
        article = request.env['helpdesk.knowledge.article'].sudo().search([
            ('id', '=', article_id),
            ('is_published', '=', True),
        ], limit=1)
        if not article:
            return request.redirect('/helpdesk/knowledge')

        article.sudo().write({'views_count': article.views_count + 1})
        return request.render('helpdeskpro.portal_knowledge_article_detail', {
            'article': article,
            'voted': kw.get('voted'),
        })

    @http.route(['/helpdesk/knowledge/<int:article_id>/helpful'], type='http', auth='public', website=True, methods=['POST'], csrf=True)
    def helpdesk_knowledge_helpful(self, article_id, **post):
        article = request.env['helpdesk.knowledge.article'].sudo().search([
            ('id', '=', article_id),
            ('is_published', '=', True),
        ], limit=1)
        if article:
            article.sudo().write({'helpful_count': article.helpful_count + 1})
        return request.redirect(f'/helpdesk/knowledge/{article_id}?voted=1')
