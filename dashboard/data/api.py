#!/usr/bin/env python3
"""
Newsletter Dashboard Data API
Aggregates data from newsletter JSON files
"""

import json
import os
from datetime import datetime
from pathlib import Path
from glob import glob

ARCHIVE_DIR = '../../archive/newsletters/v2/'
CACHE_FILE = 'cache.json'
CACHE_DURATION = 300  # 5 minutes


def load_data():
    """Load and aggregate newsletter data."""
    # Check cache
    cache_path = Path(CACHE_FILE)
    if cache_path.exists():
        cache_age = datetime.now().timestamp() - cache_path.stat().st_mtime
        if cache_age < CACHE_DURATION:
            with open(cache_path, 'r') as f:
                return json.load(f)

    # Initialize data
    data = {
        "system": {
            "status": "healthy",
            "uptime_days": 0,
            "last_check": datetime.now().isoformat(),
            "oracle_server": {"online": True}
        },
        "metrics": {
            "total_newsletters": 0,
            "total_articles": 0,
            "total_sources": 0,
            "last_generation": None,
            "success_rate": 0
        },
        "articles": [],
        "sources": [],
        "topics": [],
        "knowledge_graph": {
            "nodes": [],
            "links": []
        },
        "timeline": []
    }

    # Get all newsletter files
    files = glob(os.path.join(ARCHIVE_DIR, '*.json'))
    data['metrics']['total_newsletters'] = len(files)

    if not files:
        return data

    # Sort by modification time (newest first)
    files.sort(key=lambda f: os.path.getmtime(f), reverse=True)

    topic_counts = {}
    source_counts = {}
    label_counts = {}
    all_articles = []
    nodes = []
    links = []
    node_index = 0
    node_map = {}

    # Process each newsletter file
    for file in files:
        try:
            with open(file, 'r') as f:
                newsletter = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue

        # Update last generation
        if newsletter.get('generated_at'):
            data['metrics']['last_generation'] = newsletter['generated_at']

        # Add metrics
        if newsletter.get('metrics'):
            data['metrics']['total_articles'] += newsletter['metrics'].get('published_articles', 0)
            data['metrics']['total_sources'] = max(
                data['metrics']['total_sources'],
                newsletter['metrics'].get('sources_selected', 0)
            )

        # Process knowledge graph
        if newsletter.get('knowledge_graph', {}).get('nodes'):
            for node in newsletter['knowledge_graph']['nodes']:
                node_id = node['id']
                if node_id not in node_map:
                    node_map[node_id] = node_index
                    node_index += 1
                    
                    label = node.get('title', node_id)
                    if node.get('kind') == 'source':
                        label = node.get('name', node_id)
                    elif node.get('kind') in ('label', 'topic'):
                        label = node.get('label', node.get('token', node_id))
                    
                    nodes.append({
                        'id': node_id,
                        'kind': node['kind'],
                        'label': label,
                        'url': node.get('url'),
                        'size': 15 if node['kind'] == 'article' else 20,
                        'group': node['kind']
                    })

                # Count topics and labels
                if node.get('kind') == 'topic':
                    token = node.get('token', node_id)
                    topic_counts[token] = topic_counts.get(token, 0) + 1
                if node.get('kind') == 'label':
                    label = node.get('label', node_id)
                    label_counts[label] = label_counts.get(label, 0) + 1
                if node.get('kind') == 'source':
                    source_id = node.get('name', node_id)
                    source_counts[source_id] = source_counts.get(source_id, 0) + 1

        # Process edges
        if newsletter.get('knowledge_graph', {}).get('edges'):
            for edge in newsletter['knowledge_graph']['edges']:
                if edge['source'] in node_map and edge['target'] in node_map:
                    links.append({
                        'source': edge['source'],
                        'target': edge['target'],
                        'type': edge.get('relation', 'relates_to')
                    })

        # Process articles from story rollup
        if newsletter.get('story_rollup'):
            for story in newsletter['story_rollup']:
                if story.get('title') and story['title'] != 'Story Rollup':
                    all_articles.append({
                        'title': story['title'],
                        'source': story.get('source', 'Unknown'),
                        'url': story.get('url', '#'),
                        'summary': story.get('summary', ''),
                        'date': newsletter.get('generated_at', datetime.now().isoformat()),
                        'labels': story.get('labels', []),
                        'theme': story.get('theme', 'General')
                    })

        # Timeline data
        if newsletter.get('generated_at'):
            data['timeline'].append({
                'date': newsletter['generated_at'],
                'articles': newsletter['metrics'].get('published_articles', 0),
                'sources': newsletter['metrics'].get('sources_with_results', 0)
            })

    # Build source statistics
    for source, count in sorted(source_counts.items(), key=lambda x: x[1], reverse=True):
        data['sources'].append({
            'name': source,
            'count': count,
            'percentage': round((count / max(source_counts.values())) * 100, 1) if source_counts else 0
        })

    # Build topic statistics (top 50)
    sorted_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)
    for topic, count in sorted_topics[:50]:
        data['topics'].append({'name': topic, 'count': count})

    # Sort articles by date
    all_articles.sort(key=lambda x: x['date'], reverse=True)
    data['articles'] = all_articles

    # Build knowledge graph (limit nodes for performance)
    data['knowledge_graph'] = {
        'nodes': nodes[:300],
        'links': links
    }

    # Calculate success rate
    success_count = 0
    total_count = 0
    if newsletter.get('ingestion_report'):
        for report in newsletter['ingestion_report']:
            total_count += 1
            if report.get('metrics', {}).get('status') == 'success':
                success_count += 1
    data['metrics']['success_rate'] = round((success_count / total_count) * 100, 1) if total_count else 0

    # Calculate uptime
    if files:
        oldest_file = min(files, key=lambda f: os.path.getmtime(f))
        first_date = os.path.getmtime(oldest_file)
        data['system']['uptime_days'] = round((datetime.now().timestamp() - first_date) / 86400)

    # Save cache
    with open(CACHE_FILE, 'w') as f:
        json.dump(data, f, indent=2)

    return data


if __name__ == '__main__':
    data = load_data()
    print("Content-Type: application/json\n")
    print(json.dumps(data, indent=2))
