from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestHelpdeskTicket(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({
            'name': 'Test Enterprise Customer',
            'email': 'customer@enterprise.example.com',
            'phone': '+1-555-0100',
        })
        cls.agent_1 = cls.env['res.users'].create({
            'name': 'Support Agent One',
            'login': 'hdp_agent1@example.com',
            'email': 'hdp_agent1@example.com',
            'groups_id': [(6, 0, [cls.env.ref('helpdeskpro.group_helpdesk_agent').id])],
        })
        cls.agent_2 = cls.env['res.users'].create({
            'name': 'Support Agent Two',
            'login': 'hdp_agent2@example.com',
            'email': 'hdp_agent2@example.com',
            'groups_id': [(6, 0, [cls.env.ref('helpdeskpro.group_helpdesk_agent').id])],
        })
        cls.team = cls.env['helpdesk.team'].create({
            'name': 'Core Engineering Support',
            'code': 'CORE',
            'assignment_method': 'balanced',
            'leader_id': cls.agent_1.id,
            'member_ids': [(6, 0, [cls.agent_1.id, cls.agent_2.id])],
        })

    def test_01_sequence_and_auto_assignment(self):
        ticket1 = self.env['helpdesk.ticket'].with_context(skip_helpdesk_mail=True).create({
            'subject': 'Database connection pool exhaustion',
            'partner_id': self.partner.id,
            'team_id': self.team.id,
            'priority': '2',
        })
        self.assertTrue(ticket1.name.startswith('HDP'), "Ticket number must use HDP sequence prefix.")
        self.assertEqual(ticket1.customer_email, 'customer@enterprise.example.com')
        self.assertIn(ticket1.user_id, self.team.member_ids, "Balanced team should auto-assign an agent.")

        # Second ticket should go to the other agent since agent_1/agent_2 balance out
        ticket2 = self.env['helpdesk.ticket'].with_context(skip_helpdesk_mail=True).create({
            'subject': 'Second concurrent issue for load balancing',
            'partner_id': self.partner.id,
            'team_id': self.team.id,
        })
        self.assertNotEqual(ticket1.user_id, ticket2.user_id, "Second ticket should be assigned to the least loaded agent.")

    def test_02_workflow_transitions_and_reopen(self):
        ticket = self.env['helpdesk.ticket'].with_context(skip_helpdesk_mail=True).create({
            'subject': 'Test workflow lifecycle',
            'partner_id': self.partner.id,
        })
        self.assertEqual(ticket.state, 'new')
        ticket.action_start_progress()
        self.assertEqual(ticket.state, 'in_progress')
        self.assertTrue(ticket.first_response_date, "First response timestamp must be recorded.")

        ticket.with_context(direct_resolve=True).action_resolve()
        self.assertEqual(ticket.state, 'resolved')
        self.assertTrue(ticket.resolution_date, "Resolution timestamp must be recorded.")

        ticket.with_context(direct_close=True).action_close()
        self.assertEqual(ticket.state, 'closed')
        self.assertTrue(ticket.closing_date, "Closing timestamp must be recorded.")

        # Reopen closed ticket
        ticket.action_reopen()
        self.assertEqual(ticket.state, 'open')
        self.assertEqual(ticket.reopen_count, 1)

        # Invalid transition: cancelled -> closed directly must raise ValidationError
        ticket.action_cancel()
        with self.assertRaises(ValidationError):
            ticket.write({'state': 'closed'})

    def test_03_duplicate_detection_and_merge(self):
        t1 = self.env['helpdesk.ticket'].with_context(skip_helpdesk_mail=True).create({
            'subject': 'Unable to export monthly invoice report PDF',
            'description': '<p>First report of the issue.</p>',
            'partner_id': self.partner.id,
        })
        t2 = self.env['helpdesk.ticket'].with_context(skip_helpdesk_mail=True).create({
            'subject': 'Cannot export monthly invoice report in portal',
            'description': '<p>Duplicate submission.</p>',
            'partner_id': self.partner.id,
        })
        self.assertIn(t1, t2.duplicate_ticket_ids, "Duplicate ticket must be detected.")

        wizard = self.env['helpdesk.ticket.merge.wizard'].create({
            'target_ticket_id': t1.id,
            'ticket_ids': [(6, 0, [t1.id, t2.id])],
            'merge_reason': 'Same customer & issue',
        })
        wizard.action_merge_tickets()
        self.assertEqual(t2.state, 'cancelled')
        self.assertEqual(t2.merged_into_id, t1)

    def test_04_dashboard_data_rpc(self):
        data = self.env['helpdesk.ticket'].get_dashboard_data(date_range='30d')
        self.assertIn('kpis', data)
        self.assertIn('by_status', data)
        self.assertIn('by_priority', data)
        self.assertIn('by_team', data)
        self.assertIn('created_series', data)
        self.assertIn('resolved_series', data)
