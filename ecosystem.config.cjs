module.exports = {
  apps: [
    {
      name: 'thesisound',
      cwd: '/home/ubuntu/thesisound',
      script: '/root/.local/bin/uv',
      args: 'run thesisound-web',
      interpreter: 'none',
      instances: 1,
      exec_mode: 'fork',
      autorestart: true,
      max_restarts: 20,
      min_uptime: '5s',
      env: {
        PATH: '/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
      },
    },
  ],
};
