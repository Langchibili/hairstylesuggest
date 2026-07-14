'use strict';

module.exports = {
  routes: [
    {
      method:  'POST',
      path:    '/ratings',
      handler: 'generation-result.submitRating',
      config:  { auth: true, policies: [] },
    },
  ],
};
