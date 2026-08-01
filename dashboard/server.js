const http = require('http');
const fs = require('fs');
const path = require('path');
const url = require('url');
const crypto = require('crypto');

const PORT = 8080;
const DASHBOARD_DIR = __dirname;
const WORKSPACE_DIR = '/data/.openclaw/workspace';

// === SECURE AUTH CONFIG ===
// Set via environment variable, fallback to file
const AUTH_CONFIG_PATH = '/app/data/auth.json';
let AUTH_PASSWORD = process.env.DASHBOARD_PASSWORD;

function loadAuthConfig() {
    try {
        if (fs.existsSync(AUTH_CONFIG_PATH)) {
            const config = JSON.parse(fs.readFileSync(AUTH_CONFIG_PATH, 'utf-8'));
            AUTH_PASSWORD = config.password || AUTH_PASSWORD;
        }
    } catch (e) {
        console.error('Auth config load error:', e.message);
    }
}

loadAuthConfig();

// Generate session token
function generateSession() {
    return crypto.randomBytes(32).toString('hex');
}

// Simple in-memory session store
const sessions = new Map();
const SESSION_DURATION = 24 * 60 * 60 * 1000; // 24 hours

// Clean expired sessions periodically
setInterval(() => {
    const now = Date.now();
    for (const [token, expiry] of sessions) {
        if (expiry < now) sessions.delete(token);
    }
}, 60 * 60 * 1000);

function authenticate(req) {
    const parsed = url.parse(req.url, true);
    const token = parsed.query.token || 
                  (req.headers.cookie || '').split('; ')
                    .find(c => c.startsWith('session='))
                    ?.split('=')[1];
    
    if (token && sessions.has(token)) {
        const expiry = sessions.get(token);
        if (expiry > Date.now()) {
            return true;
        }
        sessions.delete(token);
    }
    return false;
}

const server = http.createServer((req, res) => {
    const parsedUrl = url.parse(req.url, true);
    const pathname = parsedUrl.pathname;
    
    console.log(`${new Date().toISOString()} ${req.method} ${pathname}`);
    
    // === LOGIN ENDPOINT ===
    if (pathname === '/api/login' && req.method === 'POST') {
        let body = '';
        req.on('data', chunk => body += chunk);
        req.on('end', () => {
            try {
                const { password } = JSON.parse(body);
                if (password === AUTH_PASSWORD) {
                    const token = generateSession();
                    sessions.set(token, Date.now() + SESSION_DURATION);
                    res.writeHead(200, {
                        'Content-Type': 'application/json',
                        'Set-Cookie': `session=${token}; HttpOnly; SameSite=Strict; Max-Age=86400; Path=/`
                    });
                    res.end(JSON.stringify({ success: true, token }));
                } else {
                    res.writeHead(401, { 'Content-Type': 'application/json' });
                    res.end(JSON.stringify({ success: false, error: 'Invalid password' }));
                }
            } catch (e) {
                res.writeHead(400, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ error: 'Invalid request' }));
            }
        });
        return;
    }
    
    // === LOGOUT ENDPOINT ===
    if (pathname === '/api/logout') {
        const parsed = url.parse(req.url, true);
        const token = parsed.query.token;
        if (token) sessions.delete(token);
        res.writeHead(200, { 
            'Content-Type': 'application/json',
            'Set-Cookie': 'session=; HttpOnly; SameSite=Strict; Max-Age=0; Path=/'
        });
        res.end(JSON.stringify({ success: true }));
        return;
    }
    
    // === CHECK AUTH ENDPOINT ===
    if (pathname === '/api/check-auth') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ authenticated: authenticate(req) }));
        return;
    }
    
    // === PROTECTED API ENDPOINTS ===
    if (pathname.startsWith('/api/')) {
        if (!authenticate(req)) {
            res.writeHead(401, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ error: 'Unauthorized' }));
            return;
        }
    }
    
    // API endpoint - basic data
    if (pathname === '/api/data') {
        res.writeHead(200, {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': 'https://clawhub.cabbagebaggage.net'
        });
        res.end(JSON.stringify({
            system: { status: 'healthy', uptime_days: 60 },
            metrics: {
                total_newsletters: 42,
                total_articles: 580,
                total_sources: 14,
                last_generation: new Date().toISOString(),
                success_rate: 95.5
            },
            articles: [],
            sources: [],
            topics: [],
            timeline: [],
            knowledge_graph: { nodes: [], links: [] }
        }));
        return;
    }
    
    // Research catalog API
    if (pathname === '/api/research') {
        serveResearchCatalog(res);
        return;
    }
    
    // Research file content API
    if (pathname.startsWith('/api/research/')) {
        const filePath = decodeURIComponent(pathname.replace('/api/research/', ''));
        serveResearchFile(filePath, res);
        return;
    }
    
    // Serve static files
    let filePath = path.join(DASHBOARD_DIR, pathname);
    if (pathname === '/') {
        filePath = path.join(DASHBOARD_DIR, 'index.html');
    }
    
    fs.stat(filePath, (err, stats) => {
        if (err || !stats.isFile()) {
            if (!pathname.includes('.')) {
                const htmlPath = filePath + '.html';
                fs.stat(htmlPath, (err2, stats2) => {
                    if (err2 || !stats2.isFile()) {
                        res.writeHead(404, { 'Content-Type': 'text/plain' });
                        res.end('404 Not Found');
                    } else {
                        serveFile(htmlPath, res);
                    }
                });
            } else {
                res.writeHead(404, { 'Content-Type': 'text/plain' });
                res.end('404 Not Found');
            }
        } else {
            serveFile(filePath, res);
        }
    });
});

function serveFile(filePath, res) {
    const ext = path.extname(filePath).toLowerCase();
    const mimeTypes = {
        '.html': 'text/html',
        '.js': 'text/javascript',
        '.css': 'text/css',
        '.json': 'application/json',
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.gif': 'image/gif',
        '.svg': 'image/svg+xml',
        '.ico': 'image/x-icon',
        '.md': 'text/markdown',
        '.tex': 'text/plain',
        '.pdf': 'application/pdf'
    };
    
    const contentType = mimeTypes[ext] || 'application/octet-stream';
    
    fs.readFile(filePath, (err, content) => {
        if (err) {
            res.writeHead(500);
            res.end(`Error loading ${filePath}: ${err.message}`);
        } else {
            res.writeHead(200, { 'Content-Type': contentType });
            res.end(content);
        }
    });
}

function serveResearchCatalog(res) {
    const catalogPath = path.join(DASHBOARD_DIR, 'data', 'research_catalog.json');
    fs.readFile(catalogPath, (err, content) => {
        if (err) {
            res.writeHead(500, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ error: 'Catalog not found' }));
        } else {
            res.writeHead(200, { 
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': 'https://clawhub.cabbagebaggage.net'
            });
            res.end(content);
        }
    });
}

function serveResearchFile(relPath, res) {
    const normalized = path.normalize(relPath).replace(/^(\.\.(\/|\\|$))+/, '');
    const fullPath = path.join(WORKSPACE_DIR, normalized);
    
    if (!fullPath.startsWith(WORKSPACE_DIR)) {
        res.writeHead(403, { 'Content-Type': 'text/plain' });
        res.end('Forbidden');
        return;
    }
    
    fs.stat(fullPath, (err, stats) => {
        if (err || !stats.isFile()) {
            res.writeHead(404, { 'Content-Type': 'text/plain' });
            res.end('File not found');
            return;
        }
        
        const ext = path.extname(fullPath).toLowerCase();
        const mimeTypes = {
            '.md': 'text/markdown; charset=utf-8',
            '.html': 'text/html; charset=utf-8',
            '.tex': 'text/plain; charset=utf-8',
            '.pdf': 'application/pdf',
            '.json': 'application/json'
        };
        const contentType = mimeTypes[ext] || 'text/plain; charset=utf-8';
        
        res.writeHead(200, { 
            'Content-Type': contentType,
            'Access-Control-Allow-Origin': 'https://clawhub.cabbagebaggage.net'
        });
        
        const readStream = fs.createReadStream(fullPath);
        readStream.pipe(res);
    });
}

server.listen(PORT, () => {
    console.log(`Dashboard server running at http://localhost:${PORT}/`);
    console.log(`Research API at http://localhost:${PORT}/api/research`);
});

process.on('SIGINT', () => {
    server.close(() => process.exit(0));
});
