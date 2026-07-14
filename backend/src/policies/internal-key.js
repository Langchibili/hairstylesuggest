//backend\src\policies\internal-key.js
'use strict';

/**
 * Policy: internal-key
 *
 * Validates that the incoming request carries a correct X-Internal-Key header.
 * Used on all /internal/* routes to prevent public access to webhook endpoints.
 *
 * The key must match the INTERNAL_SERVICE_KEY environment variable shared between
 * Strapi and the FastAPI AI service.
 *
 * Usage in a route definition:
 *   config: { auth: false, policies: ['global::internal-key'] }
 */
module.exports = (policyContext) => {
    const incomingKey = policyContext.request.headers['x-internal-key'];
    const expectedKey = process.env.INTERNAL_SERVICE_KEY;

    if (!expectedKey) {
        strapi.log.error('[policy][internal-key] INTERNAL_SERVICE_KEY env var is not set!');
        return false;
    }

    if (!incomingKey || incomingKey !== expectedKey) {
        strapi.log.warn(
            `[policy][internal-key] Rejected request from ${policyContext.request.ip} — key mismatch`
        );
        return false;
    }

    return true;
};