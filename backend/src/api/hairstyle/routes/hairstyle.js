'use strict';

module.exports = {
    routes: [
        {
            method: 'GET',
            path: '/hairstyles',
            handler: 'hairstyle.find',
            config: {
                auth: {},
                policies: [],
            },
        },
        {
            method: 'GET',
            path: '/hairstyles/:slug',
            handler: 'hairstyle.findOne',
            config: {
                auth: {},
                policies: [],
            },
        },
    ],
};