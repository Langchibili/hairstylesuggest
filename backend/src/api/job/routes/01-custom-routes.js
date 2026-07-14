'use strict';

/**
 * Internal webhook routes.
 *
 * These endpoints bypass Strapi JWT authentication and are protected
 * by the global::internal-key policy (X-Internal-Key header check).
 *
 * NOTE: File must be .js not .ts — Strapi v4 does NOT support TypeScript
 * route files in the src/api directory by default without additional config.
 */
module.exports = {
    routes: [
        {
            method: 'POST',
            path: '/internal/jobs/:id/complete',
            handler: 'webhook.jobComplete',
            config: {
                auth: false,
                policies: ['global::internal-key'],
                middlewares: [],
            },
        },
        {
            method: 'POST',
            path: '/internal/jobs/:id/failed',
            handler: 'webhook.jobFailed',
            config: {
                auth: false,
                policies: ['global::internal-key'],
                middlewares: [],
            },
        },
    ],
};