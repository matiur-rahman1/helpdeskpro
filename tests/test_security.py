from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase


class TestHelpdeskSecurity(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.basic_user_1 = cls.env['res.users'].create({
            'name': 'Basic User 1',
            'login': 'hdp_basic1@example.com',
            'email': 'hdp_basic1@example.com',
            'groups_id': [(6, 0, [cls.env.ref('helpdeskpro.group_helpdesk_user').id])],
        })
        cls.basic_user_2 = cls.env['res.users'].create({
            'name': 'Basic User 2',
            'login': 'hdp_basic2@example.com',
            'email': 'hdp_basic2@example.com',
            'groups_id': [(6, 0, [cls.env.ref('helpdeskpro.group_helpdesk_user').id])],
        })
        cls.manager = cls.env['res.users'].create({
            'name': 'HelpDesk Manager User',
            'login': 'hdp_mgr@example.com',
            'email': 'hdp_mgr@example.com',
            'groups_id': [(6, 0, [cls.env.ref('helpdeskpro.group_helpdesk_manager').id])],
        })

    def test_01_record_rules_isolation(self):
        t1 = self.env['helpdesk.ticket'].with_user(self.basic_user_1).with_context(skip_helpdesk_mail=True).create({
            'subject': 'User 1 private ticket',
            'user_id': self.basic_user_1.id,
        })
        # Basic user 2 should not see Basic user 1's assigned ticket
        visible_to_u2 = self.env['helpdesk.ticket'].with_user(self.basic_user_2).search([('id', '=', t1.id)])
        self.assertFalse(visible_to_u2, "Basic user 2 must not see another user's private ticket.")

        # Manager sees all tickets
        visible_to_mgr = self.env['helpdesk.ticket'].with_user(self.manager).search([('id', '=', t1.id)])
        self.assertEqual(visible_to_mgr, t1, "HelpDesk Manager must have access to all tickets.")

        # Basic user cannot delete tickets
        with self.assertRaises(AccessError):
            t1.with_user(self.basic_user_1).unlink()
