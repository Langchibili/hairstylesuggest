'use strict';

module.exports = {
    routes: [
        {
            method: 'GET',
            path: '/hairstyles',
            handler: 'hairstyle.find',
            config: { auth: true, policies: [] },
        },
        {
            method: 'GET',
            path: '/hairstyles/:slug',
            handler: 'hairstyle.findOne',
            config: { auth: true, policies: [] },
        },
    ],
};