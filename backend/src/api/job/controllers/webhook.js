'use strict';

/**
 * Webhook controller.
 *
 * These endpoints are called by the FastAPI AI service, NOT by the mobile app.
 * They are protected by the internal-key policy — the AI service must send
 * the X-Internal-Key header with the shared INTERNAL_SERVICE_KEY secret.
 *
 * Flow for a completed job:
 *   FastAPI finishes generating → uploads results to R2 → calls POST /internal/jobs/:id/complete
 *   → this controller creates generation_result rows → lifecycle hook updates session status
 *   → mobile app polling /api/sessions/:id/status picks up the new CDN URLs
 */
module.exports = {

    // ─────────────────────────────────────────────────────────────────────────
    // POST /internal/jobs/:id/complete
    //
    // Body (preview_batch / focus_render):
    // {
    //   results: [
    //     {
    //       hairstyle_id: "...",
    //       render_tier:  "preview" | "focus",
    //       angles: [{ angle: "front", cdn_url: "...", r2_key: "..." }],
    //       identity_score: 0.92,
    //       generation_params: { steps: 28, guidance_scale: 3.5 },
    //       gpu_seconds: 12.4,
    //       cost_usd: 0.008,
    //     }
    //   ],
    //   face_analysis: { ... },       // optional, included in preview_batch result
    //   runpod_job_id: "rp-xxx",
    // }
    //
    // Body (style_extraction):
    // {
    //   custom_upload_id:       "...",
    //   extracted_style_prompt: "medium box braids, center part, dark brown",
    //   extracted_mask_key:     "sessions/.../custom-style/mask.png",
    // }
    // ─────────────────────────────────────────────────────────────────────────
    async jobComplete(ctx) {
        const jobId = ctx.params.id;
        strapi.log.info(`[webhook] jobComplete received for job ${jobId}`);

        // Load the job to know its type and linked session
        const job = await strapi.db.query('api::job.job').findOne({
            where: { id: jobId },
            populate: ['session'],
        });

        if (!job) {
            strapi.log.warn(`[webhook] jobComplete: job ${jobId} not found`);
            return ctx.notFound('Job not found.');
        }

        if (job.status === 'complete') {
            strapi.log.warn(`[webhook] jobComplete: job ${jobId} already marked complete, ignoring duplicate`);
            return ctx.send({ ok: true, message: 'Already complete.' });
        }

        const body = ctx.request.body;
        const sessionId = job.session?.id;

        try {
            if (job.type === 'style_extraction') {
                await handleStyleExtractionComplete(body, jobId, sessionId);
            } else {
                // preview_batch or focus_render
                await handleGenerationComplete(body, job, sessionId);
            }

            // Mark the job as complete — lifecycle hook will then check session status
            await strapi.db.query('api::job.job').update({
                where: { id: jobId },
                data: {
                    status: 'complete',
                    runpod_job_id: body.runpod_job_id || null,
                    completed_at: new Date().toISOString(),
                    error_message: null,
                },
            });

            return ctx.send({ ok: true });

        } catch (err) {
            strapi.log.error(`[webhook] jobComplete: error processing job ${jobId}:`, err.message);
            return ctx.internalServerError('Failed to process job completion.');
        }
    },

    // ─────────────────────────────────────────────────────────────────────────
    // POST /internal/jobs/:id/failed
    //
    // Body: { error_message: "...", attempt_count: 2 }
    // ─────────────────────────────────────────────────────────────────────────
    async jobFailed(ctx) {
        const jobId = ctx.params.id;
        strapi.log.warn(`[webhook] jobFailed received for job ${jobId}`);

        const job = await strapi.db.query('api::job.job').findOne({
            where: { id: jobId },
            populate: ['session'],
        });

        if (!job) return ctx.notFound('Job not found.');

        const { error_message, attempt_count } = ctx.request.body;

        const maxAttempts = 3;
        const newStatus = (attempt_count >= maxAttempts) ? 'failed' : 'retrying';

        await strapi.db.query('api::job.job').update({
            where: { id: jobId },
            data: {
                status: newStatus,
                error_message: error_message || 'Unknown error',
                attempt_count: attempt_count || job.attempt_count,
                completed_at: newStatus === 'failed' ? new Date().toISOString() : null,
            },
        });

        strapi.log.warn(
            `[webhook] Job ${jobId} marked "${newStatus}" ` +
            `(attempt ${attempt_count}/${maxAttempts}): ${error_message}`
        );

        return ctx.send({ ok: true, status: newStatus });
    },
};

// ── Private helpers ──────────────────────────────────────────────────────────

/**
 * Process the payload from a completed preview_batch or focus_render job.
 * Creates generation_result rows in the database.
 */
async function handleGenerationComplete(body, job, sessionId) {
    const { results = [], face_analysis } = body;

    if (!results.length) {
        strapi.log.warn(`[webhook] handleGenerationComplete: job ${job.id} returned 0 results`);
        return;
    }

    // Persist face_analysis back to the session on first preview_batch
    if (face_analysis && job.type === 'preview_batch' && sessionId) {
        await strapi.db.query('api::session.session').update({
            where: { id: sessionId },
            data: { face_analysis },
        });
    }

    // Create a generation_result row for each hairstyle in the batch
    let totalCost = 0;
    for (const r of results) {
        if (!r.hairstyle_id) continue;

        const created = await strapi.db.query('api::generation-result.generation-result').create({
            data: {
                session: sessionId ? { id: sessionId } : null,
                hairstyle: { id: r.hairstyle_id },
                render_tier: r.render_tier || (job.type === 'focus_render' ? 'focus' : 'preview'),
                angles: r.angles || [],
                identity_score: r.identity_score || null,
                generation_params: r.generation_params || null,
                gpu_seconds: r.gpu_seconds || null,
                cost_usd: r.cost_usd || null,
            },
        });

        // Link the result ID back to the job if it's a focus_render
        if (job.type === 'focus_render') {
            await strapi.db.query('api::job.job').update({
                where: { id: job.id },
                data: { generation_result_id: String(created.id) },
            });
        }

        totalCost += Number(r.cost_usd || 0);
    }

    // Update session total cost
    if (sessionId && totalCost > 0) {
        const session = await strapi.db.query('api::session.session').findOne({
            where: { id: sessionId },
            select: ['total_cost_usd'],
        });
        const existing = Number(session?.total_cost_usd || 0);
        await strapi.db.query('api::session.session').update({
            where: { id: sessionId },
            data: { total_cost_usd: Math.round((existing + totalCost) * 10000) / 10000 },
        });
    }
}

/**
 * Process the payload from a completed style_extraction job.
 * Updates the custom_style_upload row with the extracted prompt and mask.
 */
async function handleStyleExtractionComplete(body, jobId, sessionId) {
    const { custom_upload_id, extracted_style_prompt, extracted_mask_key } = body;

    if (!custom_upload_id) {
        strapi.log.warn(`[webhook] handleStyleExtractionComplete: no custom_upload_id in payload for job ${jobId}`);
        return;
    }

    await strapi.db.query('api::custom-style-upload.custom-style-upload').update({
        where: { id: custom_upload_id },
        data: {
            extracted_style_prompt: extracted_style_prompt || null,
            extracted_mask_key: extracted_mask_key || null,
            status: 'ready',
        },
    });

    strapi.log.info(
        `[webhook] Style extraction complete for upload ${custom_upload_id}. ` +
        `Prompt: "${(extracted_style_prompt || '').substring(0, 80)}..."`
    );
}