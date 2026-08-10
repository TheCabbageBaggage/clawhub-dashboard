const http = require('http');
const fs = require('fs');
const path = require('path');
const url = require('url');
const crypto = require('crypto');
const bcrypt = require('bcryptjs');
const { OAuth2Client } = require('google-auth-library');
const Database = require('better-sqlite3');

const PORT = process.env.PORT || 3001;
const DASHBOARD_DIR = path.join(__dirname, 'dashboard');
const WORKSPACE_DIR = '/data/.openclaw/workspace';
const DATA_DIR = '/app/data';
const TASK_DB_PATH = process.env.TASK_DB_PATH || '/app/data/tasks.db';

// === CONFIG ===
const USERS_PATH = path.join(DATA_DIR, 'users.json');
const SESSION_DURATION = 12 * 60 * 60 * 1000;
const BCRYPT_ROUNDS = 12;
const MAX_LOGIN_ATTEMPTS = 5;
const LOGIN_WINDOW_MS = 15 * 60 * 1000;
const RATE_LIMIT_WINDOW = 60 * 1000;
const RATE_LIMIT_MAX = 100;

// Google OAuth config
const GOOGLE_CLIENT_ID = process.env.GOOGLE_CLIENT_ID || '346557089211-umshm9dqdub0bgq9p8nd4hlj5vghng76.apps.googleusercontent.com';
const ALLOWED_GOOGLE_DOMAINS = (process.env.ALLOWED_GOOGLE_DOMAINS || 'gmail.com').split(',').map(d => d.trim());
const googleClient = new OAuth2Client(GOOGLE_CLIENT_ID);

// === SQLITE TASK DB ===
let taskDb = null;
function getTaskDb() {
    if (taskDb) return taskDb;
    try {
        taskDb = new Database(TASK_DB_PATH, { readonly: true });
        taskDb.pragma('journal_mode = WAL');
        console.log(`Task DB opened: ${TASK_DB_PATH}`);
    } catch (e) {
        console.error('Task DB not available:', e.message);
    }
    return taskDb;
}

// === RATE LIMITING ===
const rateLimitMap = new Map();
function rateLimit(ip) {
    const now = Date.now();
    const entry = rateLimitMap.get(ip) || { count: 0, reset: now + RATE_LIMIT_WINDOW };
    if (now > entry.reset) { entry.count = 1; entry.reset = now + RATE_LIMIT_WINDOW; }
    else { entry.count++; }
    rateLimitMap.set(ip, entry);
    return entry.count <= RATE_LIMIT_MAX;
}
setInterval(() => {
    const now = Date.now();
    for (const [ip, entry] of rateLimitMap) if (now > entry.reset) rateLimitMap.delete(ip);
}, 5 * 60 * 1000);

// === LOGIN ATTEMPT TRACKING ===
const loginAttempts = new Map();
function checkLoginAttempts(ip) {
    const now = Date.now();
    const entry = loginAttempts.get(ip) || { count: 0, firstAttempt: now };
    if (now - entry.firstAttempt > LOGIN_WINDOW_MS) { entry.count = 1; entry.firstAttempt = now; }
    else { entry.count++; }
    loginAttempts.set(ip, entry);
    if (entry.count > MAX_LOGIN_ATTEMPTS) return { blocked: true, retryAfter: Math.ceil((entry.firstAttempt + LOGIN_WINDOW_MS - now) / 1000) };
    return { blocked: false };
}
function resetLoginAttempts(ip) { loginAttempts.delete(ip); }

// === USER MANAGEMENT ===
let users = {};
function loadUsers() {
    try {
        if (fs.existsSync(USERS_PATH)) { users = JSON.parse(fs.readFileSync(USERS_PATH, 'utf-8')); }
        else {
            const defaultPassword = process.env.ADMIN_PASSWORD || crypto.randomBytes(16).toString('hex');
            const hash = bcrypt.hashSync(defaultPassword, BCRYPT_ROUNDS);
            users = { admin: { username: 'admin', passwordHash: hash, role: 'admin', created: new Date().toISOString() } };
            fs.writeFileSync(USERS_PATH, JSON.stringify(users, null, 2));
            console.log(`Default admin created. Password: ${defaultPassword}`);
        }
        console.log(`Loaded ${Object.keys(users).length} user(s)`);
    } catch (e) { console.error('Failed to load users:', e.message); process.exit(1); }
}
function saveUsers() { try { fs.writeFileSync(USERS_PATH, JSON.stringify(users, null, 2)); } catch (e) { console.error('Save users:', e.message); } }
loadUsers();

// === SESSION MANAGEMENT ===
const sessions = new Map();
function generateSession() { return crypto.randomBytes(48).toString('base64url'); }
function createSession(username) {
    const token = generateSession();
    sessions.set(token, { username, created: Date.now(), expires: Date.now() + SESSION_DURATION });
    return token;
}
function validateSession(token) {
    if (!token || !sessions.has(token)) return null;
    const session = sessions.get(token);
    if (Date.now() > session.expires) { sessions.delete(token); return null; }
    return session;
}
setInterval(() => {
    const now = Date.now();
    for (const [token, session] of sessions) if (now > session.expires) sessions.delete(token);
}, 30 * 60 * 1000);

// === AUTH MIDDLEWARE ===
function getClientIP(req) {
    const forwarded = req.headers['x-forwarded-for'];
    if (forwarded) return forwarded.split(',')[0].trim();
    return req.socket.remoteAddress || '127.0.0.1';
}
function extractToken(req) {
    const parsed = url.parse(req.url, true);
    if (parsed.query.token) return parsed.query.token;
    const cookieHeader = req.headers.cookie || '';
    const match = cookieHeader.split(';').find(c => c.trim().startsWith('clawhub_session='));
    if (match) return match.split('=')[1].trim();
    const authHeader = req.headers.authorization || '';
    if (authHeader.startsWith('Bearer ')) return authHeader.slice(7);
    return null;
}
function requireAuth(req, res) {
    const token = extractToken(req);
    const session = validateSession(token);
    if (!session) {
        const parsed = url.parse(req.url, true);
        if (parsed.pathname.startsWith('/api/')) {
            res.writeHead(401, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ error: 'Unauthorized', code: 'AUTH_REQUIRED' }));
            return null;
        }
        res.writeHead(302, { 'Location': '/login' });
        res.end();
        return null;
    }
    return session;
}

// === MIME TYPES ===
const MIME_TYPES = {
    '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8', '.json': 'application/json',
    '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.gif': 'image/gif', '.svg': 'image/svg+xml', '.ico': 'image/x-icon',
    '.md': 'text/markdown; charset=utf-8', '.pdf': 'application/pdf',
    '.woff2': 'font/woff2', '.woff': 'font/woff'
};

// === SECURITY HEADERS ===
const SECURITY_HEADERS = {
    'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
    'X-XSS-Protection': '1; mode=block', 'Referrer-Policy': 'strict-origin-when-cross-origin',
    'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
    'Strict-Transport-Security': 'max-age=31536000; includeSubDomains'
};
function setSecurityHeaders(res) { for (const [k, v] of Object.entries(SECURITY_HEADERS)) res.setHeader(k, v); }

// === STATIC FILE SERVING ===
function serveFile(filePath, res, statusCode = 200) {
    const ext = path.extname(filePath).toLowerCase();
    const contentType = MIME_TYPES[ext] || 'application/octet-stream';
    fs.readFile(filePath, (err, content) => {
        if (err) { res.writeHead(500); res.end('Internal Server Error'); return; }
        setSecurityHeaders(res);
        res.writeHead(statusCode, { 'Content-Type': contentType });
        res.end(content);
    });
}

// === JSON RESPONSE HELPERS ===
function jsonResponse(res, statusCode, data) {
    setSecurityHeaders(res);
    res.writeHead(statusCode, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(data));
}

// === REQUEST BODY PARSER ===
function parseBody(req) {
    return new Promise((resolve, reject) => {
        let body = '';
        req.on('data', chunk => { body += chunk; if (body.length > 1024 * 1024) reject(new Error('Body too large')); });
        req.on('end', () => { try { resolve(body ? JSON.parse(body) : {}); } catch (e) { reject(new Error('Invalid JSON')); } });
    });
}

// === GOOGLE OAUTH ===
async function verifyGoogleToken(idToken) {
    try {
        const ticket = await googleClient.verifyIdToken({ idToken, audience: GOOGLE_CLIENT_ID });
        const payload = ticket.getPayload();
        if (!payload.email_verified) return { error: 'Google email not verified' };
        const domain = payload.email.split('@')[1];
        if (ALLOWED_GOOGLE_DOMAINS.length > 0 && !ALLOWED_GOOGLE_DOMAINS.includes('*') && !ALLOWED_GOOGLE_DOMAINS.includes(domain))
            return { error: `Google domain @${domain} not allowed` };
        return { email: payload.email, name: payload.name || payload.email.split('@')[0], picture: payload.picture, googleId: payload.sub };
    } catch (e) { console.error('Google verify:', e.message); return { error: 'Invalid Google token' }; }
}

// === TASK API HELPERS ===
function getTaskSummary() {
    const db = getTaskDb();
    if (!db) return null;
    try {
        const statusRows = db.prepare(`
            SELECT status, category, count(*) as cnt
            FROM tasks GROUP BY status, category ORDER BY category, status
        `).all();
        const total = db.prepare("SELECT count(*) as cnt FROM tasks").get();
        const pending = db.prepare("SELECT count(*) as cnt FROM tasks WHERE status = 'pending'").get();
        const active = db.prepare("SELECT count(*) as cnt FROM tasks WHERE status = 'in_progress'").get();
        const done = db.prepare("SELECT count(*) as cnt FROM tasks WHERE status = 'done'").get();
        const blocked = db.prepare("SELECT count(*) as cnt FROM tasks WHERE status = 'blocked'").get();
        return { statusRows, total: total.cnt, pending: pending.cnt, active: active.cnt, done: done.cnt, blocked: blocked.cnt };
    } catch (e) { console.error('Task summary:', e.message); return null; }
}

function getTaskStats() {
    const db = getTaskDb();
    if (!db) return null;
    try {
        const stats = db.prepare(`
            SELECT COUNT(*) as total_runs,
                   SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successful,
                   SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                   COALESCE(SUM(tokens_in), 0) as total_tokens_in,
                   COALESCE(SUM(tokens_out), 0) as total_tokens_out,
                   COALESCE(SUM(cost_eur), 0) as total_cost
            FROM task_runs
        `).get();
        const byModel = db.prepare(`
            SELECT model, COUNT(*) as runs, COALESCE(SUM(tokens_in),0) as tin,
                   COALESCE(SUM(tokens_out),0) as tout, COALESCE(SUM(cost_eur),0) as cost
            FROM task_runs WHERE model IS NOT NULL
            GROUP BY model ORDER BY SUM(cost_eur) DESC
        `).all();
        return { ...stats, byModel };
    } catch (e) { console.error('Task stats:', e.message); return null; }
}

function getTasksByWeek() {
    const db = getTaskDb();
    if (!db) return [];
    try {
        return db.prepare(`
            SELECT id, title, status, category, priority, week, planned_date,
                   started_at, completed_at, estimated_minutes
            FROM tasks ORDER BY week, category, priority
        `).all();
    } catch (e) { console.error('Tasks by week:', e.message); return []; }
}

function getRecentRuns(limit = 10) {
    const db = getTaskDb();
    if (!db) return [];
    try {
        return db.prepare(`
            SELECT r.id, r.task_id, r.model, r.status, r.tokens_in, r.tokens_out,
                   r.cost_eur, r.started_at, r.completed_at, r.output_summary, r.error_message,
                   t.title as task_title, t.category
            FROM task_runs r JOIN tasks t ON r.task_id = t.id
            ORDER BY r.started_at DESC LIMIT ?
        `).all(limit);
    } catch (e) { console.error('Recent runs:', e.message); return []; }
}

// === SERVER ===
const server = http.createServer(async (req, res) => {
    const ip = getClientIP(req);
    const parsedUrl = url.parse(req.url, true);
    const pathname = parsedUrl.pathname;

    if (!rateLimit(ip)) { jsonResponse(res, 429, { error: 'Too many requests', retryAfter: 60 }); return; }
    console.log(`${new Date().toISOString()} [${ip}] ${req.method} ${pathname}`);

    try {
        // === PUBLIC ROUTES ===
        if (pathname === '/login' && req.method === 'GET') { serveFile(path.join(__dirname, 'login.html'), res); return; }

        // Google OAuth login
        if (pathname === '/api/auth/google' && req.method === 'POST') {
            const attemptCheck = checkLoginAttempts(ip);
            if (attemptCheck.blocked) { jsonResponse(res, 429, { error: 'Too many login attempts', retryAfter: attemptCheck.retryAfter }); return; }
            let body; try { body = await parseBody(req); } catch (e) { jsonResponse(res, 400, { error: 'Invalid request body' }); return; }
            const { credential } = body;
            if (!credential) { jsonResponse(res, 400, { error: 'Google credential required' }); return; }
            const googleUser = await verifyGoogleToken(credential);
            if (googleUser.error) { jsonResponse(res, 401, { error: googleUser.error }); return; }
            const userKey = `google:${googleUser.email}`;
            let user = users[userKey];
            if (!user) {
                user = { username: googleUser.email, googleEmail: googleUser.email, googleId: googleUser.googleId, displayName: googleUser.name, picture: googleUser.picture, role: 'user', created: new Date().toISOString(), authProvider: 'google' };
                users[userKey] = user; saveUsers();
                console.log(`Google user auto-created: ${googleUser.email}`);
            }
            user.lastLogin = new Date().toISOString(); saveUsers();
            resetLoginAttempts(ip);
            const token = createSession(user.username);
            setSecurityHeaders(res);
            res.writeHead(200, { 'Content-Type': 'application/json', 'Set-Cookie': `clawhub_session=${token}; HttpOnly; SameSite=Strict; Max-Age=43200; Path=/; Secure` });
            res.end(JSON.stringify({ success: true, username: user.username, role: user.role, displayName: user.displayName, picture: user.picture }));
            return;
        }

        // Password login
        if (pathname === '/api/login' && req.method === 'POST') {
            const attemptCheck = checkLoginAttempts(ip);
            if (attemptCheck.blocked) { jsonResponse(res, 429, { error: 'Too many login attempts', retryAfter: attemptCheck.retryAfter }); return; }
            let body; try { body = await parseBody(req); } catch (e) { jsonResponse(res, 400, { error: 'Invalid request body' }); return; }
            const { username, password } = body;
            if (!username || !password) { jsonResponse(res, 400, { error: 'Username and password required' }); return; }
            const userKey = username.toLowerCase();
            const user = users[userKey];
            if (!user || !user.passwordHash || !bcrypt.compareSync(password, user.passwordHash)) { jsonResponse(res, 401, { error: 'Invalid credentials' }); return; }
            user.lastLogin = new Date().toISOString(); saveUsers();
            resetLoginAttempts(ip);
            const token = createSession(user.username);
            setSecurityHeaders(res);
            res.writeHead(200, { 'Content-Type': 'application/json', 'Set-Cookie': `clawhub_session=${token}; HttpOnly; SameSite=Strict; Max-Age=43200; Path=/; Secure` });
            res.end(JSON.stringify({ success: true, username: user.username, role: user.role, displayName: user.displayName || user.username, picture: user.picture }));
            return;
        }

        // Logout
        if (pathname === '/api/logout' && req.method === 'POST') {
            const token = extractToken(req); if (token) sessions.delete(token);
            setSecurityHeaders(res);
            res.writeHead(200, { 'Content-Type': 'application/json', 'Set-Cookie': 'clawhub_session=; HttpOnly; SameSite=Strict; Max-Age=0; Path=/; Secure' });
            res.end(JSON.stringify({ success: true }));
            return;
        }

        // Auth status
        if (pathname === '/api/auth-status') {
            const token = extractToken(req); const session = validateSession(token);
            if (session) {
                const userKey = session.username.toLowerCase(); const user = users[userKey];
                jsonResponse(res, 200, { authenticated: true, username: session.username, role: user ? user.role : 'user', displayName: user ? user.displayName : null, picture: user ? user.picture : null, authProvider: user ? user.authProvider : 'password' });
            } else { jsonResponse(res, 200, { authenticated: false }); }
            return;
        }

        // Google client ID
        if (pathname === '/api/auth/google-config') { jsonResponse(res, 200, { clientId: GOOGLE_CLIENT_ID }); return; }

        // === AUTH REQUIRED ===
        const session = requireAuth(req, res);
        if (!session) return;
        const userKey = session.username.toLowerCase();
        const currentUser = users[userKey];
        const isAdmin = currentUser && currentUser.role === 'admin';

        // === TASK API ENDPOINTS ===
        if (pathname === '/api/tasks/summary') {
            const summary = getTaskSummary();
            if (!summary) { jsonResponse(res, 503, { error: 'Task database not available' }); return; }
            jsonResponse(res, 200, summary);
            return;
        }
        if (pathname === '/api/tasks/stats') {
            const stats = getTaskStats();
            if (!stats) { jsonResponse(res, 503, { error: 'Task database not available' }); return; }
            jsonResponse(res, 200, stats);
            return;
        }
        if (pathname === '/api/tasks') {
            const tasks = getTasksByWeek();
            jsonResponse(res, 200, tasks);
            return;
        }
        if (pathname === '/api/tasks/runs') {
            const runs = getRecentRuns(20);
            jsonResponse(res, 200, runs);
            return;
        }

        // User management (admin only)
        if (pathname === '/api/users' && req.method === 'GET') {
            if (!isAdmin) { jsonResponse(res, 403, { error: 'Admin access required' }); return; }
            const userList = Object.values(users).map(u => ({ username: u.username, role: u.role, created: u.created, lastLogin: u.lastLogin || null, authProvider: u.authProvider || 'password', displayName: u.displayName || null }));
            jsonResponse(res, 200, userList);
            return;
        }
        if (pathname === '/api/users' && req.method === 'POST') {
            if (!isAdmin) { jsonResponse(res, 403, { error: 'Admin access required' }); return; }
            let body; try { body = await parseBody(req); } catch (e) { jsonResponse(res, 400, { error: 'Invalid request body' }); return; }
            const { username, password, role } = body;
            if (!username || !password) { jsonResponse(res, 400, { error: 'Username and password required' }); return; }
            if (!/^[a-zA-Z0-9._@+-]{2,64}$/.test(username)) { jsonResponse(res, 400, { error: 'Invalid username format' }); return; }
            if (password.length < 8) { jsonResponse(res, 400, { error: 'Password must be at least 8 characters' }); return; }
            const key = username.toLowerCase();
            if (users[key]) { jsonResponse(res, 409, { error: 'User already exists' }); return; }
            users[key] = { username, passwordHash: bcrypt.hashSync(password, BCRYPT_ROUNDS), role: role === 'admin' ? 'admin' : 'user', created: new Date().toISOString(), authProvider: 'password' };
            saveUsers();
            jsonResponse(res, 201, { username, role: users[key].role, created: users[key].created });
            return;
        }
        if (pathname.startsWith('/api/users/') && req.method === 'DELETE') {
            if (!isAdmin) { jsonResponse(res, 403, { error: 'Admin access required' }); return; }
            const targetUser = decodeURIComponent(pathname.replace('/api/users/', ''));
            const key = targetUser.toLowerCase();
            if (key === 'admin') { jsonResponse(res, 400, { error: 'Cannot delete admin' }); return; }
            if (!users[key]) { jsonResponse(res, 404, { error: 'User not found' }); return; }
            const deleted = users[key]; delete users[key]; saveUsers();
            for (const [t, s] of sessions) { if (s.username.toLowerCase() === key) sessions.delete(t); }
            jsonResponse(res, 200, { success: true, username: deleted.username });
            return;
        }
        if (pathname.startsWith('/api/users/') && pathname.endsWith('/password') && req.method === 'PUT') {
            const targetUser = decodeURIComponent(pathname.replace('/api/users/', '').replace('/password', ''));
            const key = targetUser.toLowerCase();
            if (key !== userKey && !isAdmin) { jsonResponse(res, 403, { error: 'Can only change your own password' }); return; }
            if (!users[key]) { jsonResponse(res, 404, { error: 'User not found' }); return; }
            if (users[key].authProvider === 'google') { jsonResponse(res, 400, { error: 'Google users cannot set a password' }); return; }
            let body; try { body = await parseBody(req); } catch (e) { jsonResponse(res, 400, { error: 'Invalid request body' }); return; }
            const { currentPassword, newPassword } = body;
            if (key === userKey && !isAdmin) { if (!currentPassword || !bcrypt.compareSync(currentPassword, users[key].passwordHash)) { jsonResponse(res, 401, { error: 'Current password incorrect' }); return; } }
            if (!newPassword || newPassword.length < 8) { jsonResponse(res, 400, { error: 'New password must be at least 8 characters' }); return; }
            users[key].passwordHash = bcrypt.hashSync(newPassword, BCRYPT_ROUNDS); saveUsers();
            for (const [t, s] of sessions) { if (s.username.toLowerCase() === key) sessions.delete(t); }
            jsonResponse(res, 200, { success: true });
            return;
        }

        // Dashboard data
        if (pathname === '/api/data') {
            jsonResponse(res, 200, { system: { status: 'healthy' }, metrics: { total_newsletters: 42, total_articles: 580, total_sources: 14, last_generation: new Date().toISOString(), success_rate: 95.5 }, articles: [], sources: [], topics: [], timeline: [], knowledge_graph: { nodes: [], links: [] } });
            return;
        }

        // Research catalog
        if (pathname === '/api/research') {
            const catalogPath = path.join(DASHBOARD_DIR, 'data', 'research_catalog.json');
            fs.readFile(catalogPath, (err, content) => {
                if (err) { jsonResponse(res, 500, { error: 'Catalog not found' }); }
                else { setSecurityHeaders(res); res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(content); }
            });
            return;
        }

        // Research file
        if (pathname.startsWith('/api/research/')) {
            const filePath = decodeURIComponent(pathname.replace('/api/research/', ''));
            const normalized = path.normalize(filePath).replace(/^(\.\.(\/|\\|$))+/, '');
            const fullPath = path.join(WORKSPACE_DIR, normalized);
            if (!fullPath.startsWith(WORKSPACE_DIR)) { jsonResponse(res, 403, { error: 'Forbidden' }); return; }
            fs.stat(fullPath, (err, stats) => {
                if (err || !stats.isFile()) { jsonResponse(res, 404, { error: 'File not found' }); return; }
                const ext = path.extname(fullPath).toLowerCase();
                const contentType = MIME_TYPES[ext] || 'text/plain; charset=utf-8';
                setSecurityHeaders(res); res.writeHead(200, { 'Content-Type': contentType });
                fs.createReadStream(fullPath).pipe(res);
            });
            return;
        }

        // Static files (protected)
        let filePath = path.join(DASHBOARD_DIR, pathname);
        if (pathname === '/') filePath = path.join(DASHBOARD_DIR, 'index.html');
        const resolvedPath = path.resolve(filePath);
        if (!resolvedPath.startsWith(DASHBOARD_DIR)) { jsonResponse(res, 403, { error: 'Forbidden' }); return; }
        fs.stat(filePath, (err, stats) => {
            if (err || !stats.isFile()) {
                if (!pathname.includes('.')) {
                    const htmlPath = filePath + '.html';
                    fs.stat(htmlPath, (err2, stats2) => { if (err2 || !stats2.isFile()) { jsonResponse(res, 404, { error: 'Not found' }); } else { serveFile(htmlPath, res); } });
                } else { jsonResponse(res, 404, { error: 'Not found' }); }
            } else { serveFile(filePath, res); }
        });

    } catch (e) { console.error(`Error ${pathname}:`, e.message); jsonResponse(res, 500, { error: 'Internal server error' }); }
});

server.listen(PORT, () => {
    console.log(`🔒 ClawHub Dashboard on port ${PORT}`);
    console.log(`   Auth: bcrypt + Google OAuth + sessions + rate limiting`);
    console.log(`   Users: ${Object.keys(users).length} configured`);
    console.log(`   Google OAuth: ${GOOGLE_CLIENT_ID ? 'enabled' : 'disabled'}`);
    console.log(`   Task DB: ${TASK_DB_PATH}`);
});

process.on('SIGINT', () => { server.close(() => process.exit(0)); });
process.on('SIGTERM', () => { server.close(() => process.exit(0)); });
