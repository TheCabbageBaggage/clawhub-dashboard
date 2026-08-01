<?php
/**
 * Newsletter Dashboard Data API
 * Aggregates data from newsletter JSON files
 */

header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET');

$archiveDir = '../../archive/newsletters/v2/';
$cacheFile = 'cache.json';
$cacheDuration = 300; // 5 minutes cache

// Check cache
if (file_exists($cacheFile) && (time() - filemtime($cacheFile)) < $cacheDuration) {
    echo file_get_contents($cacheFile);
    exit;
}

// Initialize data structures
$data = [
    'system' => [
        'status' => 'healthy',
        'uptime_days' => 0,
        'last_check' => date('c'),
        'oracle_server' => ['online' => true]
    ],
    'metrics' => [
        'total_newsletters' => 0,
        'total_articles' => 0,
        'total_sources' => 0,
        'last_generation' => null,
        'success_rate' => 0
    ],
    'articles' => [],
    'sources' => [],
    'topics' => [],
    'knowledge_graph' => [
        'nodes' => [],
        'links' => []
    ],
    'timeline' => []
];

// Get all newsletter files
$files = glob($archiveDir . '*.json');
$data['metrics']['total_newsletters'] = count($files);

if (empty($files)) {
    echo json_encode($data, JSON_PRETTY_PRINT);
    exit;
}

// Sort by date (newest first)
usort($files, function($a, $b) {
    return filemtime($b) - filemtime($a);
});

$topicCounts = [];
$sourceCounts = [];
$labelCounts = [];
$allArticles = [];
$nodes = [];
$links = [];
$nodeIndex = 0;
$nodeMap = [];

// Process each newsletter file
foreach ($files as $file) {
    $content = file_get_contents($file);
    $newsletter = json_decode($content, true);
    
    if (!$newsletter) continue;
    
    // Update last generation
    if (!empty($newsletter['generated_at'])) {
        $data['metrics']['last_generation'] = $newsletter['generated_at'];
    }
    
    // Add metrics
    if (!empty($newsletter['metrics'])) {
        $data['metrics']['total_articles'] += $newsletter['metrics']['published_articles'] ?? 0;
        $data['metrics']['total_sources'] = max($data['metrics']['total_sources'], $newsletter['metrics']['sources_selected'] ?? 0);
    }
    
    // Process knowledge graph
    if (!empty($newsletter['knowledge_graph']['nodes'])) {
        foreach ($newsletter['knowledge_graph']['nodes'] as $node) {
            $nodeId = $node['id'];
            
            if (!isset($nodeMap[$nodeId])) {
                $nodeMap[$nodeId] = $nodeIndex++;
                $nodes[] = [
                    'id' => $nodeId,
                    'kind' => $node['kind'],
                    'label' => $node['kind'] === 'article' ? ($node['title'] ?? $nodeId) : 
                               ($node['kind'] === 'source' ? ($node['name'] ?? $nodeId) : 
                               ($node['label'] ?? $node['token'] ?? $nodeId)),
                    'url' => $node['url'] ?? null,
                    'size' => $node['kind'] === 'article' ? 10 : ($node['kind'] === 'source' ? 20 : 15),
                    'group' => $node['kind']
                ];
            }
            
            // Count topics and labels
            if ($node['kind'] === 'topic') {
                $token = $node['token'] ?? $nodeId;
                $topicCounts[$token] = ($topicCounts[$token] ?? 0) + 1;
            }
            if ($node['kind'] === 'label') {
                $label = $node['label'] ?? $nodeId;
                $labelCounts[$label] = ($labelCounts[$label] ?? 0) + 1;
            }
            if ($node['kind'] === 'source') {
                $sourceId = $node['name'] ?? $nodeId;
                $sourceCounts[$sourceId] = ($sourceCounts[$sourceId] ?? 0) + 1;
            }
        }
    }
    
    // Process edges
    if (!empty($newsletter['knowledge_graph']['edges'])) {
        foreach ($newsletter['knowledge_graph']['edges'] as $edge) {
            if (isset($nodeMap[$edge['source']]) && isset($nodeMap[$edge['target']])) {
                $links[] = [
                    'source' => $edge['source'],
                    'target' => $edge['target'],
                    'type' => $edge['relation'] ?? 'relates_to'
                ];
            }
        }
    }
    
    // Process articles from story cards
    if (!empty($newsletter['story_rollup'])) {
        foreach ($newsletter['story_rollup'] as $story) {
            if (!empty($story['title']) && $story['title'] !== 'Story Rollup') {
                $allArticles[] = [
                    'title' => $story['title'],
                    'source' => $story['source'] ?? 'Unknown',
                    'url' => $story['url'] ?? '#',
                    'summary' => $story['summary'] ?? '',
                    'date' => $newsletter['generated_at'] ?? date('c'),
                    'labels' => $story['labels'] ?? [],
                    'theme' => $story['theme'] ?? 'General'
                ];
            }
        }
    }
    
    // Timeline data
    if (!empty($newsletter['generated_at'])) {
        $data['timeline'][] = [
            'date' => $newsletter['generated_at'],
            'articles' => $newsletter['metrics']['published_articles'] ?? 0,
            'sources' => $newsletter['metrics']['sources_with_results'] ?? 0
        ];
    }
}

// Build source statistics
foreach ($sourceCounts as $source => $count) {
    $data['sources'][] = [
        'name' => $source,
        'count' => $count,
        'percentage' => round(($count / max(array_values($sourceCounts))) * 100, 1)
    ];
}

// Sort sources by count
usort($data['sources'], function($a, $b) {
    return $b['count'] - $a['count'];
});

// Build topic statistics
arsort($topicCounts);
$data['topics'] = array_slice(array_map(function($topic, $count) {
    return ['name' => $topic, 'count' => $count];
}, array_keys($topicCounts), array_values($topicCounts)), 0, 50);

// Sort articles by date
usort($allArticles, function($a, $b) {
    return strtotime($b['date']) - strtotime($a['date']);
});
$data['articles'] = $allArticles;

// Build knowledge graph
$data['knowledge_graph'] = [
    'nodes' => array_slice($nodes, 0, 300), // Limit nodes for performance
    'links' => $links
];

// Calculate success rate from ingestion report
$successCount = 0;
$totalCount = 0;
if (!empty($newsletter['ingestion_report'])) {
    foreach ($newsletter['ingestion_report'] as $report) {
        $totalCount++;
        if ($report['metrics']['status'] === 'success') {
            $successCount++;
        }
    }
}
$data['metrics']['success_rate'] = $totalCount > 0 ? round(($successCount / $totalCount) * 100, 1) : 0;

// Calculate uptime (days since first newsletter)
if (!empty($files)) {
    $oldestFile = end($files);
    $firstDate = filemtime($oldestFile);
    $data['system']['uptime_days'] = round((time() - $firstDate) / 86400);
}

// Save cache
file_put_contents($cacheFile, json_encode($data, JSON_PRETTY_PRINT));

echo json_encode($data, JSON_PRETTY_PRINT);
?>