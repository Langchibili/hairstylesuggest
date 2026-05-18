'use strict';

/**
 * Hairstyle lifecycle hooks.
 * Fired by Strapi on create/update/delete operations via strapi.db.query.
 */
module.exports = {
    /**
     * Ensure sort_order is set when a new hairstyle is created without one.
     */
    async beforeCreate(event) {
        const { data } = event.params;

        if (data.sort_order === undefined || data.sort_order === null) {
            // Find the current maximum sort_order and increment
            const entries = await strapi.db.query('api::hairstyle.hairstyle').findMany({
                orderBy: { sort_order: 'desc' },
                limit: 1,
                select: ['sort_order'],
            });

            const maxOrder = entries.length > 0 ? (entries[0].sort_order || 0) : 0;
            data.sort_order = maxOrder + 1;
        }
    },

    /**
     * Log hairstyle creation for audit purposes.
     */
    async afterCreate(event) {
        const { result } = event;
        strapi.log.info(`[hairstyle] Created: "${result.display_name}" (${result.slug})`);
    },

    /**
     * When a hairstyle is deactivated, log a warning.
     * Future: you could cancel queued jobs that reference this hairstyle.
     */
    async afterUpdate(event) {
        const { result, params } = event;

        if (params.data && params.data.active === false) {
            strapi.log.warn(
                `[hairstyle] Deactivated: "${result.display_name}" (id: ${result.id}). ` +
                'Any in-flight generation jobs may still complete.'
            );
        }
    },
};