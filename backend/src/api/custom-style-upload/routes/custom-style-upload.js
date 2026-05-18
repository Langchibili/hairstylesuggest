'use strict';

module.exports = {
    routes: [
        {
            method: 'POST',
            path: '/sessions/:id/custom-style',
            handler: 'custom-style-upload.requestUpload',
            config: { auth: true, policies: [] },
        },
        {
            method: 'POST',
            path: '/sessions/:id/custom-style/confirm',
            handler: 'custom-style-upload.confirmUpload',
            config: { auth: true, policies: [] },
        },
        {
            method: 'GET',
            path: '/sessions/:id/custom-style/status',
            handler: 'custom-style-upload.getStatus',
            config: { auth: true, policies: [] },
        },
    ],
};