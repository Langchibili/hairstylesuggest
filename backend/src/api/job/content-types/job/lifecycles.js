'use strict';

/**
 * Job lifecycle hooks.
 * NOTE: The FastAPI worker claims jobs via raw MySQL (SELECT FOR UPDATE SKIP LOCKED),
 * which bypasses these hooks. Hooks only fire when Strapi's own db.query is used
 * (e.g. when Strapi creates a job or processes the webhook callback).
 */
module.exports = {
    /**
     * Stamp queued_at on creation if not already set.
     */
    async beforeCreate(event) {
        const { data } = event.params;
        if (!data.queued_at) {
            data.queued_at = new Date().toISOString();
        }
    },

    /**
     * Log new job creation so you can tail the Strapi log during development.
     */
    async afterCreate(event) {
        const { result } = event;
        strapi.log.info(
            `[job] Queued job ${result.id} | type: ${result.type} | session: ${result.session?.id ?? result.session}`
        );
    },

    /**
     * When a job transitions to "complete", update the parent session status.
     * If all jobs for a session are complete → session.status = "complete".
     * If at least one is complete but others are still running → "partial".
     */
    async afterUpdate(event) {
        const { result } = event;

        strapi.log.info(`[job] Job ${result.id} → ${result.status}`);

        if (result.status !== 'complete' && result.status !== 'failed') return;

        const sessionId = result.session?.id ?? result.session;
        if (!sessionId) return;

        try {
            const allJobs = await strapi.db.query('api::job.job').findMany({
                where: { session: { id: sessionId } },
                select: ['id', 'status', 'type'],
            });

            const total = allJobs.length;
            const complete = allJobs.filter(j => j.status === 'complete').length;
            const failed = allJobs.filter(j => j.status === 'failed').length;

            let newStatus;
            if (complete === total) newStatus = 'complete';
            else if (failed === total) newStatus = 'failed';
            else if (complete > 0) newStatus = 'partial';
            else return; // still running, no change yet

            await strapi.db.query('api::style-gen-session.style-gen-session').update({
                where: { id: sessionId },
                data: { status: newStatus },
            });

            strapi.log.info(`[job] Session ${sessionId} status → ${newStatus}`);
        } catch (err) {
            strapi.log.error('[job][afterUpdate] Failed to update session status:', err.message);
        }
    },
};