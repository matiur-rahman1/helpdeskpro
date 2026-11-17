{
    'name': 'HelpDeskPro – Intelligent Customer Support & Ticket Management',
    'version': '18.0.1.0.0',
    'category': 'Services/Helpdesk',
    'summary': 'Enterprise Customer Support, Ticketing, SLA Management, Knowledge Base & Customer Portal',
    'description': """
HelpDeskPro – Intelligent Customer Support & Ticket Management System
=====================================================================
A complete, production-quality customer support and helpdesk solution for Odoo 18 Community Edition:
- Interactive OWL Analytics Dashboard with Date & Team Filtering
- End-to-End Ticket Lifecycle Management (HDP00001 sequence, 8 workflow stages)
- Support Team & Agent Workload Management (Manual / Balanced Auto-Assignment)
- Configurable SLA Policies (Response & Resolution Targets, Warning & Breach Escalation)
- Duplicate Ticket Detection & Ticket Merge Wizard with History Preservation
- Built-in Knowledge Base & FAQ System with Smart Article Suggestions
- Rule-Based & Optional AI Auto-Categorization
- Customer Portal (/my/tickets) with Attachment Upload, Public Replies & CSAT Rating
- Multi-Company Record Rules & 5-Tier Role-Based Access Control
    """,
    'author': 'HelpDeskPro Engineering',
    'website': 'https://github.com/helpdeskpro/helpdeskpro',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'portal',
        'website',
    ],
    'data': [
        # 1. Security
        'security/helpdesk_security.xml',
        'security/ir.model.access.csv',
        'security/record_rules.xml',
        # 2. Data & Sequences
        'data/sequence.xml',
        'data/mail_template.xml',
        'data/cron.xml',
        'data/default_data.xml',
        # 3. Wizards
        'wizard/ticket_close_wizard_views.xml',
        # 4. Backend Views
        'views/team_views.xml',
        'views/category_views.xml',
        'views/sla_views.xml',
        'views/knowledge_views.xml',
        'views/ticket_views.xml',
        'views/res_partner_views.xml',
        'views/dashboard_views.xml',
        'views/menu_views.xml',
        # 5. Portal & Website Views
        'views/portal_templates.xml',
        # 6. Reports
        'report/ticket_report.xml',
        'report/ticket_templates.xml',
    ],
    'demo': [
        'demo/demo_data.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'helpdeskpro/static/src/css/helpdesk_dashboard.css',
            'helpdeskpro/static/src/js/helpdesk_dashboard.js',
            'helpdeskpro/static/src/xml/helpdesk_dashboard.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
