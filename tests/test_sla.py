from datetime import timedelta
from odoo import fields
from odoo.tests.common import TransactionCase


class TestHelpdeskSLA(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.leader = cls.env['res.users'].create({
            'name': 'SLA Team Leader',
            'login': 'hdp_sla_leader@example.com',
            'email': 'hdp_sla_leader@example.com',
            'groups_id': [(6, 0, [cls.env.ref('helpdeskpro.group_helpdesk_leader').id])],
        })
        cls.team = cls.env['helpdesk.team'].create({
            'name': 'SLA Test Team',
            'leader_id': cls.leader.id,
            'assignment_method': 'manual',
        })
        cls.sla_urgent = cls.env['helpdesk.sla'].create({
            'name': 'Test Urgent SLA (1h / 4h)',
            'sequence': 1,
            'priority': '3',
            'team_ids': [(6, 0, [cls.team.id])],
            'response_time_hours': 1.0,
            'resolution_time_hours': 4.0,
            'warning_threshold_pct': 75.0,
            'auto_escalate': True,
        })

    def test_01_sla_deadline_and_breach_escalation(self):
        ticket = self.env['helpdesk.ticket'].with_context(skip_helpdesk_mail=True).create({
            'subject': 'Urgent production database outage',
            'team_id': self.team.id,
            'priority': '3',
        })
        self.assertEqual(ticket.sla_id, self.sla_urgent)
        self.assertTrue(ticket.sla_response_deadline)
        self.assertTrue(ticket.sla_deadline)
        self.assertEqual(ticket.sla_status, 'on_track')

        # Simulate SLA deadline in the past and run cron
        past_dt = fields.Datetime.now() - timedelta(hours=2)
        ticket.write({'sla_deadline': past_dt})
        self.env['helpdesk.ticket']._cron_evaluate_sla_and_escalate()

        self.assertEqual(ticket.sla_status, 'breached')
        self.assertTrue(ticket.is_overdue)
        self.assertTrue(ticket.is_escalated, "Breached ticket should be escalated by cron.")
