'use strict';

const { createCoreController } = require('@strapi/strapi').factories;

// Jobs are created internally (by session controller) and updated by the webhook controller.
// No public-facing endpoints are needed. The Strapi admin panel handles admin visibility.
module.exports = createCoreController('api::job.job');
