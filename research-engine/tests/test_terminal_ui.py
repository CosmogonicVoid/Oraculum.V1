"""Report analytics and search semantics for the terminal UI."""
import unittest
from copy import deepcopy
from oraculum.dashboard_view import market_context, explore_html
from oraculum.ui import document
from test_dashboard_ui import ui_report, Page

class TerminalTests(unittest.TestCase):
    def test_score_bins_include_boundaries_and_exclude_missing(self):
        report = ui_report()
        base = report['assets'][0]
        report['assets'] = []
        for i, value in enumerate((0,19.9,20,40,60,80,100,None,float('nan'),-1)):
            row = deepcopy(base)
            row['symbol'] = 'X' + str(i)
            row['combined']['score'] = value
            report['assets'].append(row)
        body = market_context(report)
        self.assertIn('0–&lt;20: 2 stocks', body)
        self.assertIn('80–100: 2 stocks', body)
        self.assertIn('7 scored · 3 without a valid combined score', body)
        self.assertNotIn('width:nan', body)

    def test_context_is_report_pinned_and_escapes_symbols(self):
        report = ui_report()
        report['assets'][0]['symbol'] = '<img src=x>'
        report['assets'][0]['status'] = 'eligible'
        report['assets'][0]['metrics']['momentum_20d'] = 1.25
        body = market_context(report)
        self.assertIn('report=' + report['report_id'], body)
        self.assertIn('&lt;img src=x&gt;', body)
        self.assertNotIn('<img src=x>', body)

    def test_global_search_uses_existing_read_only_route(self):
        page = Page(document('Overview', '', active='today'))
        self.assertEqual(page.forms[0]['method'], 'get')
        self.assertEqual(page.forms[0]['action'], '/explore')
        self.assertEqual(page.active, ['/'])
        standalone = document('Export', '', standalone=True)
        self.assertNotIn('class="global-search"', standalone)

    def test_screener_shows_existing_metrics(self):
        body = explore_html(ui_report(), {})
        for label in ('Relative volume','Ann. volatility','Vs 50-session mean'):
            self.assertIn(label,body)
