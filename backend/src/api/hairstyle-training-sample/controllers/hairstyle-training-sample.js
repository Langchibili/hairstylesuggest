'use strict';

const { createCoreController } = require('@strapi/strapi').factories;
const r2 = require('../../../utils/r2-uploader');

module.exports = createCoreController(
    'api::hairstyle-training-sample.hairstyle-training-sample',
    ({ strapi }) => ({

        // ─────────────────────────────────────────────────────────────────────
        // POST /api/training-samples
        // Admin/Pro user uploads a curated hairstyle photo.
        // Returns presigned URL + creates a pending sample record.
        // ─────────────────────────────────────────────────────────────────────
        async create(ctx) {
            const user = ctx.state.user;
            if (!user) return ctx.unauthorized();

            // Only admin or pro users can upload training samples
            const isAdmin = user.role?.type === 'authenticated' || user.role?.name === 'Admin';
            if (!isAdmin && user.subscription_tier === 'free') {
                return ctx.forbidden('Only Pro or Salon tier users can upload training samples.');
            }

            const { category, style_label, hairstyle_id, notes, filename = 'sample.jpg' } = ctx.request.body;

            if (!category) return ctx.badRequest('category is required.');

            let presigned;
            try {
                presigned = await r2.generateTrainingSampleUploadUrl(category, filename);
            } catch (err) {
                strapi.log.error('[training-sample][create] R2 error:', err.message);
                return ctx.internalServerError('Failed to generate upload URL.');
            }

            let record;
            try {
                record = await strapi.db
                    .query('api::hairstyle-training-sample.hairstyle-training-sample')
                    .create({
                        data: {
                            hairstyle: hairstyle_id ? { id: hairstyle_id } : null,
                            uploaded_by_user: { id: user.id },
                            r2_image_key: presigned.key,
                            cdn_url: presigned.cdnUrl,
                            style_label: style_label || null,
                            category,
                            extraction_status: 'pending',
                            approved_for_training: false,
                            notes: notes || null,
                        },
                    });
            } catch (err) {
                strapi.log.error('[training-sample][create] DB error:', err.message);
                return ctx.internalServerError('Failed to create training sample record.');
            }

            // Enqueue a style_extraction job automatically on admin upload
            try {
                await strapi.db.query('api::job.job').create({
                    data: {
                        type: 'style_extraction',
                        status: 'queued',
                        payload: {
                            training_sample_id: String(record.id),
                            r2_image_key: presigned.key,
                            cdn_url: presigned.cdnUrl,
                            mode: 'training_sample',
                        },
                        attempt_count: 0,
                        queued_at: new Date().toISOString(),
                    },
                });
            } catch (err) {
                // Non-fatal: we still return the upload URL; extraction can be retried
                strapi.log.error('[training-sample][create] Failed to queue extraction job:', err.message);
            }

            return ctx.send({
                sampleId: record.id,
                uploadUrl: presigned.uploadUrl,
                cdnUrl: presigned.cdnUrl,
                key: presigned.key,
                expiresIn: 600,
            });
        },

        // ─────────────────────────────────────────────────────────────────────
        // GET /api/training-samples
        // Admin only: list samples with optional filters.
        // ─────────────────────────────────────────────────────────────────────
        async find(ctx) {
            // In production, lock this down via Strapi RBAC — only admins.
            const { category, status, approved, page = 1, pageSize = 50 } = ctx.query;

            const where = {};
            if (category) where.category = category;
            if (status) where.extraction_status = status;
            if (approved !== undefined) where.approved_for_training = approved === 'true';

            const [samples, count] = await Promise.all([
                strapi.db
                    .query('api::hairstyle-training-sample.hairstyle-training-sample')
                    .findMany({
                        where,
                        populate: ['hairstyle', 'uploaded_by_user'],
                        orderBy: { createdAt: 'desc' },
                        limit: Number(pageSize),
                        offset: (Number(page) - 1) * Number(pageSize),
                    }),
                strapi.db
                    .query('api::hairstyle-training-sample.hairstyle-training-sample')
                    .count({ where }),
            ]);

            return ctx.send({
                data: samples,
                meta: {
                    pagination: {
                        page: Number(page),
                        pageSize: Number(pageSize),
                        total: count,
                        pageCount: Math.ceil(count / Number(pageSize)),
                    },
                },
            });
        },

        // ─────────────────────────────────────────────────────────────────────
        // PATCH /api/training-samples/:id/approve
        // Admin approves a sample for LoRA fine-tuning.
        // ─────────────────────────────────────────────────────────────────────
        async approve(ctx) {
            const { id } = ctx.params;
            const { approved = true } = ctx.request.body;

            const sample = await strapi.db
                .query('api::hairstyle-training-sample.hairstyle-training-sample')
                .findOne({ where: { id } });

            if (!sample) return ctx.notFound('Training sample not found.');

            const updated = await strapi.db
                .query('api::hairstyle-training-sample.hairstyle-training-sample')
                .update({
                    where: { id },
                    data: {
                        approved_for_training: Boolean(approved),
                        extraction_status: Boolean(approved) ? 'approved' : 'pending',
                        approved_at: Boolean(approved) ? new Date().toISOString() : null,
                    },
                });

            return ctx.send({
                sampleId: updated.id,
                approved: updated.approved_for_training,
                status: updated.extraction_status,
            });
        },
    })
);