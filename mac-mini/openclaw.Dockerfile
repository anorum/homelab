FROM ghcr.io/openclaw/openclaw:latest
USER root

# Install Homebrew and fix ownership so `node` user can run brew
RUN /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
    && chown -R node:node /home/linuxbrew/.linuxbrew

# Install clawhub globally and fix npm global dir ownership
RUN npm install -g clawhub \
    && chown -R node:node /usr/local/lib/node_modules /usr/local/bin
COPY openclaw-entrypoint.sh /usr/local/bin/openclaw-entrypoint.sh
RUN chmod +x /usr/local/bin/openclaw-entrypoint.sh
USER node

ENTRYPOINT ["/usr/local/bin/openclaw-entrypoint.sh"]
CMD ["node", "openclaw.mjs", "gateway", "--allow-unconfigured"]
