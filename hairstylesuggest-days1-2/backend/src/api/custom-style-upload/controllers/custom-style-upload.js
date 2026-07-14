'use strict';

const { createCoreController } = require('@strapi/strapi').factories;
const r2 = require('../../../utils/r2-uploader');
const { v4: uuidv4 } = require('uuid');

module.exports = createCoreController('api::custom-style-upload.custom-style-upload', ({ strapi }) => ({

  // ─────────────────────────────────────────────────────────────────────────
  // POST /api/sessions/:id/custom-style
  // Returns a presigned R2 URL for uploading a reference hairstyle photo.
  // ─────────────────────────────────────────────────────────────────────────
  async requestUpload(ctx) {
    const user = ctx.state.user;
    if (!user) return ctx.unauthorized();

    const sessionId = ctx.params.id;
    const session = await strapi.db.query('api::session.session').findOne({
      where:   { id: sessionId },
      populate: ['user'],
    });

    if (!session) return ctx.notFound('Session not found.');
    if (session.user?.id !== user.id) return ctx.forbidden();

    const uploadId = uuidv4();

    let presigned;
    try {
      presigned = await r2.generateCustomStyleUploadUrl(String(sessionId), uploadId);
    } catch (err) {
      strapi.log.error('[custom-style-upload][requestUpload] R2 error:', err.message);
      return ctx.internalServerError('Failed to generate upload URL.');
    }

    // Create a placeholder row so we can track this upload
    let record;
    try {
      record = await strapi.db.query('api::custom-style-upload.custom-style-upload').create({
        data: {
          session: { id: sessionId },
          user:    { id: user.id },
          r2_image_key: presigned.key,
          cdn_url:      presigned.cdnUrl,
          status:       'uploaded', // optimistic — client will PUT then confirm
        },
      });
    } catch (err) {
      strapi.log.error('[custom-style-upload][requestUpload] DB error:', err.message);
      return ctx.internalServerError('Failed to create upload record.');
    }

    return ctx.send({
      uploadId:   record.id,
      uploadUrl:  presigned.uploadUrl,
      cdnUrl:     presigned.cdnUrl,
      key:        presigned.key,
      expiresIn:  300,
    });
  },

  // ─────────────────────────────────────────────────────────────────────────
  // POST /api/sessions/:id/custom-style/confirm
  // Body: { uploadId }
  // Confirms client has PUT the image; enqueues a style_extraction job.
  // ─────────────────────────────────────────────────────────────────────────
  async confirmUpload(ctx) {
    const user = ctx.state.user;
    if (!user) return ctx.unauthorized();

    const sessionId        = ctx.params.id;
    const { uploadId }     = ctx.request.body;

    if (!uploadId) return ctx.badRequest('uploadId is required.');

    const record = await strapi.db.query('api::custom-style-upload.custom-style-upload').findOne({
      where:   { id: uploadId },
      populate: ['session', 'user'],
    });

    if (!record) return ctx.notFound('Upload record not found.');
    if (record.user?.id !== user.id) return ctx.forbidden();
    if (String(record.session?.id) !== String(sessionId)) return ctx.badRequest('Session mismatch.');

    // Enqueue the style extraction job
    let job;
    try {
      job = await strapi.db.query('api::job.job').create({
        data: {
          session:      { id: sessionId },
          type:         'style_extraction',
          status:       'queued',
          payload: {
            session_id:         String(sessionId),
            custom_upload_id:   String(uploadId),
            r2_image_key:       record.r2_image_key,
            cdn_url:            record.cdn_url,
          },
          attempt_count: 0,
          queued_at:    new Date().toISOString(),
        },
      });
    } catch (err) {
      strapi.log.error('[custom-style-upload][confirmUpload] Failed to enqueue job:', err.message);
      return ctx.internalServerError('Failed to enqueue style extraction job.');
    }

    // Update record with job reference and new status
    await strapi.db.query('api::custom-style-upload.custom-style-upload').update({
      where: { id: uploadId },
      data:  { extraction_job_id: String(job.id), status: 'extracting' },
    });

    return ctx.send({
      uploadId:  uploadId,
      jobId:     job.id,
      status:    'extracting',
      message:   'Style extraction job queued.',
    });
  },

  // ─────────────────────────────────────────────────────────────────────────
  // GET /api/sessions/:id/custom-style/status
  // Poll endpoint for extraction progress.
  // ─────────────────────────────────────────────────────────────────────────
  async getStatus(ctx) {
    const user = ctx.state.user;
    if (!user) return ctx.unauthorized();

    const sessionId = ctx.params.id;
    const session   = await strapi.db.query('api::session.session').findOne({
      where:   { id: sessionId },
      populate: ['user'],
    });

    if (!session) return ctx.notFound();
    if (session.user?.id !== user.id) return ctx.forbidden();

    const uploads = await strapi.db.query('api::custom-style-upload.custom-style-upload').findMany({
      where:   { session: { id: sessionId } },
      orderBy: { createdAt: 'desc' },
      limit:   1,
    });

    if (!uploads.length) return ctx.notFound('No custom style upload found for this session.');

    const latest = uploads[0];

    return ctx.send({
      uploadId:              latest.id,
      status:                latest.status,
      extractedStylePrompt:  latest.extracted_style_prompt,
      extractedMaskUrl:      latest.extracted_mask_key
        ? `${process.env.R2_PUBLIC_URL}/${latest.extracted_mask_key}`
        : null,
    });
  },
}));
