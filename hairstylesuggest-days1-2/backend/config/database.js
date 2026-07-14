'use strict';

module.exports = ({ env }) => ({
  connection: {
    client: 'mysql2',
    connection: {
      host:     env('DATABASE_HOST', '127.0.0.1'),
      port:     env.int('DATABASE_PORT', 3306),
      database: env('DATABASE_NAME', 'hairstylesuggest'),
      user:     env('DATABASE_USERNAME', 'hairstylesuggest_user'),
      password: env('DATABASE_PASSWORD', ''),
      ssl: env.bool('DATABASE_SSL', false),
      charset: 'utf8mb4',
    },
    pool: {
      min: env.int('DATABASE_POOL_MIN', 2),
      max: env.int('DATABASE_POOL_MAX', 10),
    },
    acquireConnectionTimeout: env.int('DATABASE_CONNECTION_TIMEOUT', 60000),
    debug: env.bool('DATABASE_DEBUG', false),
  },
});
