'use strict';

// Jobs have no public routes — they are created by Strapi controllers internally
// and updated by the webhook endpoints. The Strapi admin panel provides visibility.
module.exports = { routes: [] };
