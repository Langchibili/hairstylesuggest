'use strict';

const { createCoreController } = require('@strapi/strapi').factories;
const r2 = require('../../../utils/r2-uploader');
const { v4: uuidv4 } = require('uuid');

const SESSION_ANGLES = ['front', 'left', 'right', 'top'];

module.exports = createCoreController('api::session.session', ({ strapi }) => ({

  // ─────────────────────────────────────────────────────────────────────────
  // POST /api/sessions
  // Creates a session row and returns R2 presigned upload URLs for 4 photos.
  // ─────────────────────────────────────────────────────────────────────────
  async create(ctx) {
    const user = ctx.state.user;
    if (!user) return ctx.unauthorized('You must be logged in.');

    // Check free tier limit (10 sessions/month)
    const tierLimits = { free: 10, pro: 100, salon: 1000 };
    const limit = tierLimits[user.subscription_tier] ?? 10;

    if (user.monthly_session_count >= limit) {
      return ctx.forbidden(
        `Monthly session limit reached (${limit} sessions for ${user.subscription_tier} tier).`
      );
    }

    let session;
    try {
      session = await strapi.db.query('api::session.session').create({
        data: {
          user:   { id: user.id },
          status: 'created',
          source_images: [],
        },
      });
    } catch (err) {
      strapi.log.error('[session][create] DB error:', err.message);
      return ctx.internalServerError('Failed to create session.');
    }

    // Generate presigned R2 upload URLs for each angle
    let uploads;
    try {
      uploads = await r2.generateSessionUploadUrls(String(session.id), SESSION_ANGLES);
    } catch (err) {
      strapi.log.error('[session][create] R2 presign error:', err.message);
      // Clean up the orphaned session row
      await strapi.db.query('api::session.session').delete({ where: { id: session.id } }).catch(() => {});
      return ctx.internalServerError('Failed to generate upload URLs.');
    }

    // Persist the expected R2 keys into source_images so we can verify on confirm
    const sourceImages = uploads.map(u => ({ angle: u.angle, key: u.key, cdnUrl: u.cdnUrl }));
    await strapi.db.query('api::session.session').update({
      where: { id: session.id },
      data:  { status: 'uploading', source_images: sourceImages },
    });

    return ctx.send({
      sessionId: session.id,
      status:    'uploading',
      uploads:   uploads.map(u => ({
        angle:     u.angle,
        uploadUrl: u.uploadUrl,
        cdnUrl:    u.cdnUrl,
        key:       u.key,
      })),
    });
  },

  // ─────────────────────────────────────────────────────────────────────────
  // POST /api/sessions/:id/confirm-uploads
  // Called after client has PUT all photos to R2.
  // Moves session → processing and enqueues a preview_batch job.
  // ─────────────────────────────────────────────────────────────────────────
  async confirmUploads(ctx) {
    const user = ctx.state.user;
    if (!user) return ctx.unauthorized();

    const sessionId = ctx.params.id;
    const session   = await strapi.db.query('api::session.session').findOne({
      where:   { id: sessionId },
      populate: ['user'],
    });

    if (!session) return ctx.notFound('Session not found.');
    if (session.user?.id !== user.id) return ctx.forbidden();
    if (session.status !== 'uploading') {
      return ctx.badRequest(`Session is in "${session.status}" state; expected "uploading".`);
    }

    // Fetch all active hairstyle IDs for the batch payload
    const hairstyles = await strapi.db.query('api::hairstyle.hairstyle').findMany({
      where:  { active: true },
      select: ['id', 'slug', 'display_name', 'category', 'lora_checkpoint', 'lora_weight',
               'base_prompt', 'negative_prompt', 'is_premium', 'source_type'],
      orderBy: { sort_order: 'asc' },
    });

    // Build job payload
    const payload = {
      session_id:   String(sessionId),
      source_images: session.source_images || [],
      hairstyles:   hairstyles,
    };

    // Enqueue the preview_batch job
    let job;
    try {
      job = await strapi.db.query('api::job.job').create({
        data: {
          session:      { id: sessionId },
          type:         'preview_batch',
          status:       'queued',
          payload,
          attempt_count: 0,
          queued_at:    new Date().toISOString(),
        },
      });
    } catch (err) {
      strapi.log.error('[session][confirmUploads] Failed to enqueue job:', err.message);
      return ctx.internalServerError('Failed to enqueue generation job.');
    }

    // Advance session status
    await strapi.db.query('api::session.session').update({
      where: { id: sessionId },
      data:  { status: 'processing' },
    });

    return ctx.send({
      sessionId: sessionId,
      status:    'processing',
      jobId:     job.id,
      message:   'Uploads confirmed. Generation started.',
    });
  },

  // ─────────────────────────────────────────────────────────────────────────
  // GET /api/sessions/:id/status
  // Poll endpoint for the mobile app.
  // Returns current status + any available CDN URLs.
  // ─────────────────────────────────────────────────────────────────────────
  async getStatus(ctx) {
    const user = ctx.state.user;
    if (!user) return ctx.unauthorized();

    const sessionId = ctx.params.id;
    const session = await strapi.db.query('api::session.session').findOne({
      where:   { id: sessionId },
      populate: ['user'],
    });

    if (!session) return ctx.notFound();
    if (session.user?.id !== user.id) return ctx.forbidden();

    // Fetch completed generation results for this session
    const results = await strapi.db.query('api::generation-result.generation-result').findMany({
      where:   { session: { id: sessionId } },
      populate: ['hairstyle'],
      orderBy: { createdAt: 'asc' },
    });

    // Check if any jobs have failed
    const jobs = await strapi.db.query('api::job.job').findMany({
      where:  { session: { id: sessionId } },
      select: ['id', 'status', 'type', 'error_message', 'attempt_count'],
    });

    const availableStyles = results.map(r => ({
      resultId:    r.id,
      hairstyleId: r.hairstyle?.id,
      hairstyleSlug: r.hairstyle?.slug,
      renderTier:  r.render_tier,
      angles:      r.angles || [],
      identityScore: r.identity_score,
    }));

    return ctx.send({
      sessionId:       sessionId,
      status:          session.status,
      availableStyles,
      jobs: jobs.map(j => ({ id: j.id, type: j.type, status: j.status, attempts: j.attempt_count })),
      completedAt:     session.completed_at,
    });
  },

  // ─────────────────────────────────────────────────────────────────────────
  // POST /api/sessions/:id/focus/:hairstyleId
  // Triggers a 3-angle focus render for a single hairstyle.
  // ─────────────────────────────────────────────────────────────────────────
  async triggerFocusRender(ctx) {
    const user = ctx.state.user;
    if (!user) return ctx.unauthorized();

    const { id: sessionId, hairstyleId } = ctx.params;

    const session = await strapi.db.query('api::session.session').findOne({
      where:   { id: sessionId },
      populate: ['user'],
    });

    if (!session) return ctx.notFound('Session not found.');
    if (session.user?.id !== user.id) return ctx.forbidden();

    if (!['partial', 'complete'].includes(session.status)) {
      return ctx.badRequest(
        `Session must be in "partial" or "complete" state to trigger a focus render. Current: "${session.status}".`
      );
    }

    const hairstyle = await strapi.db.query('api::hairstyle.hairstyle').findOne({
      where:  { id: hairstyleId },
      select: ['id', 'slug', 'display_name', 'lora_checkpoint', 'lora_weight',
               'base_prompt', 'negative_prompt', 'source_type'],
    });

    if (!hairstyle) return ctx.notFound('Hairstyle not found.');

    // Check for an existing focus render for this session + hairstyle
    const existingResult = await strapi.db.query('api::generation-result.generation-result').findMany({
      where: {
        session:    { id: sessionId },
        hairstyle:  { id: hairstyleId },
        render_tier: 'focus',
      },
      limit: 1,
    });

    if (existingResult.length > 0) {
      return ctx.send({
        message:  'Focus render already exists for this hairstyle.',
        resultId: existingResult[0].id,
      });
    }

    const payload = {
      session_id:    String(sessionId),
      hairstyle_id:  String(hairstyleId),
      hairstyle,
      source_images: session.source_images || [],
      angles:        ['left', 'front', 'right'], // 3-angle focus set
      face_analysis: session.face_analysis,
    };

    let job;
    try {
      job = await strapi.db.query('api::job.job').create({
        data: {
          session:      { id: sessionId },
          type:         'focus_render',
          status:       'queued',
          payload,
          attempt_count: 0,
          queued_at:    new Date().toISOString(),
        },
      });
    } catch (err) {
      strapi.log.error('[session][triggerFocusRender] Failed to enqueue job:', err.message);
      return ctx.internalServerError('Failed to enqueue focus render job.');
    }

    return ctx.send({
      sessionId:   sessionId,
      hairstyleId: hairstyleId,
      jobId:       job.id,
      status:      'queued',
      message:     'Focus render job queued.',
    });
  },

  // ─────────────────────────────────────────────────────────────────────────
  // GET /api/sessions/:id/results
  // Returns full result set for a completed session.
  // ─────────────────────────────────────────────────────────────────────────
  async getResults(ctx) {
    const user = ctx.state.user;
    if (!user) return ctx.unauthorized();

    const sessionId = ctx.params.id;
    const session = await strapi.db.query('api::session.session').findOne({
      where:   { id: sessionId },
      populate: ['user'],
    });

    if (!session) return ctx.notFound();
    if (session.user?.id !== user.id) return ctx.forbidden();

    const results = await strapi.db.query('api::generation-result.generation-result').findMany({
      where:   { session: { id: sessionId } },
      populate: ['hairstyle'],
      orderBy: [{ render_tier: 'asc' }, { createdAt: 'asc' }],
    });

    return ctx.send({
      sessionId:  sessionId,
      status:     session.status,
      totalCost:  session.total_cost_usd,
      results: results.map(r => ({
        id:            r.id,
        hairstyle:     {
          id:          r.hairstyle?.id,
          slug:        r.hairstyle?.slug,
          displayName: r.hairstyle?.display_name,
          category:    r.hairstyle?.category,
          isPremium:   r.hairstyle?.is_premium,
        },
        renderTier:    r.render_tier,
        angles:        r.angles || [],
        identityScore: r.identity_score,
        gpuSeconds:    r.gpu_seconds,
        costUsd:       r.cost_usd,
        userRating:    r.user_rating,
        createdAt:     r.createdAt,
      })),
    });
  },

  // ─────────────────────────────────────────────────────────────────────────
  // GET /api/users/me/history
  // Returns past sessions with thumbnail URLs for the history screen.
  // ─────────────────────────────────────────────────────────────────────────
  async getUserHistory(ctx) {
    const user = ctx.state.user;
    if (!user) return ctx.unauthorized();

    const { page = 1, pageSize = 20 } = ctx.query;
    const offset = (Number(page) - 1) * Number(pageSize);

    const sessions = await strapi.db.query('api::session.session').findMany({
      where:   { user: { id: user.id } },
      orderBy: { createdAt: 'desc' },
      limit:   Number(pageSize),
      offset,
    });

    // For each session, grab the first preview result as a thumbnail
    const sessionIds = sessions.map(s => s.id);
    const allResults = sessionIds.length
      ? await strapi.db.query('api::generation-result.generation-result').findMany({
          where:   { session: { id: { $in: sessionIds } }, render_tier: 'preview' },
          select:  ['id', 'angles', 'session'],
          orderBy: { createdAt: 'asc' },
        })
      : [];

    // Group first result per session
    const thumbnailBySession = {};
    for (const r of allResults) {
      const sid = r.session?.id ?? r.session;
      if (!thumbnailBySession[sid] && r.angles?.length) {
        const frontAngle = r.angles.find(a => a.angle === 'front') || r.angles[0];
        thumbnailBySession[sid] = frontAngle?.cdn_url || null;
      }
    }

    return ctx.send({
      data: sessions.map(s => ({
        id:          s.id,
        status:      s.status,
        thumbnail:   thumbnailBySession[s.id] || null,
        createdAt:   s.createdAt,
        completedAt: s.completed_at,
        totalCost:   s.total_cost_usd,
      })),
      meta: { page: Number(page), pageSize: Number(pageSize) },
    });
  },
}));
