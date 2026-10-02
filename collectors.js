/* ============================================================
   ClawHub — Integration Collectors
   ----------------------------------------
   Liefert die Daten fuer zwei neue Dashboard-Module:
     * /api/services   — Service-Registry + Live-Container-Status
     * /api/workstream — Gitea (Ops) + GitHub (Code) aggregiert

   Design:
     - Keine externen npm-Pakete (nur node core: https/fs/path).
     - In-Memory-Cache (30s), damit jeder Seitenaufruf nicht
       jedes Mal gegen Gitea/GitHub laeuft.
     - Fehlertolerant: ein toter Collector liefert einen
       Teil-Fehler statt 500 fuer die ganze Seite.
   ============================================================ */
'use strict';

const https = require('https');
const fs = require('fs');
const path = require('path');

const DASHBOARD_DIR = path.join(__dirname, 'dashboard');
const DATA_DIR = path.join(DASHBOARD_DIR, 'data');
const WORKSPACE_DIR = '/data/.openclaw/workspace';

// --- Integration Config (Secrets NICHT hier hardcoden) ---
const GITEA_BASE = process.env.GITEA_BASE || 'https://issues.clawhub.cabbagebaggage.net';
const GITEA_REPO = process.env.GITEA_REPO || 'linus/maintenance';
const GITEA_TOKEN = (() => {
    const candidates = [
        process.env.GITEA_TOKEN_FILE,
        path.join(__dirname, '.gitea_token'),
        path.join(WORKSPACE_DIR, 'infra', 'gitea', '.token'),
    ].filter(Boolean);
    for (const p of candidates) {
        try { const t = fs.readFileSync(p, 'utf8').trim(); if (t) return t; } catch (e) { /* ignore */ }
    }
    return process.env.GITEA_TOKEN || '';
})();

const GITHUB_REPOS = (process.env.GITHUB_REPOS || 'TheCabbageBaggage/clawhub-dashboard').split(',').map(s => s.trim()).filter(Boolean);

// --- Cache ---
const CACHE_TTL = 30 * 1000;
const cache = {};

function cached(key, fn) {
    const hit = cache[key];
    if (hit && Date.now() - hit.at < CACHE_TTL) return Promise.resolve(hit.val);
    return Promise.resolve(fn()).then(val => { cache[key] = { at: Date.now(), val }; return val; });
}

// --- Minimal HTTPS JSON GET ---
function httpsGet(urlStr, headers = {}, timeoutMs = 8000) {
    return new Promise((resolve, reject) => {
        const u = new URL(urlStr);
        const lib = u.protocol === 'http:' ? require('http') : require('https');
        const req = lib.request(u, { method: 'GET', headers: { 'User-Agent': 'ClawHub-Dashboard', ...headers } }, (res) => {
            let data = '';
            res.on('data', c => data += c);
            res.on('end', () => {
                let body = null;
                try { body = JSON.parse(data); } catch (e) { body = data; }
                if (res.statusCode >= 200 && res.statusCode < 300) resolve(body);
                else reject(new Error('HTTP ' + res.statusCode + ' ' + urlStr));
            });
        });
        req.setTimeout(timeoutMs, () => { req.destroy(new Error('timeout')); });
        req.on('error', reject);
        req.end();
    });
}

function readJson(p, fallback) {
    try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch (e) { return fallback; }
}

// ============================================================
//  SERVICE REGISTRY
// ============================================================
function loadRegistry() {
    // Statische Registry (gepflegt in dashboard/data/services.json)
    const reg = readJson(path.join(DATA_DIR, 'services.json'), null);
    if (reg && Array.isArray(reg.services)) return reg.services;
    return [];
}

function containerStateMap() {
    // Wird vom Host-Cron (alle 15 min) nach dashboard/data/containers.json geschrieben.
    const list = readJson(path.join(DATA_DIR, 'containers.json'), []);
    const map = {};
    if (Array.isArray(list)) for (const c of list) map[c.name] = c;
    return map;
}

async function getServices() {
    return cached('services', async () => {
        const services = loadRegistry();
        const containers = containerStateMap();
        const enriched = services.map(s => {
            const conts = (s.containers || []).map(name => {
                const c = containers[name];
                return { name, state: c ? c.state : 'unknown', status: c ? c.status : 'nicht gemeldet' };
            });
            const known = conts.filter(c => c.state !== 'unknown');
            const running = known.filter(c => c.state === 'running').length;
            let status = 'unknown';
            if (known.length === 0) status = 'external';   // z.B. Cloudflare Worker (kein Container)
            else if (running === known.length) status = 'green';
            else if (running === 0) status = 'red';
            else status = 'yellow';
            return {
                name: s.name,
                group: s.group || 'Weitere',
                tier: s.tier || null,
                url: s.url || null,
                description: s.description || '',
                owner: s.owner || 'Clowie',
                external: !!s.external,
                containers: conts,
                state: status,
            };
        });

        const pub = enriched.filter(s => s.url);
        const summary = {
            total: enriched.length,
            running: enriched.filter(s => s.state === 'green').length,
            degraded: enriched.filter(s => s.state === 'yellow').length,
            down: enriched.filter(s => s.state === 'red').length,
            external: enriched.filter(s => s.state === 'external').length,
            unknown: enriched.filter(s => s.state === 'unknown').length,
            public_endpoints: pub.length,
            t1: enriched.filter(s => s.tier === 'T1').length,
            t2: enriched.filter(s => s.tier === 'T2').length,
        };
        return { timestamp: new Date().toISOString(), summary, services: enriched };
    });
}

// ============================================================
//  WORKSTREAM — Gitea (Ops) + GitHub (Code)
// ============================================================
function prioRank(name) {
    const m = /(P[1-4])/i.exec(name || '');
    return m ? m[1].toUpperCase() : null;
}

async function giteaCollector() {
    if (!GITEA_TOKEN) return { ok: false, error: 'kein Gitea-Token konfiguriert' };
    const h = { Authorization: 'token ' + GITEA_TOKEN };
    const repoPath = GITEA_REPO.split('/').map(encodeURIComponent).join('/');
    const [open, closed, repos] = await Promise.all([
        httpsGet(`${GITEA_BASE}/api/v1/repos/${repoPath}/issues?state=open&limit=100`, h),
        httpsGet(`${GITEA_BASE}/api/v1/repos/${repoPath}/issues?state=closed&limit=1`, h),
        httpsGet(`${GITEA_BASE}/api/v1/repos/${repoPath}`, h),
    ]);
    const issues = Array.isArray(open) ? open : [];
    const byPrio = { P1: 0, P2: 0, P3: 0, P4: 0 };
    const recent = issues
        .sort((a, b) => new Date(b.updated_at || b.created_at) - new Date(a.updated_at || a.created_at))
        .slice(0, 15)
        .map(i => {
            const pr = prioRank((i.labels || []).map(l => l.name).join(' '));
            if (pr && byPrio[pr] !== undefined) byPrio[pr]++;
            return {
                number: i.number,
                title: i.title,
                priority: pr,
                labels: (i.labels || []).map(l => l.name),
                state: i.state,
                url: i.html_url,
                updated_at: i.updated_at,
                created_at: i.created_at,
            };
        });
    let repoUrl = GITEA_BASE + '/' + GITEA_REPO;
    if (repos && repos.html_url) repoUrl = repos.html_url;
    return {
        ok: true,
        base: GITEA_BASE,
        repo: GITEA_REPO,
        repo_url: repoUrl,
        open: issues.length,
        closed: Array.isArray(closed) ? closed.length : null,
        by_priority: byPrio,
        recent,
    };
}

async function githubCollector() {
    const out = { ok: true, repos: [] };
    for (const full of GITHUB_REPOS) {
        try {
            const h = { Accept: 'application/vnd.github+json' };
            const [repo, commits, issues] = await Promise.all([
                httpsGet(`https://api.github.com/repos/${full}`, h),
                httpsGet(`https://api.github.com/repos/${full}/commits?per_page=5`, h),
                httpsGet(`https://api.github.com/repos/${full}/issues?state=open&per_page=1`, h),
            ]);
            const cs = Array.isArray(commits) ? commits.map(c => ({
                sha: (c.sha || '').slice(0, 7),
                message: (c.commit && c.commit.message ? c.commit.message.split('\n')[0] : ''),
                author: (c.commit && c.commit.author ? c.commit.author.name : ''),
                date: c.commit && c.commit.author ? c.commit.author.date : null,
                url: c.html_url,
            })) : [];
            out.repos.push({
                full_name: repo.full_name,
                url: repo.html_url,
                private: repo.private,
                default_branch: repo.default_branch,
                pushed_at: repo.pushed_at,
                open_issues: repo.open_issues_count,
                commits: cs,
            });
        } catch (e) {
            out.repos.push({ full_name: full, error: e.message });
        }
    }
    return out;
}

async function getWorkstream() {
    return cached('workstream', async () => {
        const [gitea, github] = await Promise.all([
            giteaCollector().catch(e => ({ ok: false, error: e.message })),
            githubCollector().catch(e => ({ ok: false, error: e.message })),
        ]);
        return { timestamp: new Date().toISOString(), gitea, github };
    });
}

module.exports = { getServices, getWorkstream };
