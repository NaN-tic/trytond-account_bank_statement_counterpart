# This file is part account_bank_statement_counterpart the COPYRIGHT file at
# the top level of this repository contains the full copyright notices and
# license terms.
from trytond.pool import Pool
from . import statement


def register():
    Pool.register(
        statement.MoveLine,
        statement.StatementLine,
        statement.Reconciliation,
        module='account_bank_statement_counterpart', type_='model')
