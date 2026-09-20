#!/usr/bin/env python3
"""
dashboard-smoke.py — Layout-Smoke-Test für das ClawHub-Redesign.

Rendert jede Redesign-Seite in echtem Chromium bei mehreren Viewport-Breiten
und prüft auf die Fehlerklassen, die in der Vergangenheit aufgetreten sind:

  1. Horizontales Overflow (scrollWidth > viewport + Toleranz)
  2. Fehlende Sidebar (Shell-Injection 404 / Pfadfehler)
  3. Leere Kern-Inhalte ("Lade…"-Spinner bleibt stehen, KPI-Werte = "—")
  4. Chart-Canvas ohne Box (Endlos-Wachstum) bzw. Canvas-Höhe > Box
  5. NaN / undefined im sichtbaren Text
  6. JS-Console-Errors

Exit 0 = alles ok, Exit 2 = Befunde (blockierend).

Aufruf:
  python3 dashboard-smoke.py [--root DIR] [--data DIR]
                             [--pages a.html,b.html] [--widths 1366,1920]
                             [--json OUT]
"""
import argparse
import http.server
import json
import os
import socketserver
import sys
import threading

DEF_ROOT = '/data/.openclaw/workspace/clawhub-dashboard/dashboard/redesign'
DEF_DATA = '/tmp/proddata'
DEF_WIDTHS = [375, 768, 1024, 1366, 1440, 1920]
DEF_PAGES = [
    'index.html', 'dashboard.html', 'plan.html', 'finanz.html', 'bi.html',
    'knowledge.html', 'graph.html', 'medium.html', 'research.html',
    'influencer.html', 'ssh.html', 'status.html', 'learnings.html',
]

API_FILES = {
    '/api/metrics/ollama-usage': 'ollama-usage.json',
    '/api/task-usage': 'task-usage.json',
    '/api/learnings': 'learnings.json',
}

TOLERANCE = 2  # px


def make_handler(root, data):
    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=root, **kw)

        def log_message(self, *a):
            pass

        def do_GET(self):
            p = self.path.split('?')[0]

            if p == '/api/metrics':
                out = {'timestamp': '2026-01-01T00:00:00Z', 'metrics': {}}
                for name in ['ollama-usage', 'system', 'containers', 'security', 'storage']:
                    fp = os.path.join(data, name + '.json')
                    if os.path.exists(fp):
                        try:
                            out['metrics'][name] = json.load(open(fp))
                        except Exception:
                            out['metrics'][name] = {'error': 'parse_error'}
                    else:
                        out['metrics'][name] = {'error': 'not_found'}
                return self._json(out)

            if p == '/api/task-usage':
                fp = os.path.join(data, 'task-usage.json')
                if os.path.exists(fp):
                    return self._raw_json(fp)
                return self._json({'days': 14, 'tasks': [], 'scrum': []})

            if p == '/api/learnings':
                fp = os.path.join(data, 'learnings.json')
                if os.path.exists(fp):
                    return self._raw_json(fp)
                return self._json({'generated_at': '2026-01-01T00:00:00Z',
                                   'summary': {'total_entries': 3, 'open_count': 2,
                                               'sla_breach_count': 1, 'stale_count': 0,
                                               'age_by_priority': {'high': {'p50': 40, 'p90': 167, 'max': 167, 'n': 6}},
                                               'by_priority': {'high': 6, 'medium': 3}, 'by_type': {'insight': 5},
                                               'health': None},
                                   'pipeline': {'pending': 1, 'promoted': 2},
                                   'recurring': [],
                                   'entries': [
                                       {'id': 'LRN-20260406-001', 'type': 'insight', 'priority': 'high',
                                        'status': 'promoted', 'is_closed': True, 'sla_state': 'closed',
                                        'sla_label': 'abgeschlossen', 'age_days': 167,
                                        'summary': 'Smoke-Test-Eintrag', 'tags': ['smoke']},
                                       {'id': 'LRN-20260811-001', 'type': 'pipeline_test', 'priority': 'low',
                                        'status': 'pending', 'is_closed': False, 'sla_state': 'warning',
                                        'sla_label': '5 d übrig', 'age_days': 40,
                                        'summary': 'Smoke-Test-Eintrag offen', 'tags': ['smoke']},
                                   ]})

            if p == '/api/finanz/monthly':
                # Realistische Struktur laut server.js
                return self._json({
                    'monthly': [
                        {'month': '2026-08', 'income': 7096, 'expenses': 4200, 'savings': 2896,
                         'savings_pct': 40.8, 'txn_count': 42},
                        {'month': '2026-09', 'income': 7096, 'expenses': 3900, 'savings': 3196,
                         'savings_pct': 45.0, 'txn_count': 37},
                    ],
                    'categories': [], 'recurring': [],
                    'totals': {'total_income': 77860, 'total_expenses': 49624,
                               'total_savings': 47968, 'avg_savings_pct': 38.0},
                })

            if p == '/api/bi/summary':
                return self._json({
                    'daily': [
                        {'date': '2026-09-14', 'total_input_tokens': 1250000, 'total_output_tokens': 42000,
                         'total_cost': 0.0, 'session_count': 48},
                        {'date': '2026-09-15', 'total_input_tokens': 980000, 'total_output_tokens': 31000,
                         'total_cost': 0.0, 'session_count': 37},
                    ],
                    'modelDaily': [
                        {'model': 'deepseek-v4.1-flash', 'date': '2026-09-15',
                         'input_tokens': 900000, 'output_tokens': 28000, 'total_cost': 0.0, 'usage_count': 620},
                    ],
                    'totals': {'total_input_tokens': 2230000, 'total_output_tokens': 73000,
                               'total_cost': 0.0, 'session_count': 85},
                })

            if p == '/api/epics':
                return self._json([{'id': i} for i in range(7)])
            if p == '/api/stories':
                return self._json([{'id': i} for i in range(22)])
            if p == '/api/tasks':
                return self._json([{'id': i} for i in range(59)])
            if p.startswith('/briefing/data/'):
                fp = os.path.join(os.path.dirname(os.path.dirname(root.rstrip('/'))),
                                  'dashboard', p.lstrip('/'))
                alt = os.path.join(os.path.dirname(root.rstrip('/')), p.lstrip('/'))
                for cand in (fp, alt):
                    if os.path.exists(cand):
                        return self._raw_json(cand)
                return self._json({'nodes': [], 'links': [], 'articles': []})

            if p.startswith('/api/'):
                return self._json([])

            return super().do_GET()

        def _json(self, obj):
            body = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _raw_json(self, fp):
            body = open(fp, 'rb').read()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return H


PROBE = r"""
() => {
  const r = {};
  const de = document.documentElement;
  r.docW = de.scrollWidth;
  r.vw = window.innerWidth;

  // Sidebar
  r.hasSidebar = !!document.querySelector('.acta-sidebar');
  r.hasTopbar  = !!document.querySelector('.acta-topbar');

  // Inhalt
  const content = document.getElementById('content');
  r.contentW = content ? Math.round(content.getBoundingClientRect().width) : 0;
  r.contentH = content ? Math.round(content.getBoundingClientRect().height) : 0;

  // Lade-Spinner noch sichtbar?
  r.stillLoading = !!document.querySelector('.acta-loading');

  // KPI-Werte: sind alle "—"?
  const vals = [...document.querySelectorAll('.acta-metric-value')].map(e => e.textContent.trim());
  r.kpiCount = vals.length;
  r.kpiDash = vals.filter(v => v === '—' || v === '').length;

  // Fehlertext sichtbar?
  const txt = content ? content.innerText : '';
  r.hasError = /Fehler beim Laden|not_found|>undefined<|>NaN<|\bundefined\b|\bNaN\b/.test(txt);

  // Charts: Canvas größer als seine Box? (= Endlos-Wachstum)
  const boxes = [...document.querySelectorAll('.acta-chart-box')];
  r.chartBoxes = boxes.length;
  r.chartOverflow = boxes.filter(b => {
    const c = b.querySelector('canvas');
    if (!c) return false;
    return c.getBoundingClientRect().height > b.getBoundingClientRect().height + 8;
  }).length;

  // Freie Canvas (ohne Box) = Alt-Muster
  r.freeCanvas = [...document.querySelectorAll('canvas')].filter(c => !c.closest('.acta-chart-box')).length;

  // Elemente, die den Viewport rechts/rechts durchbrechen
  const over = [];
  document.querySelectorAll('.acta-content *').forEach(el => {
    const rect = el.getBoundingClientRect();
    if (rect.width > 0 && rect.right > window.innerWidth + 2) {
      if (over.length < 5) over.push((el.className || el.tagName) + ' right=' + Math.round(rect.right));
    }
  });
  r.overflowEls = over;

  return r;
}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=DEF_ROOT)
    ap.add_argument('--data', default=DEF_DATA)
    ap.add_argument('--pages', default=','.join(DEF_PAGES))
    ap.add_argument('--widths', default=','.join(str(w) for w in DEF_WIDTHS))
    ap.add_argument('--json', default=None)
    ap.add_argument('--shots', default=None, help='Verzeichnis für Screenshots')
    args = ap.parse_args()

    pages = [p.strip() for p in args.pages.split(',') if p.strip()]
    widths = [int(w) for w in args.widths.split(',') if w.strip()]
    pages = [p for p in pages if os.path.exists(os.path.join(args.root, p))]

    handler = make_handler(args.root, args.data)
    socketserver.TCPServer.allow_reuse_address = True
    srv = socketserver.TCPServer(('127.0.0.1', 0), handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    from playwright.sync_api import sync_playwright

    findings = []
    results = []
    total = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=['--no-sandbox'])
        for page_name in pages:
            for w in widths:
                total += 1
                page = browser.new_page(viewport={'width': w, 'height': 900})
                errs = []
                page.on('console', lambda m: errs.append(m.text[:200]) if m.type == 'error' else None)
                page.on('pageerror', lambda e: errs.append('pageerror: ' + str(e)[:200]))
                try:
                    page.goto('http://127.0.0.1:%d/%s' % (port, page_name),
                              wait_until='networkidle', timeout=20000)
                    page.wait_for_timeout(900)
                    info = page.evaluate(PROBE)
                except Exception as e:
                    findings.append({'page': page_name, 'width': w, 'check': 'render',
                                     'detail': str(e)[:200]})
                    page.close()
                    continue

                row = {'page': page_name, 'width': w, **info}
                results.append(row)

                # --- Checks ---
                if info['docW'] > info['vw'] + TOLERANCE:
                    findings.append({'page': page_name, 'width': w, 'check': 'h-overflow',
                                     'detail': 'docW=%d vw=%d' % (info['docW'], info['vw']),
                                     'els': info['overflowEls']})
                if not info['hasSidebar']:
                    findings.append({'page': page_name, 'width': w, 'check': 'no-sidebar',
                                     'detail': 'Sidebar fehlt (Shell-Injection kaputt?)'})
                if info['stillLoading']:
                    findings.append({'page': page_name, 'width': w, 'check': 'stuck-loading',
                                     'detail': 'Lade-Spinner noch sichtbar'})
                if info['kpiCount'] > 0 and info['kpiDash'] == info['kpiCount']:
                    findings.append({'page': page_name, 'width': w, 'check': 'empty-kpis',
                                     'detail': 'alle %d KPI-Werte sind "—"' % info['kpiCount']})
                if info['chartOverflow'] > 0:
                    findings.append({'page': page_name, 'width': w, 'check': 'chart-grow',
                                     'detail': '%d Canvas größer als Box' % info['chartOverflow']})
                if info['freeCanvas'] > 0:
                    findings.append({'page': page_name, 'width': w, 'check': 'free-canvas',
                                     'detail': '%d Canvas ohne .acta-chart-box' % info['freeCanvas']})
                if info['hasError']:
                    findings.append({'page': page_name, 'width': w, 'check': 'error-text',
                                     'detail': 'Fehlertext/NaN im Inhalt'})
                if info['contentH'] < 200 and not info['stillLoading']:
                    findings.append({'page': page_name, 'width': w, 'check': 'tiny-content',
                                     'detail': 'Inhalt nur %dpx hoch' % info['contentH']})
                for e in errs[:3]:
                    findings.append({'page': page_name, 'width': w, 'check': 'console-error',
                                     'detail': e})

                if args.shots:
                    os.makedirs(args.shots, exist_ok=True)
                    page.screenshot(path=os.path.join(args.shots, '%s_%d.png' % (page_name.replace('.html', ''), w)))

                page.close()
        browser.close()

    srv.shutdown()

    # --- Report ---
    print('Layout-Smoke-Test — %d Seiten × %d Breiten = %d Renders' % (len(pages), len(widths), total))
    print('=' * 68)
    if not findings:
        print('✅ KEINE BEFUNDE — alle Seiten sauber')
    else:
        by_check = {}
        for f in findings:
            by_check.setdefault(f['check'], []).append(f)
        for check, items in sorted(by_check.items()):
            print('\n❌ %s — %d Befunde' % (check, len(items)))
            seen = set()
            for it in items:
                key = (it['page'], it.get('detail', ''))
                if key in seen:
                    continue
                seen.add(key)
                print('   %-20s @%-5s  %s' % (it['page'], it['width'], it.get('detail', '')))
                if it.get('els'):
                    print('        overflow: %s' % '; '.join(it['els'][:3]))
        print('\nGESAMT: %d Befunde' % len(findings))

    if args.json:
        json.dump({'total': total, 'findings': findings, 'results': results},
                  open(args.json, 'w'), indent=2)
        print('JSON: %s' % args.json)

    return 0 if not findings else 2


if __name__ == '__main__':
    sys.exit(main())
