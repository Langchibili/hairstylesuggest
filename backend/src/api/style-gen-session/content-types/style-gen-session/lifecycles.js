'use strict';

/**
 * Session lifecycle hooks.
 */
module.exports = {
    /**
     * After a session is created, increment the user's monthly session count.
     */
    async afterCreate(event) {
        const { result } = event;

        if (!result.user) return;

        const userId = result.user.id ?? result.user;

        try {
            const user = await strapi.db
                .query('plugin::users-permissions.user')
                .findOne({ where: { id: userId }, select: ['monthly_session_count'] });

            if (user) {
                await strapi.db.query('plugin::users-permissions.user').update({
                    where: { id: userId },
                    data: { monthly_session_count: (user.monthly_session_count || 0) + 1 },
                });
            }
        } catch (err) {
            strapi.log.error('[session][afterCreate] Failed to increment monthly_session_count:', err.message);
        }

        strapi.log.info(`[session] Created session ${result.id} for user ${userId}`);
    },

    /**
     * After a session status changes to "complete" or "failed", record completed_at.
     */
    async beforeUpdate(event) {
        const { data } = event.params;

        if (data.status === 'complete' || data.status === 'failed') {
            if (!data.completed_at) {
                data.completed_at = new Date().toISOString();
            }
        }
    },

    /**
     * Log status transitions.
     */
    async afterUpdate(event) {
        const { result } = event;
        strapi.log.info(`[session] Session ${result.id} → status: ${result.status}`);
    },
};