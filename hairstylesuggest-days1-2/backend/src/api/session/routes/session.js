'use strict';

/**
 * Session custom routes.
 * All routes listed here correspond 1-to-1 with Part 3.1 of the master plan.
 *
 * auth: true  → requires a valid users-permissions JWT in the Authorization header.
 * auth: false → public (used only for internal webhooks, guarded by internal-key policy instead).
 */
module.exports = {
  routes: [
    // ── Core session flow ────────────────────────────────────────────────
    {
      method:  'POST',
      path:    '/sessions',
      handler: 'session.create',
      config:  {
        auth:       true,
        policies:   [],
        middlewares: [],
      },
    },
    {
      method:  'POST',
      path:    '/sessions/:id/confirm-uploads',
      handler: 'session.confirmUploads',
      config:  { auth: true, policies: [] },
    },
    {
      method:  'GET',
      path:    '/sessions/:id/status',
      handler: 'session.getStatus',
      config:  { auth: true, policies: [] },
    },
    {
      method:  'POST',
      path:    '/sessions/:id/focus/:hairstyleId',
      handler: 'session.triggerFocusRender',
      config:  { auth: true, policies: [] },
    },
    {
      method:  'GET',
      path:    '/sessions/:id/results',
      handler: 'session.getResults',
      config:  { auth: true, policies: [] },
    },

    // ── User history (lives here to reuse session controller context) ──
    {
      method:  'GET',
      path:    '/users/me/history',
      handler: 'session.getUserHistory',
      config:  { auth: true, policies: [] },
    },
  ],
};
