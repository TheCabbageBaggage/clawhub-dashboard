/**
 * Dashboard Server - Serves dashboard and research API
 */

const http = require('http');
const fs = require('fs');
const path = require('path');
const url = require('url');

const PORT = 3001;
const DASHBOARD_DIR = __dirname;
const WORKSPACE_DIR = path.join(DASHBOARD_DIR, 'data', 'research-files');

const server = http.createServer((req, res) => {
    const parsedUrl = url.parse(req.url, true);
    const pathname = parsedUrl.pathname;
    
    console.log(`${new Date().toISOString()} ${req.method} ${pathname}`);
    
    // API endpoint - basic data
    if (pathname === '/api/data') {
        res.writeHead(200, {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
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
                'Access-Control-Allow-Origin': '*'
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
            'Access-Control-Allow-Origin': '*'
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
