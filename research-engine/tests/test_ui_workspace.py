"""Workspace navigation, evidence cutoff and disclosure regression checks."""
import unittest
from test_dashboard_ui import ui_report, Page
from oraculum.ui import document, research_tabs
from oraculum.dashboard_view import today_html, stock_html


class WorkspaceTests(unittest.TestCase):
    def test_research_navigation_preserves_cutoff(self):
        ident = 'a' * 64
        body = research_tabs('news', ident)
        self.assertIn('/research?report=' + ident, body)
        self.assertIn('/news?report=' + ident, body)
        self.assertEqual(Page(document('Research', body, active='news')).active,
                         ['/research', '/news?report=' + ident])

    def test_routine_coverage_is_collapsed_and_shortlist_first(self):
        body = today_html(ui_report())
        self.assertIn('<details class="status-panel"><summary>Coverage', body)
        self.assertLess(body.index('id="shortlist-heading"'), body.index('<summary>Coverage'))
        self.assertIn('Coverage / details', body)

    def test_stock_review_has_distinct_evidence_and_risk_columns(self):
        report = ui_report()
        body = stock_html(report, report['assets'][0])
        self.assertIn('class="stock-main"', body)
        self.assertIn('class="stock-aside"', body)
        self.assertIn('What needs attention?', body)
        self.assertIn('Score breakdown', body)
        self.assertNotIn('<script', body)
