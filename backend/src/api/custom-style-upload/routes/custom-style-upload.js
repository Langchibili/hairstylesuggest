'use strict';

module.exports = {
    routes: [
        {
            method: 'POST',
            path: '/sessions/:id/custom-style',
            handler: 'custom-style-upload.requestUpload',
            config: { auth: {}, policies: [] },
        },
        {
            method: 'POST',
            path: '/sessions/:id/custom-style/confirm',
            handler: 'custom-style-upload.confirmUpload',
            config: { auth: {}, policies: [] },
        },
        {
            method: 'GET',
            path: '/sessions/:id/custom-style/status',
            handler: 'custom-style-upload.getStatus',
            config: { auth: {}, policies: [] },
        },
    ],
};