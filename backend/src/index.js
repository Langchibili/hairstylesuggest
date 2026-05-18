'use strict';

/**
 * Strapi application entry point.
 *
 * register()  — Called before plugins are loaded.
 * bootstrap() — Called after all plugins and routes are registered.
 *               Use this to set up any startup logic.
 */
module.exports = {
  register(/*{ strapi }*/) {
    // Nothing to register at boot — all content types are defined in their
    // respective schema.json files and auto-registered by Strapi.
  },

  async bootstrap({ strapi }) {
    // ── Verify critical environment variables are set ────────────────────
    const requiredEnvVars = [
      'JWT_SECRET',
      'INTERNAL_SERVICE_KEY',
      'R2_ACCOUNT_ID',
      'R2_ACCESS_KEY_ID',
      'R2_SECRET_ACCESS_KEY',
      'R2_BUCKET_NAME',
      'R2_PUBLIC_URL',
    ];

    const missing = requiredEnvVars.filter(k => !process.env[k]);
    if (missing.length > 0) {
      strapi.log.warn(
        `[bootstrap] The following environment variables are not set: ${missing.join(', ')}. ` +
        'Copy .env.example to .env and fill in the values.'
      );
    }

    // ── Log startup summary ──────────────────────────────────────────────
    strapi.log.info('='.repeat(60));
    strapi.log.info('  HairstyleSuggest AI — Strapi Backend');
    strapi.log.info(`  Environment  : ${process.env.NODE_ENV}`);
    strapi.log.info(`  Database     : ${process.env.DATABASE_HOST}:${process.env.DATABASE_PORT}/${process.env.DATABASE_NAME}`);
    strapi.log.info(`  R2 Bucket    : ${process.env.R2_BUCKET_NAME || '(not set)'}`);
    strapi.log.info(`  AI Service   : ${process.env.AI_SERVICE_URL || '(not set)'}`);
    strapi.log.info('='.repeat(60));

    // ── Reset monthly session counts at the start of each month ─────────
    // In production, use a proper cron scheduler (node-cron or Strapi cron plugin).
    // This is a simple check that runs once at startup.
    const now = new Date();
    if (now.getDate() === 1 && now.getHours() < 2) {
      strapi.log.info('[bootstrap] First day of month — resetting monthly_session_count for all users.');
      try {
        await strapi.db.query('plugin::users-permissions.user').updateMany({
          where: {},
          data: { monthly_session_count: 0 },
        });
      } catch (err) {
        strapi.log.error('[bootstrap] Failed to reset monthly_session_count:', err.message);
      }
    }
  },
};