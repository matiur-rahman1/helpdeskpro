from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase


class TestHelpdeskPortal(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        portal_group = cls.env.ref('base.group_portal')
        cls.portal_user_a = cls.env['res.users'].create({
            'name': 'Portal Customer A',
            'login': 'portal_a@example.com',
            'email': 'portal_a@example.com',
            'groups_id': [(6, 0, [portal_group.id])],
        })
        cls.portal_user_b = cls.env['res.users'].create({
            'name': 'Portal Customer B',
            'login': 'portal_b@example.com',
            'email': 'portal_b@example.com',
            'groups_id': [(6, 0, [portal_group.id])],
        })

    def test_01_portal_ticket_isolation_and_internal_notes(self):
        ticket_a = self.env['helpdesk.ticket'].with_context(skip_helpdesk_mail=True).create({
            'subject': 'Portal Customer A Issue',
            'partner_id': self.portal_user_a.partner_id.id,
            'internal_notes': 'CONFIDENTIAL STAFF NOTE',
        })
        # Portal User A can read their own ticket
        found_a = self.env['helpdesk.ticket'].with_user(self.portal_user_a).search([('id', '=', ticket_a.id)])
        self.assertEqual(found_a, ticket_a)

        # Portal User B cannot see Portal User A's ticket
        found_b = self.env['helpdesk.ticket'].with_user(self.portal_user_b).search([('id', '=', ticket_a.id)])
        self.assertFalse(found_b, "Portal user B must never see Portal user A's tickets.")

        # Portal User A cannot read internal_notes field (restricted to group_helpdesk_user)
        with self.assertRaises(AccessError):
            _ = ticket_a.with_user(self.portal_user_a).internal_notes

    def test_02_knowledge_base_suggestions(self):
        results = self.env['helpdesk.knowledge.article'].search_suggested_articles(query='password')
        self.assertTrue(len(results) >= 1, "Suggested KB articles should match 'password'.")
