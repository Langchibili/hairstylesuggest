'use strict';

const { createCoreController } = require('@strapi/strapi').factories;

module.exports = createCoreController('api::generation-result.generation-result', ({ strapi }) => ({

  // POST /api/ratings
  // Body: { resultId, rating }   rating: 1-5
  async submitRating(ctx) {
    const user = ctx.state.user;
    if (!user) return ctx.unauthorized();

    const { resultId, rating } = ctx.request.body;

    if (!resultId) return ctx.badRequest('resultId is required.');
    const ratingNum = Number(rating);
    if (!ratingNum || ratingNum < 1 || ratingNum > 5) {
      return ctx.badRequest('rating must be an integer between 1 and 5.');
    }

    // Verify the result belongs to a session owned by this user
    const result = await strapi.db.query('api::generation-result.generation-result').findOne({
      where:   { id: resultId },
      populate: ['session', 'session.user'],
    });

    if (!result) return ctx.notFound('Generation result not found.');
    if (result.session?.user?.id !== user.id) return ctx.forbidden();

    const updated = await strapi.db.query('api::generation-result.generation-result').update({
      where: { id: resultId },
      data:  { user_rating: ratingNum },
    });

    return ctx.send({
      resultId: updated.id,
      rating:   updated.user_rating,
      message:  'Rating saved.',
    });
  },
}));
