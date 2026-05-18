'use strict';

/**
 * Internal webhook routes.
 *
 * auth: false  — These endpoints bypass Strapi JWT authentication entirely.
 * policy: global::internal-key — validates the X-Internal-Key header instead.
 *
 * These paths intentionally start with /internal/ to make it obvious in logs
 * and to allow easy firewall rules (e.g. block /internal/* from public traffic).
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