from odoo import api, fields, models


class HelpdeskKnowledgeCategory(models.Model):
    _name = 'helpdesk.knowledge.category'
    _description = 'HelpDesk Knowledge Base Category'
    _order = 'sequence, name'

    name = fields.Char(string='Category Name', required=True, translate=True)
    sequence = fields.Integer(string='Sequence', default=10)
    description = fields.Text(string='Description')
    icon = fields.Char(string='FontAwesome Icon', default='fa-book')
    active = fields.Boolean(string='Active', default=True)
    article_ids = fields.One2many('helpdesk.knowledge.article', 'category_id', string='Articles')
    article_count = fields.Integer(string='Article Count', compute='_compute_article_count')

    @api.depends('article_ids')
    def _compute_article_count(self):
        for rec in self:
            rec.article_count = len(rec.article_ids)


class HelpdeskKnowledgeArticle(models.Model):
    _name = 'helpdesk.knowledge.article'
    _description = 'HelpDesk Knowledge Base Article'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'is_faq desc, sequence, id desc'

    name = fields.Char(string='Article Title', required=True, tracking=True, translate=True)
    sequence = fields.Integer(string='Sequence', default=10)
    category_id = fields.Many2one(
        'helpdesk.knowledge.category',
        string='Knowledge Category',
        required=True,
        tracking=True,
    )
    ticket_category_id = fields.Many2one(
        'helpdesk.category',
        string='Related Ticket Category',
        help="Used to suggest this article when customers create tickets in this category.",
    )
    summary = fields.Text(string='Short Summary', help="Displayed in search results and portal cards.")
    content = fields.Html(string='Article Content', required=True, sanitize_style=True)
    keywords = fields.Char(string='Search Keywords', help="Comma-separated keywords for quick lookup.")
    is_faq = fields.Boolean(string='Featured in FAQ', default=False, tracking=True)
    is_published = fields.Boolean(string='Published on Portal', default=True, tracking=True)
    author_id = fields.Many2one(
        'res.users',
        string='Author',
        default=lambda self: self.env.user,
        tracking=True,
    )
    views_count = fields.Integer(string='Views', default=0, readonly=True)
    helpful_count = fields.Integer(string='Helpful Votes', default=0, readonly=True)
    active = fields.Boolean(string='Active', default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
    )

    def action_toggle_publish(self):
        for rec in self:
            rec.is_published = not rec.is_published

    @api.model
    def search_suggested_articles(self, query='', category_id=None, limit=5):
        """Return published KB articles matching a user query or ticket category."""
        domain = [('is_published', '=', True), ('active', '=', True)]
        if category_id:
            try:
                cid = int(category_id)
                if query and len(query.strip()) >= 2:
                    q = query.strip()
                    domain += [
                        '|', '|', '|',
                        ('ticket_category_id', '=', cid),
                        ('name', 'ilike', q),
                        ('summary', 'ilike', q),
                        ('keywords', 'ilike', q),
                    ]
                else:
                    domain += [('ticket_category_id', '=', cid)]
            except (TypeError, ValueError):
                pass
        elif query and len(query.strip()) >= 2:
            q = query.strip()
            domain += [
                '|', '|',
                ('name', 'ilike', q),
                ('summary', 'ilike', q),
                ('keywords', 'ilike', q),
            ]
        else:
            domain += [('is_faq', '=', True)]

        articles = self.sudo().search(domain, limit=limit)
        return [{
            'id': a.id,
            'title': a.name,
            'category': a.category_id.name or '',
            'summary': (a.summary or '')[:140],
            'is_faq': a.is_faq,
            'url': f'/helpdesk/knowledge/{a.id}',
        } for a in articles]
