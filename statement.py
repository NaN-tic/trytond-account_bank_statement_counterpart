# This file is part account_bank_statement_counterpart the COPYRIGHT file at
# the top level of this repository contains the full copyright notices and
# license terms.
from decimal import Decimal
from trytond.model import ModelView, fields
from trytond.pyson import Eval, Not, Equal, Bool
from trytond.pool import Pool, PoolMeta
from trytond.transaction import Transaction
from trytond import backend
from trytond.i18n import gettext
from trytond.exceptions import UserError


__all__ = ['StatementLine', 'Move', 'MoveLine', 'Reconciliation']


CONFIRMED_STATES = {
    'readonly': Not(Equal(Eval('state'), 'draft'))
    }
CONFIRMED_DEPENDS = ['state']

POSTED_STATES = {
    'readonly': Not(Equal(Eval('state'), 'confirmed'))
    }
POSTED_DEPENDS = ['state']

_ZERO = Decimal(0)


class StatementLine(metaclass=PoolMeta):
    __name__ = 'account.bank.statement.line'

    counterpart_lines = fields.One2Many('account.move.line',
        'bank_statement_line_counterpart', 'Counterpart',
        states=POSTED_STATES, domain=[
            ('move.company', '=', Eval('company', -1)),
            ('account.reconcile', '=', True),
            ('move_state', '=', 'posted'),
            ],
        add_remove=[
            ('reconciliation', '=', None),
            ('bank_statement_line_counterpart', '=', None),
            ('move_state', '=', 'posted'),
            ('account.reconcile', '=', True),
            ])
    account_date = fields.Function(fields.DateTime('Account Date'),
        'get_date_utc', searcher='search_date_utc',
        setter='set_date_utc')
    account_date_utc = fields.DateTime('Account Date UTC',
        states={
            'required': Bool(Eval('counterpart_lines')),
        })

    @classmethod
    def __register__(cls, module_name):
        table = backend.TableHandler(cls, module_name)

        # Migration: rename account_date into account_date_utc
        if (table.column_exist('account_date')
                and not table.column_exist('account_date_utc')):
            table.column_rename('account_date', 'account_date_utc')

        super(StatementLine, cls).__register__(module_name)

    @fields.depends('date')
    def on_change_with_account_date(self):
        return self.date

    @classmethod
    def create(cls, vlist):
        vlist = [x.copy() for x in vlist]
        for vals in vlist:
            if vals.get('account_date') or not vals.get('date', None):
                continue
            vals['account_date'] = vals['date']
        return super().create(vlist)

    def _search_counterpart_line_reconciliation_domain(self):
        return [
            ('reconciliation', '=', None),
            ('bank_statement_line_counterpart', '=', None),
            ('move_state', '=', 'posted'),
            ('account.reconcile', '=', True),
            ('move.company', '=', self.company.id),
            ]

    def _search_counterpart_line_reconciliation(self):
        search_amount = self.company_amount - self.moves_amount
        if search_amount == _ZERO:
            return

        MoveLine = Pool().get('account.move.line')
        domain = self._search_counterpart_line_reconciliation_domain()
        if search_amount > 0:
            domain.append(('debit', '=', abs(search_amount)))
        else:
            domain.append(('credit', '=', abs(search_amount)))
        lines = MoveLine.search(domain)

        if len(lines) == 1:
            line, = lines
            line.bank_statement_line_counterpart = self
            line.save()

    def _search_reconciliation(self):
        super(StatementLine, self)._search_reconciliation()
        self._search_counterpart_line_reconciliation()

    def _check_period(lines):
        Period = Pool().get('account.period')

        company_ids = set(x.company.id for x in lines)
        check_lines = dict((x, set()) for x in company_ids)

        for line in lines:
            if not line.account_date:
                continue
            check_lines.setdefault(
                line.company.id, set()).add(line.account_date)

        for company, dates in check_lines.items():
            for date in set(dates):
                Period.find(company, date=date.date())

    @classmethod
    @ModelView.button
    def post(cls, statement_lines):
        cls._check_period(statement_lines)
        for st_line in statement_lines:
            for line in st_line.counterpart_lines:
                st_line.create_move(line)
        super(StatementLine, cls).post(statement_lines)

    @classmethod
    @ModelView.button
    def cancel(cls, statement_lines):
        cls._check_period(statement_lines)
        super(StatementLine, cls).cancel(statement_lines)
        cls.reset_counterpart_move(statement_lines)
        to_write = []
        for st_line in statement_lines:
            to_write.extend(([st_line], {
                        'counterpart_lines': [('remove',
                                [x.id for x in st_line.counterpart_lines])]}))
        if to_write:
            cls.write(*to_write)

    @fields.depends('state', 'counterpart_lines')
    def on_change_with_moves_amount(self, name=None):
        amount = super(StatementLine, self).on_change_with_moves_amount(name)
        amount += sum((x.debit or _ZERO) - (x.credit or _ZERO) for x in
            self.counterpart_lines)
        if self.company_currency:
            amount = self.company_currency.round(amount)
        return amount

    @classmethod
    def reset_counterpart_move(cls, lines):
        pool = Pool()
        Reconciliation = pool.get('account.move.reconciliation')
        Move = pool.get('account.move')

        delete_moves = []
        delete_reconciliation = []
        for line in lines:
            for counterpart in line.counterpart_lines:
                if not counterpart.reconciliation:
                    continue
                for x in counterpart.reconciliation.lines:
                    if x.move != counterpart.move:
                        delete_moves.append(x.move)
                delete_reconciliation.append(counterpart.reconciliation)
        with Transaction().set_context(from_account_bank_statement_line=True):
            if delete_reconciliation:
                Reconciliation.delete(delete_reconciliation)
            if delete_moves:
                Move.delete(delete_moves)

    def create_move(self, line):
        pool = Pool()
        Move = pool.get('account.move')
        Line = pool.get('account.move.line')
        Period = pool.get('account.period')

        if line.reconciliation:
            return

        # Create Move
        period_id = Period.find(self.company, date=self.account_date.date())
        move_lines = self._get_counterpart_move_lines(line)
        move = Move(
            origin=self.statement,
            period=period_id,
            journal=self.journal.journal,
            lines=move_lines,
            date=self.account_date.date())
        move.save()
        Move.post([move])

        journal = self.journal
        account = journal.account

        # Reconcile lines
        counterparts = [x for x in move.lines if x.account != account]
        if not counterparts:
            raise UserError(gettext(
                'account_bank_statement_counterpart.not_found_counterparts'))
        Line.reconcile([counterparts[0], line])
        self.save()

    def _get_counterpart_move_lines(self, line):
        pool = Pool()
        MoveLine = pool.get('account.move.line')
        Currency = Pool().get('currency.currency')

        # Generate counterpart line
        move_lines = []
        counterpart = MoveLine()
        counterpart.journal = self.journal.journal
        counterpart.description = line.description
        counterpart.debit = line.credit
        counterpart.credit = line.debit
        counterpart.account = line.account
        if line.account.party_required:
            counterpart.party = line.party
        counterpart.origin = self

        amount = line.debit - line.credit
        amount_second_currency = None
        second_currency = None
        if self.statement_currency != self.company_currency:
            with Transaction().set_context(date=self.date.date()):
                amount_second_currency = abs(Currency.compute(
                    self.company_currency, amount, self.statement_currency))
            second_currency = self.statement_currency
            counterpart.amount_second_currency = (amount_second_currency *
                (-1 if amount > _ZERO else 1))
            counterpart.second_currency = second_currency

        # Generate Bank Line.
        journal = self.journal
        account = journal.account

        if not account:
            raise UserError(gettext(
                'account_bank_statement_counterpart.account_statement_journal',
                journal=journal.rec_name))
        if not account.bank_reconcile:
            raise UserError(gettext(
                    'account_bank_statement_counterpart.'
                    'account_not_bank_reconcile',
                    journal=journal.rec_name))
        if line.account == account:
            raise UserError(gettext(
                'account_bank_statement_counterpart.same_account',
                    account=line.account.rec_name,
                    line=line.rec_name,
                    journal=journal.rec_name))

        bank_move = MoveLine(
            journal=journal.journal,
            description=self.description,
            debit=amount >= _ZERO and amount or _ZERO,
            credit=amount < _ZERO and -amount or _ZERO,
            account=account,
            origin=self,
            move_origin=self.statement,
            second_currency=second_currency,
            amount_second_currency=(amount_second_currency *
                (1 if amount > _ZERO else -1)
                if amount_second_currency else None),
            )
        if account.party_required:
            bank_move.party = line.party or self.company.party

        move_lines.append(bank_move)
        move_lines.append(counterpart)
        return move_lines


class Move(metaclass=PoolMeta):
    __name__ = 'account.move'

    @classmethod
    def check_modify(cls, *args, **kwargs):
        if Transaction().context.get('from_account_bank_statement_line',
                False):
            return
        return super(Move, cls).check_modify(*args, **kwargs)


class MoveLine(metaclass=PoolMeta):
    __name__ = 'account.move.line'

    bank_statement_line_counterpart = fields.Many2One(
        'account.bank.statement.line', 'Bank Statement Line Counterpart',
        readonly=True)

    @classmethod
    def __setup__(cls):
        super(MoveLine, cls).__setup__()
        cls._check_modify_exclude.add('bank_statement_line_counterpart')

    @classmethod
    def copy(cls, lines, default=None):
        if default is None:
            default = {}
        default['bank_statement_line_counterpart'] = None
        return super(MoveLine, cls).copy(lines, default=default)

    @classmethod
    def check_modify(cls, *args, **kwargs):
        if Transaction().context.get('from_account_bank_statement_line',
                False):
            return
        return super(MoveLine, cls).check_modify(*args, **kwargs)


class Reconciliation(metaclass=PoolMeta):
    __name__ = 'account.move.reconciliation'

    @classmethod
    def delete(cls, reconciliations):
        from_statement = Transaction().context.get(
            'from_account_bank_statement_line', False)
        if not from_statement:
            cls.check_bank_statement_lines(reconciliations)
        return super(Reconciliation, cls).delete(reconciliations)

    @classmethod
    def check_bank_statement_lines(cls, reconciliations):
        BankLine = Pool().get('account.bank.statement.line')

        lines = [line for reconciliation in reconciliations
            for line in reconciliation.lines
            if isinstance(line.origin, BankLine)]

        if lines:
            line = lines[0]
            raise UserError(gettext(
                    'account_bank_statement_counterpart.'
                    'reconciliation_cannot_delete',
                    bank_line=line.origin.rec_name))
