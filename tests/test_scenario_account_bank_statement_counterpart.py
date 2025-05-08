# ===========================================
# Account Bank Statement Counterpart Scenario
# ===========================================

# Imports
from trytond.modules.account.exceptions import PeriodNotFoundError
from trytond.modules.account.tests.tools import create_fiscalyear, create_chart, get_accounts, create_tax
from trytond.modules.company.tests.tools import create_company, get_company
from trytond.tests.tools import activate_modules
from proteus import Model
from decimal import Decimal
import datetime
import unittest
from trytond.tests.test_tryton import drop_db

class Test(unittest.TestCase):
    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):

        now = datetime.datetime.now()

        # Install account_bank_statement_counterpart
        config = activate_modules('account_bank_statement_counterpart')

        # Create company
        _ = create_company()
        company = get_company()
        company.timezone = 'Europe/Madrid'
        company.save()

        # Reload the context
        User = Model.get('res.user')
        config._context = User.get_preferences(True, config.context)

        # Create fiscal year
        fiscalyear = create_fiscalyear(company)
        fiscalyear.click('create_period')

        # Create chart of accounts
        _ = create_chart(company)
        accounts = get_accounts(company)
        receivable = accounts['receivable']
        revenue = accounts['revenue']
        cash = accounts['cash']
        cash.bank_reconcile = True
        cash.reconcile = True
        cash.save()

        # Create tax
        tax = create_tax(Decimal('.10'))
        tax.save()

        # Create party
        Party = Model.get('party.party')
        party = Party(name='Party')
        party.save()

        # Create Journal
        AccountJournal = Model.get('account.journal')
        account_journal = AccountJournal(name='Statement', type='cash')
        account_journal.save()

        # Create Statement Journal
        StatementJournal = Model.get('account.bank.statement.journal')
        statement_journal = StatementJournal(name='Test',
            journal=account_journal, currency=company.currency, account=cash)
        statement_journal.save()

        # Create Bank Move
        period = fiscalyear.periods[0]
        Move = Model.get('account.move')
        move = Move()
        move.period = period
        move.journal = account_journal
        move.date = period.start_date
        line = move.lines.new()
        line.account = receivable
        line.debit = Decimal('80.0')
        line.party = party
        line2 = move.lines.new()
        line2.account = revenue
        line2.credit = Decimal('80.0')
        move.click('post')
        self.assertEqual(move.state, 'posted')
        _, line2 = move.lines

        # Create Bank Statement With Different Curreny
        BankStatement = Model.get('account.bank.statement')
        statement = BankStatement(journal=statement_journal, date=now)

        # Create Bank Statement Lines
        StatementLine = Model.get('account.bank.statement.line')
        Line = Model.get('account.move.line')
        statement_line = StatementLine()
        statement.lines.append(statement_line)
        statement_line.date = now
        statement_line.description = 'Statement Line'
        statement_line.amount = Decimal('80.0')
        statement.click('confirm')
        self.assertEqual(statement.state, 'confirmed')

        statement_line, = statement.lines
        statement_line.reload()
        line2.reload()
        statement_line.counterpart_lines.append(Line(line2.id))
        statement_line.save()
        statement_line.click('post')

        # Check reconciliation
        line2.reload()
        move_line, = [x for x in line2.reconciliation.lines if x != line2]
        self.assertEqual(move_line.account, line2.account)
        self.assertEqual(move_line.credit, Decimal('80.0'))

        move_line2, = [x for x in move_line.move.lines if x != move_line]
        self.assertEqual(move_line2.account, statement_line.account)
        self.assertEqual(move_line2.debit, Decimal('80.0'))

        receivable.reload()
        self.assertEqual(receivable.balance, Decimal('0.00'))

        # Not allow cancel when period is closed
        Period = Model.get('account.period')
        periods = Period.find([])
        Period.click(periods, 'close')
        with self.assertRaises(PeriodNotFoundError):
            statement_line.click('cancel')
