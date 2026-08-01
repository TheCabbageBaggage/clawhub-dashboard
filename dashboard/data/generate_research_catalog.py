import os, json, re
from datetime import datetime

workspace = "/data/.openclaw/workspace"
dirs = ["research", "business", "reports", "business-plans", "projects"]

catalog = []

def extract_summary(filepath):
    """Extract first meaningful paragraph as summary."""
    try:
        with open(filepath, 'r') as f:
            content = f.read(3000)
        # Try to find executive summary or first substantial paragraph
        lines = content.split('\n')
        summary = ""
        in_summary = False
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith('#') or stripped.startswith('---'):
                if in_summary and summary:
                    break
                continue
            if re.match(r'(Executive Summary|Summary|Zusammenfassung|Abstract|Overview)', stripped, re.I):
                in_summary = True
                continue
            if in_summary or len(stripped) > 60:
                summary += stripped + " "
                if len(summary) > 300:
                    break
        if not summary:
            # Fallback: first non-header paragraph
            for line in lines:
                s = line.strip()
                if s and not s.startswith('#') and not s.startswith('---') and len(s) > 40:
                    summary = s[:300]
                    break
        return summary.strip()[:300]
    except:
        return ""

def get_date(filepath):
    """Extract date from filename or content."""
    # Try filename date patterns
    basename = os.path.basename(filepath)
    date_match = re.search(r'(\d{8})', basename)
    if date_match:
        try:
            return datetime.strptime(date_match.group(1), '%Y%m%d').isoformat()
        except:
            pass
    # Try content date
    try:
        with open(filepath, 'r') as f:
            for line in f:
                m = re.search(r'Date:\s*(.+)$', line)
                if m:
                    return m.group(1).strip()
                if re.search(r'^\d{4}-\d{2}-\d{2}', line):
                    return line.strip()[:10]
    except:
        pass
    # Fallback: file mtime
    try:
        mtime = os.path.getmtime(filepath)
        return datetime.fromtimestamp(mtime).isoformat()
    except:
        return ""

def categorize(filepath, filename):
    """Categorize research."""
    rel = os.path.relpath(filepath, workspace)
    name_lower = filename.lower()
    
    if 'grant' in name_lower or 'funding' in name_lower or 'förder' in name_lower:
        return "Funding & Grants"
    if 'business' in name_lower and ('plan' in name_lower or 'case' in name_lower or 'model' in name_lower):
        return "Business Planning"
    if 'financial' in name_lower or 'revenue' in name_lower or 'cost' in name_lower:
        return "Financial Analysis"
    if 'competitor' in name_lower or 'market' in name_lower or 'compar' in name_lower:
        return "Market & Competition"
    if 'risk' in name_lower or 'mitigation' in name_lower:
        return "Risk Analysis"
    if 'roadmap' in name_lower or 'go_to_market' in name_lower or 'gtm' in name_lower:
        return "Go-to-Market"
    if 'micro' in name_lower or 'validation' in name_lower or 'reddit' in name_lower:
        return "Micro Business Validation"
    if 'personal' in name_lower or 'assistant' in name_lower or 'calendar' in name_lower:
        return "Personal Assistant Strategy"
    if 'codex' in name_lower or 'openai' in name_lower or 'model' in name_lower or 'free_ai' in name_lower:
        return "AI Tools & Models"
    if 'cloud' in name_lower or 'hardware' in name_lower or 'hosting' in name_lower:
        return "Infrastructure"
    if 'api' in name_lower or 'service' in name_lower:
        return "API Services"
    if 'phase' in name_lower or 'research' in name_lower or 'analysis' in name_lower:
        return "Research & Analysis"
    if 'sap' in name_lower or 'finance' in name_lower or 'curriculum' in name_lower:
        return "Learning & Education"
    if 'medium' in name_lower or 'article' in name_lower or 'blog' in name_lower:
        return "Content & Publishing"
    if 'agent' in name_lower and 'mesh' in name_lower:
        return "Agent Architecture"
    if 'token' in name_lower or 'audit' in name_lower:
        return "Token & Cost Analysis"
    if 'ambient' in name_lower:
        return "Hardware & IoT"
    if 'night' in name_lower or 'shift' in name_lower:
        return "Automation"
    if 'briefing' in name_lower or 'hub' in name_lower:
        return "Briefing Systems"
    if 'self-assessment' in name_lower or 'report' in name_lower:
        return "Reports & Assessments"
    if 'cfo' in name_lower or 'master' in name_lower:
        return "CFO & Financial Reports"
    if 'physiq' in name_lower or 'arca' in name_lower or 'odoo' in name_lower:
        return "Product Analysis"
    if 'kroatien' in name_lower or 'memo' in name_lower:
        return "Travel & Personal"
    return "Other"

for d in dirs:
    full = os.path.join(workspace, d)
    if not os.path.isdir(full):
        continue
    for root, dirs_, files in os.walk(full):
        # Skip some dirs
        dirs_[:] = [x for x in dirs_ if x not in ('node_modules', '.git', 'charts', 'vps', 'mxchip', 'hardware', 'security', 'book-reviews', 'night-shift')]
        for f in files:
            if f.startswith('.'):
                continue
            ext = os.path.splitext(f)[1].lower()
            if ext not in ('.md', '.html', '.pdf', '.tex'):
                continue
            filepath = os.path.join(root, f)
            relpath = os.path.relpath(filepath, workspace)
            summary = extract_summary(filepath) if ext in ('.md', '.tex') else ""
            date = get_date(filepath)
            category = categorize(filepath, f)
            
            # Generate a nice title from filename
            title = os.path.splitext(f)[0].replace('_', ' ').replace('-', ' ')
            # Clean up
            title = re.sub(r'\s+', ' ', title).strip()
            title = title[:80]
            
            catalog.append({
                "id": relpath.replace('/', '_').replace('.', '_'),
                "title": title,
                "category": category,
                "date": date,
                "summary": summary,
                "path": relpath,
                "type": ext[1:].upper()
            })

# Sort by date descending
catalog.sort(key=lambda x: x['date'] or '', reverse=True)

with open('/data/.openclaw/workspace/dashboard/data/research_catalog.json', 'w') as f:
    json.dump(catalog, f, indent=2, ensure_ascii=False)

print(f"Generated catalog with {len(catalog)} entries")
for c in catalog[:5]:
    print(f"  [{c['category']}] {c['title']} ({c['type']})")
