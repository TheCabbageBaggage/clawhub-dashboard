/**
 * Newsletter Dashboard Data API
 * Aggregates data from newsletter JSON files
 */

const fs = require('fs');
const path = require('path');

const ARCHIVE_DIR = '/data/.openclaw/workspace/archive/newsletters/v2/';
const CACHE_FILE = 'cache.json';
const CACHE_DURATION = 5 * 60 * 1000; // 5 minutes

function loadData() {
    // Check cache
    if (fs.existsSync(CACHE_FILE)) {
        const cacheStat = fs.statSync(CACHE_FILE);
        const cacheAge = Date.now() - cacheStat.mtimeMs;
        if (cacheAge < CACHE_DURATION) {
            const cacheContent = fs.readFileSync(CACHE_FILE, 'utf-8');
            return JSON.parse(cacheContent);
        }
    }

    // Initialize data
    const data = {
        system: {
            status: 'healthy',
            uptime_days: 0,
            last_check: new Date().toISOString(),
            oracle_server: { online: true }
        },
        metrics: {
            total_newsletters: 0,
            total_articles: 0,
            total_sources: 0,
            last_generation: null,
            success_rate: 0
        },
        articles: [],
        sources: [],
        topics: [],
        knowledge_graph: {
            nodes: [],
            links: []
        },
        timeline: []
    };

    // Get all newsletter files
    const files = fs.readdirSync(ARCHIVE_DIR)
        .filter(f => f.endsWith('.json'))
        .map(f => path.join(ARCHIVE_DIR, f));
    
    data.metrics.total_newsletters = files.length;

    if (files.length === 0) {
        return data;
    }

    // Sort by modification time (newest first)
    files.sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs);

    const topicCounts = {};
    const sourceCounts = {};
    const labelCounts = {};
    const allArticles = [];
    const nodes = [];
    const links = [];
    const nodeMap = new Map();
    let nodeIndex = 0;
    let lastNewsletter = null;

    // Process each newsletter file
    for (const file of files) {
        let newsletter;
        try {
            const content = fs.readFileSync(file, 'utf-8');
            newsletter = JSON.parse(content);
        } catch (e) {
            console.error(`Error parsing ${file}:`, e.message);
            continue;
        }

        lastNewsletter = newsletter;

        // Update last generation
        if (newsletter.generated_at) {
            data.metrics.last_generation = newsletter.generated_at;
        }

        // Add metrics
        if (newsletter.metrics) {
            data.metrics.total_articles += newsletter.metrics.published_articles || 0;
            data.metrics.total_sources = Math.max(
                data.metrics.total_sources,
                newsletter.metrics.sources_selected || 0
            );
        }

        // Process knowledge graph
        if (newsletter.knowledge_graph?.nodes) {
            for (const node of newsletter.knowledge_graph.nodes) {
                const nodeId = node.id;
                if (!nodeMap.has(nodeId)) {
                    nodeMap.set(nodeId, nodeIndex++);
                    
                    let label = node.title || nodeId;
                    if (node.kind === 'source') {
                        label = node.name || nodeId;
                    } else if (node.kind === 'label' || node.kind === 'topic') {
                        label = node.label || node.token || nodeId;
                    }
                    
                    nodes.push({
                        id: nodeId,
                        kind: node.kind,
                        label: label,
                        url: node.url || null,
                        size: node.kind === 'article' ? 10 : (node.kind === 'source' ? 20 : 15),
                        group: node.kind
                    });
                }

                // Count topics and labels
                if (node.kind === 'topic') {
                    const token = node.token || nodeId;
                    topicCounts[token] = (topicCounts[token] || 0) + 1;
                }
                if (node.kind === 'label') {
                    const label = node.label || nodeId;
                    labelCounts[label] = (labelCounts[label] || 0) + 1;
                }
                if (node.kind === 'source') {
                    const sourceId = node.name || nodeId;
                    sourceCounts[sourceId] = (sourceCounts[sourceId] || 0) + 1;
                }
                
                // Extract articles from story_rollup instead
                // Articles will be extracted from story_rollup array below
            }
        }

        // Process edges
        if (newsletter.knowledge_graph?.edges) {
            for (const edge of newsletter.knowledge_graph.edges) {
                if (nodeMap.has(edge.source) && nodeMap.has(edge.target)) {
                    links.push({
                        source: edge.source,
                        target: edge.target,
                        type: edge.relation || 'relates_to'
                    });
                }
            }
        }

        // Timeline data
        if (newsletter.generated_at) {
            data.timeline.push({
                date: newsletter.generated_at,
                articles: newsletter.metrics?.published_articles || 0,
                sources: newsletter.metrics?.sources_with_results || 0
            });
        }
    }

    // Build source statistics
    const sortedSources = Object.entries(sourceCounts)
        .sort((a, b) => b[1] - a[1]);
    const maxSourceCount = sortedSources[0]?.[1] || 1;
    
    for (const [source, count] of sortedSources) {
        data.sources.push({
            name: source,
            count: count,
            percentage: Math.round((count / maxSourceCount) * 100 * 10) / 10
        });
    }

    // Build topic statistics (top 50)
    const sortedTopics = Object.entries(topicCounts)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 50);
    
    for (const [topic, count] of sortedTopics) {
        data.topics.push({ name: topic, count: count });
    }

    // Sort articles by date
    allArticles.sort((a, b) => new Date(b.date) - new Date(a.date));
    data.articles = allArticles;

    // Build knowledge graph (limit nodes for performance)
    data.knowledge_graph = {
        nodes: nodes.slice(0, 300),
        links: links
    };

    // Calculate success rate
    let successCount = 0;
    let totalCount = 0;
    if (lastNewsletter?.ingestion_report) {
        for (const report of lastNewsletter.ingestion_report) {
            totalCount++;
            if (report.metrics?.status === 'success') {
                successCount++;
            }
        }
    }
    data.metrics.success_rate = totalCount > 0 
        ? Math.round((successCount / totalCount) * 100 * 10) / 10 
        : 0;

    // Calculate uptime
    if (files.length > 0) {
        const oldestFile = files[files.length - 1];
        const firstDate = fs.statSync(oldestFile).mtimeMs;
        data.system.uptime_days = Math.round((Date.now() - firstDate) / (1000 * 60 * 60 * 24));
    }

    // Save cache
    fs.writeFileSync(CACHE_FILE, JSON.stringify(data, null, 2));

    return data;
}

// If called as script
if (require.main === module) {
    const data = loadData();
    console.log(JSON.stringify(data, null, 2));
}

module.exports = { loadData };
