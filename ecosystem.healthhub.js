module.exports = {
  apps: [{
    name: 'healthhub',
    cwd: '/home/ubuntu/healthhub-v2/frontend',
    script: 'node_modules/.bin/next',
    args: 'start -p 3000',
    interpreter: 'none',
    env: { NODE_ENV: 'production' }
  }]
};
