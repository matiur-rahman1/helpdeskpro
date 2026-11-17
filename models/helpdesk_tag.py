from random import randint
from odoo import fields, models


class HelpdeskTag(models.Model):
    _name = 'helpdesk.tag'
    _description = 'HelpDesk Ticket Tag'
    _order = 'name'

    def _get_default_color(self):
        return randint(1, 11)

    name = fields.Char(string='Tag Name', required=True, translate=True)
    color = fields.Integer(string='Color Index', default=_get_default_color)

    _sql_constraints = [
        ('name_uniq', 'unique (name)', 'Tag name must be unique!'),
    ]
