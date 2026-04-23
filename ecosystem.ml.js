module.exports = {
  apps: [{
    name: 'physiq-ml',
    cwd: '/home/ubuntu/physiq-ml',
    script: 'python3',
    args: '-m uvicorn app.main:app --host 0.0.0.0 --port 8001',
    interpreter: 'none',
    env: { PYTHONPATH: '/home/ubuntu/physiq-ml' }
  }]
};
