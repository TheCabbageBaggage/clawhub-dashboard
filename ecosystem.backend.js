module.exports = {
  apps: [{
    name: 'physiq-backend',
    cwd: '/home/ubuntu/physiq-app/backend',
    script: 'python3',
    args: '-m uvicorn app.main:app --host 0.0.0.0 --port 3001',
    interpreter: 'none',
    env: { PYTHONPATH: '/home/ubuntu/physiq-app/backend' }
  }]
};
