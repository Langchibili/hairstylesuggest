'use strict';

const { createCoreController } = require('@strapi/strapi').factories;

module.exports = createCoreController('api::hairstyle.hairstyle', ({ strapi }) => ({

  // GET /api/hairstyles?category=fade&premium=false&page=1&pageSize=20
  async find(ctx) {
    const { category, premium, page = 1, pageSize = 20 } = ctx.query;

    const where = { active: true };
    if (category) where.category = category;
    if (premium !== undefined) where.is_premium = premium === 'true';

    const [hairstyles, count] = await Promise.all([
      strapi.db.query('api::hairstyle.hairstyle').findMany({
        where,
        select: ['id', 'slug', 'display_name', 'category', 'preview_image_url',
                 'is_premium', 'sort_order', 'source_type', 'lora_weight'],
        orderBy: [{ sort_order: 'asc' }, { display_name: 'asc' }],
        limit:  Number(pageSize),
        offset: (Number(page) - 1) * Number(pageSize),
      }),
      strapi.db.query('api::hairstyle.hairstyle').count({ where }),
    ]);

    return ctx.send({
      data: hairstyles,
      meta: {
        pagination: {
          page:      Number(page),
          pageSize:  Number(pageSize),
          total:     count,
          pageCount: Math.ceil(count / Number(pageSize)),
        },
      },
    });
  },

  // GET /api/hairstyles/:slug
  async findOne(ctx) {
    const { slug } = ctx.params;

    const hairstyle = await strapi.db.query('api::hairstyle.hairstyle').findOne({
      where: { slug, active: true },
    });

    if (!hairstyle) return ctx.notFound('Hairstyle not found.');

    return ctx.send({ data: hairstyle });
  },
}));
