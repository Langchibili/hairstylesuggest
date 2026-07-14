'use strict';

const { createCoreService } = require('@strapi/strapi').factories;

module.exports = createCoreService('api::session.session', ({ strapi }) => ({
  /**
   * Find a session and verify it belongs to a given user.
   * Throws a 403-ready error if the user doesn't own it.
   */
  async findOwned(sessionId, userId) {
    const session = await strapi.db.query('api::session.session').findOne({
      where:   { id: sessionId },
      populate: ['user'],
    });

    if (!session) return null;
    if (String(session.user?.id) !== String(userId)) {
      const err = new Error('Forbidden');
      err.status = 403;
      throw err;
    }

    return session;
  },

  /**
   * Calculate and persist the total cost for a session by summing generation_result costs.
   */
  async recalculateCost(sessionId) {
    const results = await strapi.db.query('api::generation-result.generation-result').findMany({
      where:  { session: { id: sessionId } },
      select: ['cost_usd'],
    });

    const total = results.reduce((sum, r) => sum + Number(r.cost_usd || 0), 0);

    await strapi.db.query('api::session.session').update({
      where: { id: sessionId },
      data:  { total_cost_usd: Math.round(total * 10000) / 10000 },
    });

    return total;
  },
}));
