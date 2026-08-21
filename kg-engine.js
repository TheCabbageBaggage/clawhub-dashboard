/**
 * kg-engine.js — Natural-Language Knowledge Graph Query Engine
 *
 * Nimmt eine NL-Query entgegen, übersetzt sie via nemotron-mini (lokal, Ollama)
 * in eine Cypher-artige Query, führt diese gegen den Knowledge Graph aus
 * (kg_full.json) und liefert die passenden Nodes + Edges zurück.
 *
 * Die Engine ist bewusst Cypher-kompatibel gebaut, sodass sie später 1:1 auf
 * Neo4j umziehen kann (Phase 2, wenn Workspace + Embeddings dazukommen).
 *
 * Autor: Clowie | ACTA CI
 */

const fs = require('fs');
const path = require('path');
const http = require('http');
const https = require('https');
const { URL } = require('url');

// --- Konfiguration ---
const OLLAMA_URL = process.env.OLLAMA_URL || 'http://ollama:11434';
const NL_MODEL = process.env.KG_NL_MODEL || 'nemotron-mini:latest';
const KG_PATH = process.env.KG_PATH || path.join(__dirname, 'data', 'kg_full.json');

// ============================================================
//  Graph laden + Indexe
// ============================================================
let _kg = null;
let _kgLoadedAt = 0;
const KG_CACHE_MS = 10 * 60 * 1000;

function loadGraph() {
  const now = Date.now();
  if (_kg && now - _kgLoadedAt < KG_CACHE_MS) return _kg;
  const raw = fs.readFileSync(KG_PATH, 'utf8');
  _kg = JSON.parse(raw);
  _kgLoadedAt = now;
  return _kg;
}

let _index = null;
function getIndex() {
  if (_index) return _index;
  const kg = loadGraph();
  const nodeMap = {};
  const adj = {};
  const byType = {};
  const byLabel = {};
  kg.nodes.forEach(n => {
    nodeMap[n.id] = n;
    (byType[n.type] = byType[n.type] || []).push(n);
    const lbl = (n.label || '').toLowerCase();
    if (lbl) (byLabel[lbl] = byLabel[lbl] || []).push(n);
  });
  kg.edges.forEach(e => {
    (adj[e.source] = adj[e.source] || {})[e.target] = (adj[e.source][e.target] || []).concat([e]);
    (adj[e.target] = adj[e.target] || {})[e.source] = (adj[e.target][e.source] || []).concat([e]);
  });
  _index = { nodeMap, adj, byType, byLabel };
  return _index;
}

// Node-Referenz auflösen: id → Label → Teilstring
function resolveNodeId(ref) {
  const idx = getIndex();
  const s = String(ref);
  if (idx.nodeMap[s]) return s;
  const lower = s.toLowerCase();
  if (idx.byLabel[lower]) {
    let best = idx.byLabel[lower][0];
    for (const n of idx.byLabel[lower]) if ((n.degree || 0) > (best.degree || 0)) best = n;
    return best.id;
  }
  for (const id of Object.keys(idx.nodeMap)) {
    if (id.toLowerCase().includes(lower)) return id;
  }
  return null;
}

// ============================================================
// Ollama-Aufruf (nemotron)
// ============================================================
function ollamaGenerate(prompt, extraOptions = {}) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({
      model: NL_MODEL,
      prompt,
      stream: false,
      options: Object.assign({ temperature: 0.1, num_predict: 250 }, extraOptions)
    });
    const u = new URL(OLLAMA_URL);
    const lib = u.protocol === 'https:' ? https : http;
    const req = lib.request({
      hostname: u.hostname,
      port: u.port || (u.protocol === 'https:' ? 443 : 80),
      path: '/api/generate',
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      timeout: 60000
    }, (res) => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); }
        catch (e) { reject(new Error('Ollama-Response nicht parsebar: ' + data.slice(0, 200))); }
      });
    });
    req.on('error', reject);
    req.on('timeout', () => req.destroy(new Error('Ollama-Timeout')));
    req.write(body);
    req.end();
  });
}

// ============================================================
// NL → Cypher (nemotron)
// ============================================================
function buildSchema() {
  const kg = loadGraph();
  const types = [...new Set(kg.nodes.map(n => n.type))].sort();
  const rels = [...new Set(kg.edges.map(e => e.relation))].sort();
  const exNodes = kg.nodes.slice(0, 3).map(n => `${n.type} {id:'${n.id}', label:'${n.label}'}`).join('\n');
  const exEdges = kg.edges.slice(0, 3).map(e => `${e.source} -[${e.relation}]-> ${e.target}`).join('\n');
  return `GRAPH-SCHEMA:
- Node-Typen: ${types.join(', ')}
- Relation-Typen: ${rels.join(', ')}
Beispiel-Nodes:
${exNodes}
Beispiel-Edges:
${exEdges}

Unterstützte Cypher-Patterns:
- MATCH (n:Person) RETURN n                                  -- alle Nodes eines Typs
- MATCH (p:Person {label:'X'}) RETURN p                      -- Node per Label
- MATCH (p:Person)-[:knows]->(q:Person) RETURN q             -- Nachbarn über Relation
- MATCH (p:Person {label:'A'})-[:works_at]->(o:Organization) RETURN o
- MATCH (p:Person)-[:knows]->(q:Person)-[:works_at]->(o:Organization {label:'B'}) RETURN q
- MATCH (a {label:'A'})-[*1..2]->(b {label:'B'}) RETURN a,b  -- Pfad (variable Hops)
- MATCH (p {label:'A'})-[*1..3]-(q {label:'B'}) RETURN p,q   -- Pfad ohne Richtung`;
}

function nlToCypher(nl) {
  const prompt = `Du bist eine NL-zu-Cypher-Engine fuer einen kleinen Knowledge Graph (LinkedIn-Kontakte und Organisationen).
${buildSchema()}

Regeln:
- Antworte NUR mit der Cypher-artigen Query (ein bis mehrere Statements, durch Semikolon getrennt).
- Keine Erklaerung, kein Markdown, keine Kommentare.
- Nutze die tatsaechlichen Node-/Relation-Typen und Label-Namen aus dem Graphen (z.B. 'Linus Kohl', 'OMV').
- Wenn nichts passt, antworte: MATCH (n) RETURN n

Natural Language Query: ${nl}

Cypher:`;
  return ollamaGenerate(prompt);
}

function isCypherSyntax(s) { return /^\s*MATCH/i.test(s); }

function cleanCypher(s) {
  return String(s).replace(/```/g, '').replace(/^cypher\s*/i, '').trim();
}

// ============================================================
// Cypher-Parser (Subset)
// ============================================================
function parseCypher(cypher) {
  const nodePatterns = [];
  const edgePatterns = [];
  const statements = cypher.split(';').map(s => s.trim()).filter(Boolean);
  for (const stmt of statements) {
    const matchBody = stmt.split(/\bWHERE\b/i)[0];
    // Extrahiere alle MATCH-Patterns (komma- oder mehrfach-joined)
    const matchRe = /MATCH\s+(.+?)(?=\bMATCH\b|$)/gis;
    let mm;
    while ((mm = matchRe.exec(matchBody))) {
      const pattern = mm[1].trim();
      let i = 0;
      while (i < pattern.length) {
        const nodeRe = /^\(\s*(\w+)?\s*(?::\s*([\w]+))?\s*([^)]*)\)/;
        const nMatch = pattern.slice(i).match(nodeRe);
        if (nMatch) {
          const props = {};
          if (nMatch[3]) {
            const propRe = /(\w+)\s*:\s*'([^']*)'/g;
            let pm;
            while ((pm = propRe.exec(nMatch[3]))) props[pm[1]] = pm[2];
          }
          nodePatterns.push({ var: nMatch[1] || null, type: nMatch[2] || null, props });
          i += nMatch[0].length;
          continue;
        }
        const relEdgeRe = /^\s*-\s*\[:\s*([\w]+)\s*\]\s*-+>?/;
        const relEdge = pattern.slice(i).match(relEdgeRe);
        if (relEdge) { edgePatterns.push({ rel: relEdge[1], minHops: 1, maxHops: 1 }); i += relEdge[0].length; continue; }
        const varEdgeRe = /^\s*-\s*\[\s*\*\s*(\d+)?\s*(?:\.\.\s*(\d+))?\s*\]\s*-+>?/;
        const varEdge = pattern.slice(i).match(varEdgeRe);
        if (varEdge) {
          const min = varEdge[1] ? parseInt(varEdge[1]) : 1;
          const max = varEdge[2] ? parseInt(varEdge[2]) : min;
          edgePatterns.push({ rel: null, minHops: min, maxHops: max });
          i += varEdge[0].length;
          continue;
        }
        if (/^\s*->/.test(pattern.slice(i))) {
          edgePatterns.push({ rel: null, minHops: 1, maxHops: 1 });
          i += 2;
          continue;
        }
        if (/^\s*-/.test(pattern.slice(i))) {
          edgePatterns.push({ rel: null, minHops: 1, maxHops: 1 });
          i++;
          while (i < pattern.length && pattern[i] === '-') i++;
          continue;
        }
        i++;
      }
    }
  }
  return { nodePatterns, edgePatterns };
}

// ============================================================
// Pfadsuche (BFS)
// ============================================================
function findPaths(fromId, toId, maxHops) {
  const idx = getIndex();
  if (fromId === toId) return [[fromId]];
  const results = [];
  const visited = new Set([fromId]);
  function dfs(current, path, depth) {
    if (depth > maxHops) return;
    const nbrs = idx.adj[current] || {};
    for (const nbrId of Object.keys(nbrs)) {
      if (nbrId === toId) { results.push(path.concat([toId])); continue; }
      if (!visited.has(nbrId) && depth < maxHops) {
        visited.add(nbrId);
        dfs(nbrId, path.concat([nbrId]), depth + 1);
        visited.delete(nbrId);
      }
    }
  }
  dfs(fromId, [fromId], 1);
  results.sort((a, b) => a.length - b.length);
  return results.slice(0, 5);
}

// ============================================================
// Hauptausführung
// ============================================================
async function runNLQuery(nl, options = {}) {
  const useNL = !options.skipNL && !isCypherSyntax(nl);
  let cypher;
  if (useNL) {
    const resp = await nlToCypher(nl);
    cypher = cleanCypher(resp.response || '');
  } else {
    cypher = cleanCypher(nl);
  }

  let result = executeQuery(cypher);

  // Fallback: wenn nemotron invalides Cypher liefert oder 0 Treffer,
  // extrahiere direkt bekannte Entity-Labels aus der NL-Query
  if (useNL && result.stats.nodes === 0) {
    const fallback = runLabelFallback(nl);
    if (fallback) {
      return {
        query: cypher,
        nl,
        nodes: fallback.nodes,
        edges: fallback.edges,
        stats: { nodes: fallback.nodes.length, edges: fallback.edges.length },
        fallback: true
      };
    }
  }

  return result;
}

// Cypher ausführen (intern)
function executeQuery(cypher) {
  const parsed = parseCypher(cypher);
  const idx = getIndex();
  const kg = loadGraph();
  const nodeIds = new Set();
  const edgeIds = new Set();

  // --- Pfad-Erkennung: 2 Nodes mit label + variable Hops ---
  const labeledNodes = parsed.nodePatterns.filter(np => np.props && np.props.label !== undefined);
  const varHop = parsed.edgePatterns.find(ep => ep.maxHops > 1);

  if (labeledNodes.length >= 2 && varHop) {
    const a = resolveNodeId(labeledNodes[0].props.label);
    const b = resolveNodeId(labeledNodes[1].props.label);
    if (a && b) {
      const paths = findPaths(a, b, varHop.maxHops);
      paths.forEach(p => {
        p.forEach(id => nodeIds.add(id));
        for (let i = 0; i < p.length - 1; i++) {
          const edges = (idx.adj[p[i]] || {})[p[i + 1]] || [];
          edges.forEach(e => edgeIds.add(edgeKey(e)));
        }
      });
    }
  } else {
    // --- Normale Node-Matches ---
    // Anker: erster Node mit label (falls vorhanden)
    const labeledNode = parsed.nodePatterns.find(np => np.props && np.props.label !== undefined);
    const anchorId = labeledNode ? resolveNodeId(labeledNode.props.label) : null;

    if (anchorId && parsed.edgePatterns.length > 0) {
      // Traversal: vom Anker entlang der Relationen alle erreichbaren Nodes sammeln
      const collect = (startId, relation) => {
        const out = new Set([startId]);
        const stack = [startId];
        while (stack.length) {
          const cur = stack.pop();
          const nbrs = (idx.adj[cur] || {});
          for (const nid of Object.keys(nbrs)) {
            const edges = nbrs[nid];
            const matches = relation ? edges.some(e => e.relation === relation) : edges.length > 0;
            if (matches && !out.has(nid)) { out.add(nid); stack.push(nid); }
          }
        }
        return out;
      };

      // Für jede Edge-Pattern-Relation vom Anker traversieren
      const anchorRel = parsed.edgePatterns[0] ? parsed.edgePatterns[0].rel : null;
      collect(anchorId, anchorRel).forEach(id => nodeIds.add(id));
    } else {
      // Einfacher Node-/Typ-Match (keine Edges)
      const matchedIds = new Set();
      for (const np of parsed.nodePatterns) {
        if (np.props && np.props.label !== undefined) {
          const id = resolveNodeId(np.props.label);
          if (id) matchedIds.add(id);
        } else if (np.type) {
          (idx.byType[np.type] || []).forEach(n => matchedIds.add(n.id));
        } else {
          kg.nodes.forEach(n => matchedIds.add(n.id));
        }
      }
      matchedIds.forEach(id => nodeIds.add(id));
    }
    // Edges zwischen gematchten Nodes
    kg.edges.forEach((e, i) => {
      if (nodeIds.has(e.source) && nodeIds.has(e.target)) edgeIds.add('e' + i);
    });
  }

  const resultNodes = kg.nodes.filter(n => nodeIds.has(n.id));
  const resultEdges = kg.edges.map((e, i) => ({ ...e, _i: i }))
    .filter(e => edgeIds.has('e' + e._i))
    .map(({ _i, ...e }) => e);

  return {
    query: cypher,
    nodes: resultNodes,
    edges: resultEdges,
    stats: { nodes: resultNodes.length, edges: resultEdges.length }
  };
}

// Fallback: extrahiere bekannte Entity-Labels direkt aus der NL-Query
function runLabelFallback(nl) {
  const idx = getIndex();
  const kg = loadGraph();
  const text = String(nl);
  const found = new Set();

  for (const [label, nodes] of Object.entries(idx.byLabel)) {
    if (label.length < 3) continue;
    if (text.toLowerCase().includes(label)) {
      nodes.forEach(n => found.add(n.id));
    }
  }

  const hasOrgWord = /firmen?|organisation|unternehmen|firma|arbeitgeber/i.test(text);
  const hasPersonWord = /personen|kontakte|leute|wer kennt/i.test(text);
  if (found.size === 0 && hasOrgWord) idx.byType['Organization'].forEach(n => found.add(n.id));
  if (hasPersonWord && idx.byType['Person']) idx.byType['Person'].forEach(n => found.add(n.id));

  if (found.size === 0) return null;

  const nodeIds = new Set(found);
  // Bei einzelnen gefundenen Personen deren direkte Nachbarn mitnehmen
  const singlePerson = [...found].find(id => idx.nodeMap[id].type === 'Person' && found.size <= 3);
  if (singlePerson) {
    Object.keys(idx.adj[singlePerson] || {}).forEach(nid => nodeIds.add(nid));
  }

  const edgeIds = new Set();
  kg.edges.forEach((e, i) => {
    if (nodeIds.has(e.source) && nodeIds.has(e.target)) edgeIds.add('e' + i);
  });
  const resultNodes = kg.nodes.filter(n => nodeIds.has(n.id));
  const resultEdges = kg.edges.map((e, i) => ({ ...e, _i: i })).filter(e => edgeIds.has('e' + e._i)).map(({ _i, ...e }) => e);
  return { nodes: resultNodes, edges: resultEdges };
}

function edgeKey(e) { return 'e:' + e.source + '|' + e.target + '|' + (e.relation || ''); }

module.exports = { runNLQuery, loadGraph };
