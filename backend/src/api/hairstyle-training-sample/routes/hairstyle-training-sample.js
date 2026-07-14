'use strict';

module.exports = {
    routes: [
        {
            method: 'POST',
            path: '/training-samples',
            handler: 'hairstyle-training-sample.create',
            config: {
                auth: {},
                policies: [],
            },
        },
        {
            method: 'GET',
            path: '/training-samples',
            handler: 'hairstyle-training-sample.find',
            config: {
                auth: {},
                policies: [],
            },
        },
        {
            method: 'PATCH',
            path: '/training-samples/:id/approve',
            handler: 'hairstyle-training-sample.approve',
            config: {
                auth: {},
                policies: [],
            },
        },
    ],
};