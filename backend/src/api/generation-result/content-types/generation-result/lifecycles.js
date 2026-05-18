'use strict';

/**
 * Generation Result lifecycle hooks.
 */
module.exports = {
    /**
     * When a user gives a 5-star rating, automatically add the result
     * to the hairstyle_training_samples pool (approved_for_training = false,
     * pending admin review as per the plan).
     */
    async afterUpdate(event) {
        const { result, params } = event;

        // Only act when the rating field was explicitly set to 5
        if (params.data?.user_rating !== 5) return;

        // Avoid creating duplicate samples if re-rated
        const existing = await strapi.db
            .query('api::hairstyle-training-sample.hairstyle-training-sample')
            .findMany({
                where: { generation_result_ref: String(result.id) },
                limit: 1,
            });

        if (existing.length > 0) return;

        try {
            // Pull angle CDN URLs from the result
            const angles = result.angles || [];
            const hairstyleId = result.hairstyle?.id ?? result.hairstyle;

            for (const angle of angles) {
                if (!angle.cdn_url) continue;

                await strapi.db
                    .query('api::hairstyle-training-sample.hairstyle-training-sample')
                    .create({
                        data: {
                            hairstyle: hairstyleId ? { id: hairstyleId } : null,
                            r2_image_key: angle.r2_key || angle.cdn_url,
                            cdn_url: angle.cdn_url,
                            style_label: `auto-from-result-${result.id}`,
                            extraction_status: 'pending',
                            approved_for_training: false,
                            notes: `Auto-added from 5-star rating on generation_result ${result.id}`,
                            generation_result_ref: String(result.id),
                        },
                    });
            }

            strapi.log.info(
                `[generation-result] Auto-queued ${angles.length} training samples from 5-star result ${result.id}`
            );
        } catch (err) {
            strapi.log.error('[generation-result][afterUpdate] Failed to create training samples:', err.message);
        }
    },
};