'use strict';

const { S3Client, PutObjectCommand, GetObjectCommand } = require('@aws-sdk/client-s3');
const { getSignedUrl } = require('@aws-sdk/s3-request-presigner');

/**
 * Build a configured S3Client pointed at Cloudflare R2.
 * R2 is S3-compatible; the only difference is the custom endpoint.
 */
function buildClient() {
    const accountId = process.env.R2_ACCOUNT_ID;
    const endpoint = process.env.R2_ENDPOINT_URL
        || `https://${accountId}.r2.cloudflarestorage.com`;

    return new S3Client({
        region: 'auto',          // R2 requires "auto"
        endpoint,
        credentials: {
            accessKeyId: process.env.R2_ACCESS_KEY_ID,
            secretAccessKey: process.env.R2_SECRET_ACCESS_KEY,
        },
        // R2 doesn't support path-style, so force virtual-hosted style
        forcePathStyle: false,
    });
}

const BUCKET = () => process.env.R2_BUCKET_NAME || 'hairstylesuggest-assets';
const CDN = () => (process.env.R2_PUBLIC_URL || '').replace(/\/$/, '');

/**
 * Generate a presigned PUT URL so the mobile client can upload directly to R2
 * without routing the binary through Strapi.
 *
 * @param {string} key          - The R2 object key (e.g. "sessions/abc123/front.jpg")
 * @param {string} contentType  - MIME type of the file (e.g. "image/jpeg")
 * @param {number} expiresIn    - Seconds until the URL expires (default 300)
 * @returns {Promise<{uploadUrl: string, cdnUrl: string, key: string}>}
 */
async function generatePresignedPutUrl(key, contentType = 'image/jpeg', expiresIn = 300) {
    const client = buildClient();
    const command = new PutObjectCommand({
        Bucket: BUCKET(),
        Key: key,
        ContentType: contentType,
    });

    const uploadUrl = await getSignedUrl(client, command, { expiresIn });
    const cdnUrl = `${CDN()}/${key}`;

    return { uploadUrl, cdnUrl, key };
}

/**
 * Generate presigned GET URL for private objects (not needed if R2 bucket is public).
 *
 * @param {string} key
 * @param {number} expiresIn
 * @returns {Promise<string>}
 */
async function generatePresignedGetUrl(key, expiresIn = 3600) {
    const client = buildClient();
    const command = new GetObjectCommand({ Bucket: BUCKET(), Key: key });
    return getSignedUrl(client, command, { expiresIn });
}

/**
 * Build the CDN URL for a known R2 key.
 *
 * @param {string} key
 * @returns {string}
 */
function cdnUrlForKey(key) {
    return `${CDN()}/${key}`;
}

/**
 * Generate all presigned upload URLs needed for a session's source photos.
 * Returns an array of {angle, uploadUrl, cdnUrl, key}.
 *
 * @param {string} sessionId
 * @param {string[]} angles   - e.g. ['front', 'left', 'right', 'top']
 * @returns {Promise<Array>}
 */
async function generateSessionUploadUrls(sessionId, angles = ['front', 'left', 'right', 'top']) {
    const results = await Promise.all(
        angles.map(async (angle) => {
            const key = `sessions/${sessionId}/source/${angle}.jpg`;
            const result = await generatePresignedPutUrl(key, 'image/jpeg', 300);
            return { angle, ...result };
        })
    );
    return results;
}

/**
 * Generate a presigned URL for a custom style reference photo.
 *
 * @param {string} sessionId
 * @param {string} uploadId   - A unique identifier for this upload attempt
 * @returns {Promise<{uploadUrl, cdnUrl, key}>}
 */
async function generateCustomStyleUploadUrl(sessionId, uploadId) {
    const key = `sessions/${sessionId}/custom-style/${uploadId}.jpg`;
    return generatePresignedPutUrl(key, 'image/jpeg', 300);
}

/**
 * Generate a presigned URL for a training sample uploaded by admin.
 *
 * @param {string} category
 * @param {string} filename
 * @returns {Promise<{uploadUrl, cdnUrl, key}>}
 */
async function generateTrainingSampleUploadUrl(category, filename) {
    const sanitized = filename.replace(/[^a-zA-Z0-9._-]/g, '_');
    const key = `training-samples/${category}/${Date.now()}_${sanitized}`;
    return generatePresignedPutUrl(key, 'image/jpeg', 600);
}

module.exports = {
    generatePresignedPutUrl,
    generatePresignedGetUrl,
    generateSessionUploadUrls,
    generateCustomStyleUploadUrl,
    generateTrainingSampleUploadUrl,
    cdnUrlForKey,
};