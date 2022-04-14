# This file is part of the account_bank_statement_counterpart module for Tryton.
# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
import unittest
import doctest
import trytond.tests.test_tryton
from trytond.tests.test_tryton import ModuleTestCase
from trytond.tests.test_tryton import doctest_teardown
from trytond.tests.test_tryton import doctest_checker
from trytond.modules.company.tests import CompanyTestMixin


class AccountBankStatementCounterpartTestCase(CompanyTestMixin, ModuleTestCase):
    'Test Account Bank Statement Counterpart module'
    module = 'account_bank_statement_counterpart'


def suite():
    suite = trytond.tests.test_tryton.suite()
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(
        AccountBankStatementCounterpartTestCase))
    suite.addTests(doctest.DocFileSuite(
            'scenario_account_bank_statement_counterpart.rst',
            tearDown=doctest_teardown, encoding='utf-8',
            checker=doctest_checker,
            optionflags=doctest.REPORT_ONLY_FIRST_FAILURE))
    return suite
